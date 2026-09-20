"""Ledger local append-only de declaraciones; no verifica evidencia ni procedencia."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from functools import wraps
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys

from .forecasts import score_binary_forecasts

MAX_INPUT_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_FORECASTS = 1000
_ERROR = 'Operación rechazada: datos, reloj, límites o almacenamiento inválidos.'
_STAMP = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')


def _timestamp(value):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise ValueError(_ERROR)
    datetime.fromisoformat(value)
    return value


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(_ERROR)
        out[key] = value
    return out


def _constant(value):
    raise ValueError(_ERROR)


def _decode(raw):
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                            parse_constant=_constant)
        pending = [result]
        while pending:
            value = pending.pop()
            if type(value) is str:
                value.encode('utf-8')  # reject escaped, unpaired surrogates too
            elif type(value) is list:
                pending.extend(value)
            elif type(value) is dict:
                pending.extend(value.keys())
                pending.extend(value.values())
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(_ERROR) from exc


def _parts(path):
    raw = os.fspath(path)
    if type(raw) is not str or not raw or ':' in raw or '\x00' in raw:
        raise ValueError(_ERROR)
    parts = Path(raw).parts
    if '..' in parts or not parts or parts == ('/',):
        raise ValueError(_ERROR)
    return parts


@contextmanager
def _parent(path):
    """Traverse physical directories with openat; never follow symlinks."""
    parts = _parts(path)
    fd = os.open('/' if parts[0] == '/' else '.', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[1:-1] if parts[0] == '/' else parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _read(fd, name, limit):
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        info = os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError(_ERROR)
        chunks = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(source, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        if len(raw) > limit or len(raw) != info.st_size:
            raise ValueError(_ERROR)
        return raw
    finally:
        os.close(source)


def _input(path):
    with _parent(path) as (fd, name):
        return _decode(_read(fd, name, MAX_INPUT_BYTES))


def _safe(method):
    """Public errors never expose filenames or supplied content."""
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            raise ValueError(_ERROR) from None
    return wrapped


class Ledger:
    """Explicit local directory; clock injection is only available to Python callers.

    init/add/resolve mutate; show/score open existing files read-only. All public
    failures raise ValueError. Inputs are filenames, not in-memory records or URLs.
    """

    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self._clock = _now if clock is None else clock

    @contextmanager
    def _open(self, exclusive=False):
        with _parent(self.path) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, mode | fcntl.LOCK_NB)
            yield fd
        finally:
            os.close(fd)

    def _commit(self, fd, index, event):
        raw = json.dumps(event, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > MAX_INPUT_BYTES:
            raise ValueError(_ERROR)
        name = f'{index:08d}.json'
        temporary = '.pending-' + secrets.token_hex(12)
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o600, dir_fd=fd)
        try:
            with os.fdopen(out, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Atomic publication, with no replacement even if another file exists.
            os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=fd)
        os.fsync(fd)
        return event['registered_at']

    def _load(self, fd):
        names = []
        with os.scandir(fd) as entries:
            for entry in entries:
                names.append(entry.name)
                if len(names) > 2 * MAX_FORECASTS + 1:
                    raise ValueError(_ERROR)
        names.sort()
        if not names or names != [f'{i:08d}.json' for i in range(len(names))]:
            raise ValueError(_ERROR)
        forecasts, resolutions, records = [], [], []
        identifiers, resolved = set(), set()
        previous, total = None, 0
        for index, name in enumerate(names):
            raw = _read(fd, name, min(MAX_INPUT_BYTES, MAX_TOTAL_BYTES - total))
            total += len(raw)
            event = _decode(raw)
            if type(event) is not dict or event.keys() != {'kind', 'registered_at', 'payload'}:
                raise ValueError(_ERROR)
            registered = _timestamp(event['registered_at'])
            if previous is not None and registered < previous:
                raise ValueError(_ERROR)
            kind, payload = event['kind'], event['payload']
            if index == 0:
                if kind != 'init' or type(payload) is not dict or payload != {'version': 1} or type(payload['version']) is not int:
                    raise ValueError(_ERROR)
            elif kind == 'add':
                score_binary_forecasts([payload], [], registered)
                if payload['id'] in identifiers or len(forecasts) >= MAX_FORECASTS:
                    raise ValueError(_ERROR)
                forecasts.append(payload)
                identifiers.add(payload['id'])
                records.append(event)
            elif kind == 'resolve':
                if type(payload) is not dict or payload.get('id') not in identifiers or payload.get('id') in resolved:
                    raise ValueError(_ERROR)
                matching = next(f for f in forecasts if f['id'] == payload['id'])
                score_binary_forecasts([matching], [payload], registered)
                resolutions.append(payload)
                resolved.add(payload['id'])
                records.append(event)
            else:
                raise ValueError(_ERROR)
            previous = registered
        return forecasts, resolutions, records, previous, total, len(names)

    @_safe
    def init(self):
        now = _timestamp(self._clock())
        with _parent(self.path) as (parent, name):
            os.mkdir(name, 0o700, dir_fd=parent)
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._commit(fd, 0, {'kind': 'init', 'registered_at': now, 'payload': {'version': 1}})
                os.fsync(parent)
            finally:
                os.close(fd)
        return {'initialized': True, 'registered_at': now,
                'evidence_verified': False, 'prospective_validation': False}

    def _mutate(self, kind, source):
        payload = _input(source)
        with self._open(exclusive=True) as fd:
            forecasts, resolutions, _, last, total, index = self._load(fd)
            now = _timestamp(self._clock())
            if now < last:
                raise ValueError(_ERROR)
            if kind == 'add':
                if len(forecasts) >= MAX_FORECASTS:
                    raise ValueError(_ERROR)
                forecasts.append(payload)
            else:
                resolutions.append(payload)
            score_binary_forecasts(forecasts, resolutions, now)
            event = {'kind': kind, 'registered_at': now, 'payload': payload}
            size = len(json.dumps(event, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode())
            if total + size > MAX_TOTAL_BYTES:
                raise ValueError(_ERROR)
            self._commit(fd, index, event)
        return {'recorded': True, 'registered_at': now,
                'evidence_verified': False, 'prospective_validation': False}

    @_safe
    def add(self, source):
        return self._mutate('add', source)

    @_safe
    def resolve(self, source):
        return self._mutate('resolve', source)

    def _query(self):
        with self._open() as fd:
            forecasts, resolutions, records, last, _, _ = self._load(fd)
        now = _timestamp(self._clock())
        return forecasts, resolutions, records, max(now, last), now < last

    @_safe
    def show(self):
        forecasts, resolutions, records, now, regressed = self._query()
        adds = {e['payload']['id']: e['registered_at'] for e in records if e['kind'] == 'add'}
        resolves = {e['payload']['id']: e['registered_at'] for e in records if e['kind'] == 'resolve'}
        return {'forecasts': [dict(forecast=f, registered_at=adds[f['id']],
                    status='resolved' if f['id'] in resolves else
                    'overdue' if f['resolve_at'] <= now else 'pending') for f in forecasts],
                'resolutions': [dict(resolution=r, registered_at=resolves[r['id']]) for r in resolutions],
                'as_of': now, 'clock_regressed': regressed,
                'evidence_verified': False, 'prospective_validation': False}

    @_safe
    def score(self):
        forecasts, resolutions, _, now, regressed = self._query()
        result = score_binary_forecasts(forecasts, resolutions, now)
        resolved = {r['id'] for r in resolutions}
        return dict(result, overdue=sum(f['id'] not in resolved and f['resolve_at'] <= now for f in forecasts),
                    as_of=now, clock_regressed=regressed, prospective_validation=False)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, _ERROR + '\n')


def main(argv=None):
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'add', 'resolve', 'show', 'score'):
        command = commands.add_parser(name)
        command.add_argument('ledger')
        if name in ('add', 'resolve'):
            command.add_argument('source')
    args = parser.parse_args(argv)
    try:
        instance = Ledger(args.ledger)
        method = getattr(instance, args.command)
        result = method(args.source) if hasattr(args, 'source') else method()
        print(json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (ValueError, OSError):
        print(_ERROR, file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
