"""Bounded LOCAL READONLY console. Persisted declarations never authorize actions."""
import argparse
import json
import os
import re
from types import MappingProxyType
from pathlib import Path
import sqlite3
import stat
import sys

from . import operator_cli, experiment_registry, forecast_ledger, evidence_import, authority
from .controller import DurableController

_STATES = ('RESERVED', 'DISPATCHING', 'UNKNOWN', 'CONFIRMED', 'REJECTED')
_STATUS = ('AVAILABLE', 'MISSING', 'INVALID', 'NOT_CONFIGURED', 'INCOMPLETE')
_FLAGS = ('enterprise_complete', 'C1_T02_verified', 'human_authenticated',
          'evidence_verified', 'prospective_validation', 'dispatch_authorized')
_MAX_DB = 8 * 1024 * 1024

# Current core DDL, deliberately fixed: unknown migrations fail closed.
_DDL = MappingProxyType({
    'controller_state': """CREATE TABLE controller_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        deadline TEXT NOT NULL, max_operations INTEGER NOT NULL,
        last_observed TEXT NOT NULL, clock_blocked INTEGER NOT NULL DEFAULT 0)""",
    'intents': """CREATE TABLE intents (
        intent_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
        intent_json TEXT NOT NULL)""",
    'operations': """CREATE TABLE operations (
        operation_id TEXT PRIMARY KEY,
        intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id),
        approval_id TEXT NOT NULL UNIQUE,
        calendar_id TEXT NOT NULL, event_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN
        ('RESERVED','DISPATCHING','UNKNOWN','CONFIRMED','REJECTED')),
        receipt_json TEXT)""",
    'active_event': """CREATE UNIQUE INDEX active_event
        ON operations(calendar_id, event_id)
        WHERE status IN ('RESERVED','DISPATCHING','UNKNOWN')""",
})
_COLUMNS = MappingProxyType({
    'controller_state': (('singleton', 'INTEGER', 0, None, 1),
        ('deadline', 'TEXT', 1, None, 0), ('max_operations', 'INTEGER', 1, None, 0),
        ('last_observed', 'TEXT', 1, None, 0), ('clock_blocked', 'INTEGER', 1, '0', 0)),
    'intents': (('intent_id', 'TEXT', 0, None, 1),
        ('intent_digest', 'TEXT', 1, None, 0), ('intent_json', 'TEXT', 1, None, 0)),
    'operations': (('operation_id', 'TEXT', 0, None, 1),
        ('intent_id', 'TEXT', 1, None, 0), ('approval_id', 'TEXT', 1, None, 0),
        ('calendar_id', 'TEXT', 1, None, 0), ('event_id', 'TEXT', 1, None, 0),
        ('status', 'TEXT', 1, None, 0), ('receipt_json', 'TEXT', 0, None, 0)),
})


def _ddl_tokens(sql):
    # Ignore whitespace outside literals only; preserve literal bytes and case.
    return tuple(re.findall(r"'(?:''|[^'])*'|[^\s]", sql))


def _schema(db):
    expected = {name: ('table' if name in _COLUMNS else 'index',
                      name if name in _COLUMNS else 'operations', _ddl_tokens(sql))
                for name, sql in _DDL.items()}
    for table, count in (('intents', 1), ('operations', 3)):
        for index in range(1, count + 1):
            expected[f'sqlite_autoindex_{table}_{index}'] = ('index', table, None)
    seen = set()
    for row in db.execute('SELECT type, name, tbl_name, sql FROM sqlite_schema LIMIT 9'):
        kind, name, table, sql = row
        actual = (kind, table, _ddl_tokens(sql) if type(sql) is str else sql)
        if name in seen or name not in expected or actual != expected[name]:
            raise ValueError('Unsupported schema')
        seen.add(name)
    if seen != expected.keys():
        raise ValueError('Incomplete schema')
    for table, columns in _COLUMNS.items():
        actual = tuple(tuple(row) for row in db.execute('PRAGMA table_xinfo(' + table + ')'))
        wanted = tuple((i, *column, 0) for i, column in enumerate(columns))
        if actual != wanted:
            raise ValueError('Unsupported columns')


def _rows(db, table, limit=1000):
    columns = ', '.join(column[0] for column in _COLUMNS[table])
    for index, row in enumerate(db.execute('SELECT ' + columns + ' FROM ' + table +
                                         ' NOT INDEXED LIMIT ' + str(limit + 1))):
        if index >= limit:
            raise ValueError('Too many records')
        if any(type(value) is bytes for value in row):
            raise ValueError('Invalid field type')
        yield dict(row)


