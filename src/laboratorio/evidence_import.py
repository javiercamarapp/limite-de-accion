"""Bounded offline evidence snapshots; integrity is never external verification."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote, urlsplit, parse_qsl

from .experiment_registry import (
    canonical, strict_json, read_file, _directory, _read_at, _keys,
    SECRET_BYTES,
)

MAX_SPEC = 65_536
MAX_SOURCE = 1_048_576
MAX_TOTAL = 16_777_216
MAX_MANIFEST = 65_536
META_KEYS = ('id', 'title', 'url', 'captured_at', 'source_kind')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
CREDENTIAL = re.compile(r'password|passwd|secret|token|credential|api.?key|private.?key|signature|authorization|^auth$|^key$|^sig$|^code$|access.?key', re.I)
LOCAL_PATH = re.compile(r'''(?:^|[\s=(:,;\[\{"'])(?:/[^/\s]|[A-Za-z]:[\\/]|~[/\\])''')
HTTP_REFERENCE = re.compile(r'''https?://[^\s<>"')\]}]+''', re.I)
STRUCTURED_SECRET = re.compile(
    rb'(?:password|passwd|secret|token|api[_-]?key)["\x27]?\s*[=:]\s*["\x27]?[^\s"\x27,}]{8,}'
    rb'|\bBearer\s+[A-Za-z0-9._~+/-]{8,}', re.I)


class EvidenceImportError(ValueError):
    """Controlled failure without source contents or local paths."""


def _has_secret(data):
    return SECRET_BYTES.search(data) or STRUCTURED_SECRET.search(data)


def _absolute(value):
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or '\x00' in raw or any(p in ('.', '..') for p in raw.split('/')):
        raise ValueError('Unsafe path')
    return Path(os.path.abspath(raw))


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Invalid text')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Control character')
    if _has_secret(value.encode('utf-8')) or LOCAL_PATH.search(HTTP_REFERENCE.sub('', value)):
        raise ValueError('Sensitive metadata')


def _timestamp(value):
    _text(value, 20)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value):
        raise ValueError('Invalid timestamp')
    datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def _url(value):
    _text(value, 2048)
    decoded = unquote(value)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in decoded) or '\\' in decoded:
        raise ValueError('Invalid URL')
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError('Invalid URL')
    if not parts.netloc or parts.port == 0 or '%' in parts.netloc:
        raise ValueError('Invalid URL authority')
    host = parts.hostname
    if parts.netloc.startswith('['):
        ipaddress.IPv6Address(host)
        if not re.fullmatch(r'\[[^\]]+\](?::[0-9]+)?', parts.netloc):
            raise ValueError('Invalid IPv6 authority')
    else:
        if ':' in host or parts.netloc.endswith(':'):
            raise ValueError('Invalid host')
        ascii_host = host.encode('idna').decode('ascii').removesuffix('.')
        if not ascii_host or len(ascii_host) > 253:
            raise ValueError('Invalid host length')
        for label in ascii_host.split('.'):
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label):
                raise ValueError('Invalid host label')
            if label.startswith('xn--'):
                label.encode('ascii').decode('idna')
        if re.fullmatch(r'[0-9.]+', ascii_host):
            ipaddress.IPv4Address(ascii_host)
    if _has_secret(decoded.encode('utf-8')):
        raise ValueError('Sensitive URL')
    for component in (parts.query, parts.fragment):
        for key, _ in parse_qsl(unquote(component), keep_blank_values=True):
            if CREDENTIAL.search(key):
                raise ValueError('Credential parameter')


def _metadata(entry):
    _text(entry['id'], 64)
    if not NAME.fullmatch(entry['id']):
        raise ValueError('Invalid id')
    _text(entry['title'], 256)
    _url(entry['url'])
    _timestamp(entry['captured_at'])
    if entry['source_kind'] not in ('public', 'synthetic', 'authorized'):
        raise ValueError('Invalid source kind')


def _sources(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError('Invalid source count')
    seen = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError('Invalid entry')
        _metadata(entry)
        if entry['id'] in seen:
            raise ValueError('Duplicate id')
        seen.add(entry['id'])


def _content(data):
    data.decode('utf-8', errors='strict')
    if _has_secret(data):
        raise ValueError('Sensitive content')


def _source_path(value):
    if not isinstance(value, str) or not value.startswith('/') or len(value) > 4096:
        raise ValueError('Absolute source path required')
    path = _absolute(value)
    if any(p.lower() in ('.ssh', '.aws', '.git', '.gnupg') for p in path.parts) or path.name.lower().startswith('.env') or path.suffix.lower() in ('.pem', '.key', '.p12', '.pfx') or path.name.lower() in ('credentials', 'id_rsa', 'id_ed25519'):
        raise ValueError('Sensitive path')
    return path


def _write(fd, name, data):
    handle = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        view = memoryview(data)
        while view:
            count = os.write(handle, view)
            if count <= 0:
                raise OSError('Short write')
            view = view[count:]
        os.fsync(handle)
    finally:
        os.close(handle)


def _report(manifest, digest):
    return {'manifest': manifest, 'sha256': digest, 'integrity': 'MATCH',
            'evidence_verified': False, 'authenticity_verified': False}


def _identity(info):
    return info.st_dev, info.st_ino


def _anchor(out, parent, fd, created):
    # Observe the name without following its final symlink, and retain both fds.
    current = os.stat(out.name, dir_fd=parent, follow_symlinks=False)
    parent_name = os.stat(out.parent, follow_symlinks=False)
    if (not stat.S_ISDIR(current.st_mode)
            or not stat.S_ISDIR(parent_name.st_mode)
            or _identity(current) != _identity(created)
            or _identity(os.fstat(fd)) != _identity(created)
            or _identity(parent_name) != _identity(os.fstat(parent))):
        raise ValueError('Output anchor changed')
    # A replaced ancestor symlink would also make the public verifier reject.
    for ancestor in out.parent.parents:
        if not stat.S_ISDIR(os.stat(ancestor, follow_symlinks=False).st_mode):
            raise ValueError('Output ancestor changed')


def _names(fd):
    names = set()
    with os.scandir(fd) as entries:
        for index, entry in enumerate(entries):
            if index >= 17:  # 16 snapshots + manifest; read at most 18 entries.
                raise ValueError('Too many bundle entries')
            names.add(entry.name)
    return names


def _mark_failed(fd):
    # Never unlink or overwrite published files, including foreign replacements.
    try:
        _write(fd, '.failed', b'IMPORT_FAILED\n')
        os.fsync(fd)
    except OSError:
        raise EvidenceImportError('IMPORT_FAILED_UNCERTAIN: failure marker durability unavailable') from None


def import_bundle(spec_path, out_path):
    """Import explicit local UTF-8 files into a new private directory.

    Return a JSON-compatible report. Raise EvidenceImportError on any failure.
    No input writes, external actions, URL visits, or interpretation of content.
    """
    try:
        spec = strict_json(read_file(_absolute(spec_path), MAX_SPEC).decode('utf-8'), MAX_SPEC)
        _keys(spec, ('sources',))
        entries = spec['sources']
        if not isinstance(entries, list):
            raise ValueError('Invalid sources')
        for entry in entries:
            _keys(entry, (*META_KEYS, 'path'))
        _sources(entries)
        snapshots = []
        sources = []
        total = 0
        for index, entry in enumerate(entries, 1):
            data = read_file(_source_path(entry['path']), MAX_SOURCE)
            _content(data)
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError('Total size exceeded')
            name = f'source-{index:02d}.txt'
            sources.append({**{key: entry[key] for key in META_KEYS}, 'snapshot': name,
                            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            snapshots.append((name, data))
        manifest = {'schema_version': 'evidence-bundle.v1',
                    'imported_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'evidence_verified': False, 'sources': sources}
        digest = hashlib.sha256(canonical(manifest)).hexdigest()
        document = canonical({'manifest': manifest, 'sha256': digest})
        if len(document) > MAX_MANIFEST:
            raise ValueError('Manifest size exceeded')
        out = _absolute(out_path)
        with _directory(out.parent) as parent:
            os.mkdir(out.name, 0o700, dir_fd=parent)
            created = os.stat(out.name, dir_fd=parent, follow_symlinks=False)
            fd = os.open(out.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                # Do not write even a failure marker into an observed replacement.
                _anchor(out, parent, fd, created)
                if _names(fd):
                    raise ValueError('Output directory is not empty')
                try:
                    for name, data in snapshots:
                        _anchor(out, parent, fd, created)
                        _write(fd, name, data)
                    _anchor(out, parent, fd, created)
                    _write(fd, '.manifest.pending', document)
                    os.fsync(fd)
                    # Atomic no-replace publication, followed by durable removal of staging.
                    _anchor(out, parent, fd, created)
                    os.link('.manifest.pending', 'manifest.json', src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                    os.fsync(fd)
                    _anchor(out, parent, fd, created)
                    os.unlink('.manifest.pending', dir_fd=fd)
                    os.fsync(fd)
                    os.fsync(parent)
                    _anchor(out, parent, fd, created)
                    if _inspect_fd(fd) != _report(manifest, digest):
                        raise ValueError('Published bundle changed')
                    _anchor(out, parent, fd, created)
                except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
                    _mark_failed(fd)
                    raise
            finally:
                os.close(fd)
        return _report(manifest, digest)
    except EvidenceImportError:
        raise
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise EvidenceImportError('IMPORT_FAILED: invalid input, unsafe file or incomplete write') from None


def _inspect(path):
    with _directory(_absolute(path)) as fd:
        return _inspect_fd(fd)


def _inspect_fd(fd):
    # Reject partial markers before reading payloads; enumeration is bounded.
    names = _names(fd)
    if any(name.startswith('.') for name in names):
        raise ValueError('Partial bundle')
    document = strict_json(_read_at(fd, 'manifest.json', MAX_MANIFEST).decode('utf-8'), MAX_MANIFEST)
    _keys(document, ('manifest', 'sha256'))
    manifest = document['manifest']
    _keys(manifest, ('schema_version', 'imported_at', 'evidence_verified', 'sources'))
    if manifest['schema_version'] != 'evidence-bundle.v1' or manifest['evidence_verified'] is not False:
        raise ValueError('Invalid manifest')
    _timestamp(manifest['imported_at'])
    digest = document['sha256']
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest) or hashlib.sha256(canonical(manifest)).hexdigest() != digest:
        raise ValueError('Manifest hash mismatch')
    entries = manifest['sources']
    if not isinstance(entries, list):
        raise ValueError('Invalid sources')
    for entry in entries:
        _keys(entry, (*META_KEYS, 'snapshot', 'size', 'sha256'))
    _sources(entries)
    expected = {'manifest.json'}
    total = 0
    for index, entry in enumerate(entries, 1):
        name = f'source-{index:02d}.txt'
        if entry['snapshot'] != name or type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_SOURCE:
            raise ValueError('Invalid snapshot metadata')
        digest_source = entry['sha256']
        if not isinstance(digest_source, str) or not DIGEST.fullmatch(digest_source):
            raise ValueError('Invalid hash')
        data = _read_at(fd, name, MAX_SOURCE)
        _content(data)
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != digest_source:
            raise ValueError('Snapshot mismatch')
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError('Total size exceeded')
        expected.add(name)
    if _names(fd) != expected:
        raise ValueError('Unexpected or partial bundle files')
    return _report(manifest, digest)


def verify_bundle(path):
    """Read and rehash the entire bundle; never create, repair or authenticate it."""
    try:
        return _inspect(path)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise EvidenceImportError('VERIFY_FAILED: missing, changed, invalid or incomplete bundle') from None


def show_bundle(path):
    """Return validated metadata with the same read-only checks as verify_bundle."""
    return verify_bundle(path)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"INVALID_ARGUMENTS","evidence_verified":false}\n')


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    importer = commands.add_parser('import')
    importer.add_argument('--spec', required=True)
    importer.add_argument('--out', required=True)
    for name in ('verify', 'show'):
        commands.add_parser(name).add_argument('directory')
    args = parser.parse_args(argv)
    try:
        if args.command == 'import':
            report = import_bundle(args.spec, args.out)
        else:
            report = verify_bundle(args.directory)
    except EvidenceImportError as error:
        print(json.dumps({'error': str(error), 'evidence_verified': False}), file=sys.stderr)
        return 2
    print(canonical(report).decode('utf-8'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
