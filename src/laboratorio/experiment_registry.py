"""Bounded offline experiment manifests. Never executes or authenticates artifacts."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import uuid

MAX_FILE = 2_000_000
MAX_JSON = 64_000
MAX_VERSIONS = 256
MAX_EXPORT = MAX_JSON * MAX_VERSIONS
GROUPS = ('inputs', 'results', 'code')
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
DIGEST = re.compile(r'[a-f0-9]{64}\Z')
SECRET_KEY = re.compile(r'password|passwd|secret|token|credential|api.?key|private.?key', re.I)
SECRET_BYTES = re.compile(rb'-----BEGIN (?:[A-Z ]*PRIVATE KEY)|(?:AKIA|ASIA)[A-Z0-9]{16}|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,}|(?:password|passwd|secret|token|api[_-]?key)\s*[=:]\s*["\x27]?[A-Za-z0-9/+_-]{8,}', re.I)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def _bounded(value, depth=0):
    if depth > 12:
        raise ValueError('JSON nesting limit exceeded')
    if isinstance(value, dict):
        if len(value) > 128 or any(not isinstance(k, str) or len(k) > 256 for k in value):
            raise ValueError('Invalid JSON object')
        for item in value.values():
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_VERSIONS:
            raise ValueError('JSON list limit exceeded')
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > 4096:
            raise ValueError('JSON string limit exceeded')
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Nonfinite number')
    elif type(value) not in (int, bool, type(None)):
        raise ValueError('Invalid JSON value')


def strict_json(data, limit=MAX_JSON):
    if len(data) > limit:
        raise ValueError('JSON size limit exceeded')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Invalid JSON constant')
    try:
        value = json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant)
        _bounded(value)
        return value
    except (RecursionError, UnicodeError) as exc:
        raise ValueError('Invalid JSON encoding or nesting') from exc


def _path(path):
    try:
        raw = os.fspath(path)
    except TypeError:
        raise ValueError('Use an explicit absolute path') from None
    if not isinstance(raw, str) or not raw.startswith('/') or '\x00' in raw:
        raise ValueError('Use an explicit absolute path')
    if any(part in ('.', '..') for part in raw.split('/')):
        raise ValueError('Dot path components forbidden')
    return Path(raw)


@contextmanager
def _directory(path):
    path = _path(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _read_at(fd, name, limit):
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(handle)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Unsafe file')
        if before.st_size > limit:
            raise ValueError('File size limit exceeded')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(handle, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(handle)
        if len(data) > limit:
            raise ValueError('File size limit exceeded')
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('File changed during read')
        return bytes(data)
    finally:
        os.close(handle)


def read_file(path, limit=MAX_JSON):
    path = _path(path)
    with _directory(path.parent) as fd:
        return _read_at(fd, path.name, limit)


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Unexpected or missing fields')


def _name(value):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError('Invalid name')
    if SECRET_BYTES.search(value.encode()):
        raise ValueError('Secret name excluded')


def _configuration(value):
    # Leave room for export -> records -> record -> manifest -> configuration.
    _bounded(value, 4)
    if not isinstance(value, dict) or len(canonical(value)) > 8192:
        raise ValueError('Invalid configuration')
    def walk(item):
        if isinstance(item, dict):
            for key, val in item.items():
                if SECRET_KEY.search(key) or SECRET_BYTES.search(key.encode()):
                    raise ValueError('Secret configuration excluded')
                walk(val)
        elif isinstance(item, list):
            for val in item:
                walk(val)
        elif isinstance(item, str) and (SECRET_BYTES.search(item.encode()) or item.startswith('/')):
            raise ValueError('Secret or path configuration excluded')
    walk(value)


def validate_spec(spec):
    _bounded(spec)
    if len(canonical(spec)) > MAX_JSON:
        raise ValueError('Specification size limit exceeded')
    _keys(spec, ('experiment_id', 'source', 'configuration', *GROUPS))
    _name(spec['experiment_id'])
    if spec['source'] not in ('synthetic', 'authorized'):
        raise ValueError('Source must be synthetic or operator-authorized')
    _configuration(spec['configuration'])
    total = 0
    for group in GROUPS:
        entries = spec[group]
        if not isinstance(entries, list) or (not entries and group != 'results'):
            raise ValueError('Inputs and code must be explicitly provided')
        names = set()
        for entry in entries:
            _keys(entry, ('name', 'path'))
            _name(entry['name'])
            if entry['name'] in names:
                raise ValueError('Duplicate artifact name')
            names.add(entry['name'])
            _path(entry['path'])
        total += len(entries)
    if total > 16:
        raise ValueError('At most 16 artifacts')


def _artifact(entry):
    result = {'name': entry['name'], 'status': 'INVALID', 'sha256': None, 'size': None, 'reason': None}
    path = _path(entry['path'])
    if any(part.lower() in ('.ssh', '.aws', '.git', '.gnupg') for part in path.parts) or path.name.lower().startswith('.env') or path.suffix.lower() in ('.pem', '.key', '.p12', '.pfx') or path.name.lower() in ('id_rsa', 'id_ed25519', 'credentials'):
        result['reason'] = 'SECRET_EXCLUDED'
        return result
    try:
        data = read_file(path, MAX_FILE)
    except FileNotFoundError:
        result.update(status='MISSING', reason='NOT_FOUND')
        return result
    except (OSError, ValueError):
        result['reason'] = 'UNSAFE_FILE'
        return result
    if SECRET_BYTES.search(data):
        result['reason'] = 'SECRET_EXCLUDED'
        return result
    result.update(status='AVAILABLE', sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    return result


def _state(artifacts):
    states = [entry['status'] for group in GROUPS for entry in artifacts[group]]
    if 'INVALID' in states:
        return 'INVALID'
    if 'MISSING' in states or not artifacts['results']:
        return 'MISSING'
    return 'AVAILABLE'


def _validate_records(records):
    if not isinstance(records, list) or len(records) > MAX_VERSIONS:
        raise ValueError('Invalid history size')
    previous = None
    experiment = None
    for index, record in enumerate(records, 1):
        _keys(record, ('manifest', 'sha256'))
        manifest = record['manifest']
        _keys(manifest, ('schema_version', 'experiment_id', 'version', 'previous_sha256', 'recorded_at', 'source', 'configuration', 'artifacts', 'state'))
        if manifest['schema_version'] != 'experiment-manifest.v1' or type(manifest['version']) is not int or manifest['version'] != index or manifest['previous_sha256'] != previous:
            raise ValueError('Invalid version chain')
        _name(manifest['experiment_id'])
        if experiment is not None and manifest['experiment_id'] != experiment:
            raise ValueError('Mixed experiments')
        experiment = manifest['experiment_id']
        if manifest['source'] not in ('synthetic', 'authorized'):
            raise ValueError('Invalid source')
        if not isinstance(manifest['recorded_at'], str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', manifest['recorded_at']):
            raise ValueError('Invalid local timestamp')
        datetime.strptime(manifest['recorded_at'], '%Y-%m-%dT%H:%M:%SZ')
        _configuration(manifest['configuration'])
        artifacts = manifest['artifacts']
        _keys(artifacts, GROUPS)
        count = 0
        for group in GROUPS:
            if not isinstance(artifacts[group], list) or (group != 'results' and not artifacts[group]):
                raise ValueError('Invalid artifact list')
            names = set()
            for entry in artifacts[group]:
                count += 1
                _keys(entry, ('name', 'status', 'sha256', 'size', 'reason'))
                _name(entry['name'])
                if entry['name'] in names:
                    raise ValueError('Duplicate artifact')
                names.add(entry['name'])
                if entry['status'] == 'AVAILABLE':
                    if not isinstance(entry['sha256'], str) or not DIGEST.fullmatch(entry['sha256']) or type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_FILE or entry['reason'] is not None:
                        raise ValueError('Invalid digest metadata')
                elif entry['status'] in ('MISSING', 'INVALID'):
                    reasons = ('NOT_FOUND',) if entry['status'] == 'MISSING' else ('UNSAFE_FILE', 'SECRET_EXCLUDED')
                    if entry['sha256'] is not None or entry['size'] is not None or entry['reason'] not in reasons:
                        raise ValueError('Invalid unavailable artifact')
                else:
                    raise ValueError('Invalid artifact status')
        if count > 16 or manifest['state'] != _state(artifacts):
            raise ValueError('Invalid aggregate state')
        digest = hashlib.sha256(canonical(manifest)).hexdigest()
        if record['sha256'] != digest:
            raise ValueError('Manifest digest mismatch')
        previous = digest
    return previous


def _history_at(fd):
    names = sorted(os.listdir(fd))
    # A crashed staging file is not silently erased or treated as a committed version.
    if len(names) > MAX_VERSIONS or names != [f'{n:06d}.json' for n in range(1, len(names) + 1)]:
        raise ValueError('Unexpected files or incomplete registry; operator recovery required')
    records = [strict_json(_read_at(fd, name, MAX_JSON)) for name in names]
    _validate_records(records)
    return records


def initialize(path):
    path = _path(path)
    with _directory(path.parent) as fd:
        os.mkdir(path.name, mode=0o700, dir_fd=fd)
        os.fsync(fd)
    return {'schema_version': 'experiment-registry.v1', 'initialized': True}


def history(path):
    with _directory(path) as fd:
        return _history_at(fd)


def _publish(fd, name, data):
    temporary = '.pending-' + uuid.uuid4().hex
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # link is atomic and never replaces an existing destination.
        os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=fd)
    os.fsync(fd)


def append(path, spec):
    validate_spec(spec)
    with _directory(path) as fd:
        records = _history_at(fd)
        if len(records) >= MAX_VERSIONS:
            raise ValueError('Registry version limit reached')
        if records and records[0]['manifest']['experiment_id'] != spec['experiment_id']:
            raise ValueError('Registry belongs to another experiment')
        artifacts = {group: [_artifact(entry) for entry in spec[group]] for group in GROUPS}
        manifest = {'schema_version': 'experiment-manifest.v1', 'experiment_id': spec['experiment_id'],
                    'version': len(records) + 1, 'previous_sha256': records[-1]['sha256'] if records else None,
                    'recorded_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'source': spec['source'], 'configuration': spec['configuration'],
                    'artifacts': artifacts, 'state': _state(artifacts)}
        record = {'manifest': manifest, 'sha256': hashlib.sha256(canonical(manifest)).hexdigest()}
        data = canonical(record)
        if len(data) > MAX_JSON:
            raise ValueError('Manifest size limit exceeded')
        _publish(fd, f'{len(records) + 1:06d}.json', data)
        return record


def export_registry(path):
    records = history(path)
    return {'schema_version': 'experiment-export.v1', 'records': records,
            'head_sha256': records[-1]['sha256'] if records else None}


def verify_export(export, *, expected_head=None):
    _bounded(export)
    if len(canonical(export)) > MAX_EXPORT:
        raise ValueError('Export size limit exceeded')
    _keys(export, ('schema_version', 'records', 'head_sha256'))
    if export['schema_version'] != 'experiment-export.v1' or _validate_records(export['records']) != export['head_sha256']:
        raise ValueError('Export chain mismatch')
    if expected_head is not None:
        if type(expected_head) is not str or not DIGEST.fullmatch(expected_head):
            raise ValueError('Invalid independently saved head')
        if export['head_sha256'] != expected_head:
            raise ValueError('Export does not match independently saved head')
    return {'integrity': 'VALID', 'versions': len(export['records']), 'head_sha256': export['head_sha256'],
            'anchor_checked': expected_head is not None,
            'files_checked': False, 'authenticity_verified': False}


def check_files(path, spec):
    validate_spec(spec)
    records = history(path)
    if not records:
        raise ValueError('No registered version')
    latest = records[-1]['manifest']
    if (latest['experiment_id'], latest['source']) != (spec['experiment_id'], spec['source']) or canonical(latest['configuration']) != canonical(spec['configuration']):
        raise ValueError('Specification does not match registered experiment')
    actual = {group: [_artifact(entry) for entry in spec[group]] for group in GROUPS}
    for group in GROUPS:
        if [a['name'] for a in actual[group]] != [a['name'] for a in latest['artifacts'][group]]:
            raise ValueError('Artifact names do not match registered version')
    state = _state(actual)
    if state == 'AVAILABLE':
        state = 'MATCH' if actual == latest['artifacts'] else 'CHANGED'
    return {'state': state, 'version': latest['version'], 'artifacts': actual, 'authenticity_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline manifests; integrity is not authenticity or authorization')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'append', 'show', 'export', 'check'):
        cmd = commands.add_parser(name)
        cmd.add_argument('registry')
        if name in ('append', 'check'):
            cmd.add_argument('--spec', required=True)
        if name == 'export':
            cmd.add_argument('--out', required=True)
    verify = commands.add_parser('verify')
    verify.add_argument('export_file')
    verify.add_argument('--expected-head', help='SHA256 guardado aparte; el head del propio export no es ancla independiente')
    args = parser.parse_args(argv)
    try:
        if args.command == 'init':
            result = initialize(args.registry)
        elif args.command in ('append', 'check'):
            spec = strict_json(read_file(args.spec))
            result = (append if args.command == 'append' else check_files)(args.registry, spec)
        elif args.command == 'show':
            result = export_registry(args.registry)
        elif args.command == 'verify':
            result = verify_export(strict_json(read_file(args.export_file, MAX_EXPORT), MAX_EXPORT),
                                   expected_head=args.expected_head)
        else:
            result = export_registry(args.registry)
            target = _path(args.out)
            with _directory(target.parent) as fd:
                _publish(fd, target.name, canonical(result))
            result = verify_export(result)
        print(canonical(result).decode())
        return 0
    except (ValueError, OSError, OverflowError, RecursionError) as exc:
        # Paths and file contents are never echoed in errors.
        print(json.dumps({'error': type(exc).__name__, 'operation_completed': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