def _path(value):
    raw = os.fspath(value)
    if (type(raw) is not str or not raw or len(raw) > 4096 or ':' in raw
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)
            or '..' in raw.split('/')):
        raise ValueError('Invalid path')
    path = Path(raw)
    return path if path.is_absolute() else Path.cwd() / path


def _regular(info, limit):
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_size > limit or info.st_uid != os.geteuid()
            or info.st_mode & 0o022):
        raise ValueError('Unsafe storage')


def _scan(path, count, per_file, total_limit, *, names=None):
    """Bound enumeration before legacy APIs that allocate their directory listing.

    Physical traversal and lstat precede reads; no recursive traversal occurs.
    Return identities to detect concurrent modifications, not an atomic snapshot.
    """
    result, total = {}, 0
    with experiment_registry._directory(path) as fd:
        directory = os.fstat(fd)
        if directory.st_uid != os.geteuid() or directory.st_mode & 0o022:
            raise ValueError('Unsafe directory')
        result['.'] = (directory.st_dev, directory.st_ino, directory.st_mtime_ns)
        with os.scandir(fd) as entries:
            for index, entry in enumerate(entries):
                if index >= count:
                    raise ValueError('Too many entries')
                if names is not None and entry.name not in names:
                    # The operator may have sockets and private intent files;
                    # they are not inputs to this read-only report.
                    continue
                info = entry.stat(follow_symlinks=False)
                limit = per_file(entry.name) if callable(per_file) else per_file
                _regular(info, limit)
                total += info.st_size
                if total > total_limit:
                    raise ValueError('Storage limit')
                result[entry.name] = (info.st_dev, info.st_ino, info.st_size,
                                      info.st_mtime_ns, info.st_ctime_ns)
        if names is not None and not names <= result.keys():
            raise FileNotFoundError('Required storage missing')
    return result


def _stamp(value):
    forecast_ledger._timestamp(value)
    return value


def _int(value, maximum=1000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Invalid integer')
    return value


def _operator(path):
    names = {'config.json', 'controller.sqlite3'}
    scan = lambda: _scan(path, 32, lambda n: 65536 if n.endswith('.json') else _MAX_DB,
                         _MAX_DB + 65536, names=names)
    before = scan()
    path, config = operator_cli._load(path)
    dbpath = path / 'controller.sqlite3'
    # Reject all sidecars: even a read-only SQLite connection must not recover
    # a hot journal or create shared memory for WAL mode.
    for suffix in ('-journal', '-wal', '-shm'):
        if os.path.lexists(str(dbpath) + suffix):
            raise ValueError('Sidecar not supported')
    header = experiment_registry.read_file(dbpath, _MAX_DB)[:100]
    if len(header) < 100 or header[:16] != b'SQLite format 3\x00' or header[18:20] != b'\x01\x01':
        raise ValueError('Unsupported database')
    with operator_cli._readonly(dbpath) as db:
        # Apply engine limits BEFORE schema/column reads or expression evaluation.
        for category, limit in ((sqlite3.SQLITE_LIMIT_LENGTH, 65536),
                (sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16384),
                (sqlite3.SQLITE_LIMIT_COLUMN, 32),
                (sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 32),
                (sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 1),
                (sqlite3.SQLITE_LIMIT_ATTACHED, 0)):
            db.setlimit(category, limit)
        db.execute('PRAGMA trusted_schema=OFF')
        db.set_progress_handler(lambda: 1, 200000)
        _schema(db)
        metadata_rows = list(_rows(db, 'controller_state', 1))
        if len(metadata_rows) != 1:
            raise ValueError('Invalid metadata')
        metadata = metadata_rows[0]
        if (type(metadata['singleton']) is not int or metadata['singleton'] != 1
                or type(metadata['clock_blocked']) is not int
                or metadata['clock_blocked'] not in (0, 1)):
            raise ValueError('Invalid metadata')
        _stamp(metadata['deadline'])
        _stamp(metadata['last_observed'])
        _int(metadata['max_operations'])
        if (metadata['deadline'] != config['deadline']
                or metadata['max_operations'] != config['max_operations']):
            raise ValueError('Immutable configuration mismatch')
        metadata['clock_blocked'] = bool(metadata['clock_blocked'])
        intents = {}
        for row in _rows(db, 'intents'):
            intent = authority._intent_snapshot(operator_cli.loads_strict(row['intent_json']))
            if (row['intent_id'] != intent['intent_id'] or row['intent_id'] in intents
                    or row['intent_digest'] != authority.intent_digest(intent)):
                raise ValueError('Invalid intent identity')
            intents[row['intent_id']] = intent
        counts = dict.fromkeys(_STATES, 0)
        ids, approvals, reserved_intents, active_events = set(), set(), set(), set()
        used = 0
        for operation in _rows(db, 'operations'):
            for key in ('operation_id', 'intent_id', 'approval_id', 'calendar_id', 'event_id'):
                authority._identifier(operation[key])
            for key, seen in (('operation_id', ids), ('approval_id', approvals),
                              ('intent_id', reserved_intents)):
                if operation[key] in seen:
                    raise ValueError('Duplicate identity')
                seen.add(operation[key])
            intent = intents[operation['intent_id']]
            if any(operation[k] != intent[k] for k in ('calendar_id', 'event_id')):
                raise ValueError('Inconsistent event')
            state = operation['status']
            if type(state) is not str or state not in _STATES:
                raise ValueError('Invalid state')
            if state in ('RESERVED', 'DISPATCHING', 'UNKNOWN'):
                event = (operation['calendar_id'], operation['event_id'])
                if event in active_events:
                    raise ValueError('Duplicate active event')
                active_events.add(event)
            raw = operation['receipt_json']
            if state == 'CONFIRMED':
                receipt = operator_cli.loads_strict(raw) if type(raw) is str else None
                if DurableController._receipt({'ok': True, 'result': receipt}, operation, intent) is None:
                    raise ValueError('Invalid receipt')
            elif raw is not None:
                raise ValueError('Receipt incompatible with persisted state')
            counts[state] += 1
            used += 1
        if used > config['max_operations']:
            raise ValueError('Budget exceeded')
    if scan() != before:
        raise ValueError('Inconsistent storage')
    return dict(budget_total=config['max_operations'], budget_used=used, counts=counts,
                deadline=_stamp(metadata['deadline']), clock_blocked=metadata['clock_blocked'],
                last_observed=_stamp(metadata['last_observed']), service_alive=None,
                states_are_persisted=True, dispatch_authorized=False)


def _experiments(path):
    scan = lambda: _scan(path, 256, 64000, 64000 * 256)
    before = scan()
    exported = experiment_registry.export_registry(path)
    checked = experiment_registry.verify_export(exported)
    records = exported['records']
    latest = records[-1]['manifest']['state'] if records else None
    if scan() != before:
        raise ValueError('Concurrent change')
    return dict(status='AVAILABLE' if latest == 'AVAILABLE' else 'INCOMPLETE',
                versions=checked['versions'], latest_state=latest,
                head_sha256=checked['head_sha256'], chain_integrity=checked['integrity'],
                files_checked=False, authenticity_verified=False, anchor_checked=False,
                history=[dict(version=r['manifest']['version'], state=r['manifest']['state'],
                              sha256=r['sha256']) for r in records])


def _forecasts(path):
    scan = lambda: _scan(path, 2001, 32768, 16 * 1024 * 1024)
    before = scan()
    result = forecast_ledger.Ledger(path).score()
    if scan() != before:
        raise ValueError('Concurrent change')
    return {key: result[key] for key in ('resolved', 'pending', 'overdue', 'brier',
            'baseline_brier', 'as_of', 'clock_regressed', 'evidence_verified', 'prospective_validation')}


def _evidence(path):
    scan = lambda: _scan(path, 17, lambda n: 65536 if n == 'manifest.json' else 1048576,
                         16777216 + 65536)
    before = scan()
    if 'manifest.json' not in before:
        raise FileNotFoundError('Missing manifest')
    result = evidence_import.verify_bundle(path)
    origins = dict.fromkeys(('public', 'synthetic', 'authorized'), 0)
    for source in result['manifest']['sources']:
        origins[source['source_kind']] += 1
    if scan() != before:
        raise ValueError('Concurrent change')
    return dict(source_count=sum(origins.values()), declared_origins=origins,
                integrity=result['integrity'], evidence_verified=False,
                authenticity_verified=False, original_sources_checked=False, urls_opened=False)


def collect_status(operator_root=None, experiments=None, forecasts=None, evidence=None):
    """Read independent optional stores. No actions, recovery, source imports or sockets.

    Missing configured storage is MISSING; unsafe/corrupt storage is INVALID.
    An intact experiment history with an incomplete latest record is INCOMPLETE.
    AVAILABLE describes readability only, never operational readiness.
    """
    components = {}
    for name, value, reader in (('operator', operator_root, _operator),
            ('experiments', experiments, _experiments), ('forecasts', forecasts, _forecasts),
            ('evidence', evidence, _evidence)):
        if value is None:
            components[name] = {'status': 'NOT_CONFIGURED'}
            continue
        try:
            components[name] = {'status': 'AVAILABLE', **reader(_path(value))}
        except FileNotFoundError:
            components[name] = {'status': 'MISSING'}
        except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError,
                RecursionError, sqlite3.Error):
            components[name] = {'status': 'INVALID'}
    states = [c['status'] for c in components.values()]
    overall = next((s for s in ('INVALID', 'MISSING', 'INCOMPLETE') if s in states), None)
    if overall is None:
        overall = 'NOT_CONFIGURED' if all(s == 'NOT_CONFIGURED' for s in states) else 'AVAILABLE'
    return dict(schema='operations-status.v1', mode='LOCAL_READONLY', status=overall,
                components=components, snapshot_atomic=False, timestamps_certified=False,
                hashes_are_integrity_only=True, **dict.fromkeys(_FLAGS, False))


def format_text(report):
    """Render only known labels, enums and typed numeric values; never free metadata."""
    def state(value):
        return value if type(value) is str and value in _STATUS else 'INVALID'
    def number(value):
        if value is None:
            return 'null'
        if type(value) in (int, float) and 0 <= value <= 1000000:
            return str(value)
        return 'INVALID'
    lines = ['LOCAL READONLY | ' + state(report.get('status')),
             'Instantanea NO atomica; timestamps locales NO certificados.',
             'Hashes: solo integridad. Ningun estado ni score autoriza despacho.']
    for name in ('operator', 'experiments', 'forecasts', 'evidence'):
        c = report.get('components', {}).get(name, {})
        lines.append(name + ': ' + state(c.get('status')))
        if name == 'operator' and c.get('status') == 'AVAILABLE':
            lines.append('  budget total=' + number(c.get('budget_total')) + ' usado=' + number(c.get('budget_used')))
            lines.append('  ' + ' '.join(s + '=' + number(c.get('counts', {}).get(s)) for s in _STATES))
            deadline = c.get('deadline')
            try: deadline = _stamp(deadline)
            except (ValueError, TypeError): deadline = 'INVALID'
            lines.append('  deadline=' + deadline + ' clock_blocked=' + ('true' if c.get('clock_blocked') is True else 'false'))
            lines.append('  Servicio vivo: no determinado desde archivos.')
        elif name == 'experiments' and 'versions' in c:
            lines.append('  versiones=' + number(c.get('versions')) + ' ultimo=' + state(c.get('latest_state')))
            head = c.get('head_sha256')
            safe_head = head if (type(head) is str and len(head) == 64
                                 and all(ch in '0123456789abcdef' for ch in head)) else 'null'
            integrity = 'VALID' if c.get('chain_integrity') == 'VALID' else 'INVALID'
            lines.append('  cadena=' + integrity + ' head_sha256=' + safe_head)
            lines.append('  Cadena: integridad de metadatos; originales no comprobados.')
        elif name == 'forecasts' and c.get('status') == 'AVAILABLE':
            lines.append('  ' + ' '.join(k + '=' + number(c.get(k)) for k in
                         ('resolved', 'pending', 'overdue', 'brier', 'baseline_brier')))
        elif name == 'evidence' and c.get('status') == 'AVAILABLE':
            lines.append('  fuentes=' + number(c.get('source_count')) + ' origenes declarados: ' +
                         ' '.join(k + '=' + number(c.get('declared_origins', {}).get(k)) for k in
                                  ('public', 'synthetic', 'authorized')))
    lines.extend(k + '=false' for k in _FLAGS)
    return '\n'.join(lines)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Argumentos invalidos.\n')


def main(argv=None):
    parser = _Parser(description='Consola LOCAL READONLY; no autoriza despacho.', allow_abbrev=False)
    for name in ('operator-root', 'experiments', 'forecasts', 'evidence'):
        parser.add_argument('--' + name)
    parser.add_argument('--format', choices=('json', 'text'), default='json')
    args = parser.parse_args(argv)
    report = collect_status(args.operator_root, args.experiments, args.forecasts, args.evidence)
    print(json.dumps(report, ensure_ascii=True, allow_nan=False) if args.format == 'json' else format_text(report))
    return 2 if report['status'] in ('INVALID', 'MISSING', 'INCOMPLETE') else 0


if __name__ == '__main__':
    raise SystemExit(main())
