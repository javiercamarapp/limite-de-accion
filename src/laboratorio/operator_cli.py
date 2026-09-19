"""Offline operator CLI. Trusted local configuration; no human authentication.

Run with python -m laboratorio.operator_cli. The foreground service uses kernel
peer UIDs through UnixReceiver. Same-UID channels are NOT security separation.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import threading

from .authority import LocalAuthority, _identifier, _timestamp, intent_digest
from .controller import DurableController
from .evaluation import loads_strict
from .unix_transport import UnixReceiver, request

_LIMIT = 65536
_CONFIG = {'schema', 'deadline', 'max_operations', 'admin_uid', 'dispatcher_uid', 'principal'}
_LIMITS = {'synthetic_data': True, 'human_authenticated': False,
           'separate_os_identities': False, 'C1_T02_verified': False,
           'external_effects': False}


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _path(value):
    # Do not normalize '..' across symlinks, or resolve away a symlink.
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('No se permiten componentes ..')
    if not path.is_absolute():
        path = Path.cwd() / path
    for parent in reversed(path.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
                or info.st_uid not in (0, os.geteuid())):
            raise PermissionError('La ruta requiere padres existentes y confiables, sin symlinks')
    return path


def _regular(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise PermissionError('Se requiere archivo regular propio, sin enlaces ni escritura compartida')
    return info


def _read_json(value):
    path = _path(value)
    before = _regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        if (actual.st_dev, actual.st_ino) != (before.st_dev, before.st_ino):
            raise PermissionError('Archivo sustituido durante apertura')
        if actual.st_size > _LIMIT:
            raise ValueError('JSON supera 65536 bytes')
        payload = stream.read(_LIMIT + 1)
    if len(payload) > _LIMIT:
        raise ValueError('JSON supera 65536 bytes')
    return loads_strict(payload.decode('utf-8'))


def _write_new(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=True, allow_nan=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def _validate_config(config):
    if type(config) is not dict or set(config) != _CONFIG or config['schema'] != 'operator.v1':
        raise ValueError('Configuración operator.v1 inválida')
    _timestamp(config['deadline'])
    if type(config['max_operations']) is not int or not 1 <= config['max_operations'] <= 1000:
        raise ValueError('Presupuesto entre 1 y 1000')
    for name in ('admin_uid', 'dispatcher_uid'):
        if type(config[name]) is not int or config[name] < 0:
            raise ValueError('UID inválido')
    _identifier(config['principal'])
    return config


def _load(root):
    root = _path(root)
    info = root.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise PermissionError('El directorio de estado debe ser propio y privado (0700)')
    config = _validate_config(_read_json(root / 'config.json'))
    return root, config


def _database(root, name):
    path = _path(root / name)
    _regular(path)
    for suffix in ('-journal', '-wal', '-shm'):
        sidecar = Path(str(path) + suffix)
        if os.path.lexists(sidecar):
            _regular(sidecar)
    return path


@contextmanager
def _readonly(path):
    # mode=ro neither creates missing storage nor runs constructor recovery.
    # SQLite ro can still create WAL/SHM files. This CLI creates rollback-journal
    # databases only; reject an externally changed WAL mode before connecting.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise PermissionError('Se requiere SQLite regular')
        header = stream.read(20)
    if len(header) == 20 and 2 in header[18:20]:
        raise ValueError('WAL no admitido: la consulta no puede crear sidecars')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db
    finally:
        db.close()


def _check_metadata(db, config):
    row = db.execute('SELECT * FROM controller_state WHERE singleton=1').fetchone()
    if row is None or row['deadline'] != config['deadline'] or row['max_operations'] != config['max_operations']:
        raise PermissionError('Configuración durable inmutable o incompleta')
    return dict(row)


def _check_authority(path):
    # The library constructor can bootstrap a blank DB. Reopening a CLI session
    # must instead reject missing state before that constructor can write.
    with _readonly(path) as db:
        rows = db.execute('SELECT singleton, epoch FROM authority_state').fetchall()
        if (len(rows) != 1 or rows[0]['singleton'] != 1
                or type(rows[0]['epoch']) is not int or not 0 <= rows[0]['epoch'] < 2**53):
            raise ValueError('Estado de autoridad incompleto')
        db.execute('SELECT calendar_id, event_id, start_utc, end_utc, title, version FROM events LIMIT 0')
        db.execute('SELECT approval_id, intent_digest, intent_json, principal_id, '
                   'original_request_digest, approver_id, epoch, expires_at, consumed FROM approvals LIMIT 0')
        db.execute('SELECT operation_id, intent_digest, intent_json, approval_id, '
                   'principal_id, receipt_json FROM receipts LIMIT 0')


def query(root, operation_id=None):
    root, config = _load(root)
    if operation_id is not None:
        _identifier(operation_id)
    with _readonly(_database(root, 'controller.sqlite3')) as db:
        metadata = _check_metadata(db, config)
        metadata['clock_blocked'] = bool(metadata['clock_blocked'])
        if operation_id is None:
            rows = db.execute('SELECT * FROM operations ORDER BY operation_id').fetchall()
        else:
            rows = db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchall()
            if not rows:
                raise KeyError(operation_id)
        operations = []
        for row in rows:
            operation = dict(row)
            operation['receipt'] = loads_strict(operation.pop('receipt_json') or 'null')
            operations.append(operation)
        if operation_id is not None:
            return operations[0]
        intents = [{'intent': loads_strict(row['intent_json']), 'intent_digest': row['intent_digest']}
                   for row in db.execute('SELECT * FROM intents ORDER BY intent_id')]
        return {'metadata': metadata, 'intents': intents, 'operations': operations}


def _controller(root, config):
    path = _database(root, 'controller.sqlite3')
    with _readonly(path) as db:
        _check_metadata(db, config)
    return DurableController(path, deadline=config['deadline'], max_operations=config['max_operations'],
                             clock=_now, transport=lambda message: request(root / 'd.sock', message))


def prepare_fixture(root, config):
    config = _validate_config(config)
    if config['deadline'] <= _now():
        raise ValueError('Deadline debe ser futuro')
    # This iteration creates no users, chown, or cross-UID permission setup.
    if config['admin_uid'] != os.geteuid() or config['dispatcher_uid'] != os.geteuid():
        raise PermissionError('Esta CLI local sólo configura el UID efectivo; separación de UIDs pendiente')
    root = _path(root)
    root.mkdir(mode=0o700, exist_ok=False)
    # Partial failed initialization remains visible; never delete/reuse a run.
    for name in ('receiver.sqlite3', 'controller.sqlite3'):
        fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    authority = LocalAuthority(root / 'receiver.sqlite3', clock=_now)
    try:
        authority.create_event('fixture_calendar', 'fixture_event', '2099-01-02T08:00:00Z',
                               '2099-01-02T08:30:00Z', title='SYNTHETIC OPERATOR FIXTURE')
    finally:
        authority._db.close()  # Existing authority exposes no public close API.
    def unavailable_transport(message):
        raise RuntimeError('No transport during setup')

    with DurableController(root / 'controller.sqlite3', deadline=config['deadline'],
                           max_operations=config['max_operations'], clock=_now,
                           transport=unavailable_transport):
        pass
    intent = {'schema_version': 'C1.intent.v1', 'intent_id': 'fixture_intent', 'run_id': 'fixture_run',
              'principal_id': config['principal'], 'calendar_id': 'fixture_calendar',
              'event_id': 'fixture_event', 'operation': 'RESCHEDULE_EVENT', 'expected_version': 0,
              'start_utc': '2099-01-02T10:00:00Z', 'end_utc': '2099-01-02T10:30:00Z'}
    _write_new(root / 'intent.json', intent)
    _write_new(root / 'config.json', config)  # Written last: incomplete runs cannot open.
    return {'root': str(root), **_LIMITS}


def serve(root, *, stop=None, ready=None):
    """Foreground lifetime; owned threads are closed and joined on every exit.

    stop/ready allow an embedding operator/test to manage that same lifetime.
    No daemon, background process, host identity changes or auto-approvals.
    """
    root, config = _load(root)
    if config['admin_uid'] != os.geteuid() or config['dispatcher_uid'] != os.geteuid():
        raise PermissionError('No se cambia UID ni ownership del host')
    path = _database(root, 'receiver.sqlite3')
    # Reject occupied endpoints before opening the authority (including stale sockets).
    for name in ('a.sock', 'd.sock'):
        if os.path.lexists(root / name):
            raise FileExistsError('Endpoint ocupado; no se elimina automáticamente')
    _check_authority(path)
    authority = LocalAuthority(path, clock=_now)
    receivers, threads, errors = [], [], []
    stop = stop if stop is not None else threading.Event()
    def run(receiver):
        try:
            receiver.serve_forever()
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()
    try:
        for name, role, uid in [('a.sock', 'admin', config['admin_uid']),
                                ('d.sock', 'dispatcher', config['dispatcher_uid'])]:
            receiver = UnixReceiver(root / name, authority, allowed_uid=uid, role=role,
                                    principal_id=config['principal'] if role == 'dispatcher' else None)
            receivers.append(receiver)
        for receiver in receivers:
            thread = threading.Thread(target=run, args=(receiver,))
            threads.append(thread)
            thread.start()
        if ready is not None:
            ready.set()
        stop.wait()
    except KeyboardInterrupt:
        pass
    finally:
        # One failed cleanup must not skip the remaining owned resources.
        for receiver in receivers:
            try:
                receiver.close()
            except BaseException as exc:
                errors.append(exc)
                shutdown = getattr(receiver, 'shutdown', None)
                if shutdown is not None:
                    try:
                        shutdown()
                    except BaseException as shutdown_error:
                        errors.append(shutdown_error)
        for thread in threads:
            if thread.ident is not None:
                try:
                    thread.join(timeout=3)
                except BaseException as exc:
                    errors.append(exc)
        if any(thread.is_alive() for thread in threads):
            # Do not close a connection still being used by a live receiver.
            raise RuntimeError('Cierre no confirmado; quedan hilos propios activos')
        authority._db.close()
    # Workers can fail while close/join is running. Observe them only after join.
    if errors:
        raise RuntimeError('Falló el receptor o su cierre') from errors[0]
    return {'stopped': True, **_LIMITS}


def _remote(root, channel, method, params):
    response = request(root / channel, {'method': method, 'params': params})
    if response['ok'] is not True:
        raise PermissionError('Receptor rechazó petición: ' + response['error']['code'])
    return response['result']


def _parser():
    parser = argparse.ArgumentParser(description='Operador local sintético; mismo UID NO separa roles ni autentica humanos')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare-fixture', 'serve', 'register', 'approve', 'reserve', 'dispatch',
                 'query', 'reconcile', 'revoke', 'event', 'receipt'):
        command = sub.add_parser(name)
        command.add_argument('--root', required=True)
        if name == 'prepare-fixture':
            command.add_argument('--deadline', required=True)
            command.add_argument('--max-operations', type=int, required=True)
            command.add_argument('--admin-uid', type=int, required=True)
            command.add_argument('--dispatcher-uid', type=int, required=True)
            command.add_argument('--principal', required=True)
        if name in ('register', 'approve'):
            command.add_argument('--intent', required=True)
        if name == 'approve':
            command.add_argument('--original-digest', required=True,
                                 help='Digest recibido por canal confiable; nunca se fabrica desde la propuesta')
            command.add_argument('--expires-at', required=True)
        if name == 'reserve':
            command.add_argument('--intent-id', required=True)
            command.add_argument('--approval-id', required=True)
        if name in ('reserve', 'dispatch', 'query', 'reconcile', 'receipt'):
            command.add_argument('--operation-id', required=name != 'query')
        if name == 'event':
            command.add_argument('--calendar-id', required=True)
            command.add_argument('--event-id', required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == 'prepare-fixture':
            result = prepare_fixture(args.root, {'schema': 'operator.v1', 'deadline': args.deadline,
                'max_operations': args.max_operations, 'admin_uid': args.admin_uid,
                'dispatcher_uid': args.dispatcher_uid, 'principal': args.principal})
        elif args.command == 'serve':
            result = serve(args.root)
        elif args.command == 'query':
            result = query(args.root, args.operation_id)
        else:
            root, config = _load(args.root)
            intent = None
            if args.command in ('register', 'approve'):
                intent = _read_json(args.intent)
                intent_digest(intent)  # Validate before opening writable state.
                if intent['principal_id'] != config['principal']:
                    raise PermissionError('Principal distinto de configuración confiable')
            if args.command == 'approve':
                result = _remote(root, 'a.sock', 'approve', {'intent': intent,
                    'original_request_digest': args.original_digest, 'expires_at': args.expires_at})
            elif args.command == 'revoke':
                result = _remote(root, 'a.sock', 'revoke', {})
            elif args.command == 'event':
                result = _remote(root, 'd.sock', 'get_event', {'calendar_id': args.calendar_id, 'event_id': args.event_id})
            elif args.command == 'receipt':
                result = _remote(root, 'd.sock', 'get_receipt', {'operation_id': args.operation_id})
            else:
                with _controller(root, config) as controller:
                    if args.command == 'register':
                        result = controller.register(intent)
                    elif args.command == 'reserve':
                        result = controller.reserve(args.intent_id, args.approval_id, args.operation_id)
                    elif args.command == 'dispatch':
                        result = controller.dispatch(args.operation_id)
                    else:
                        result = controller.reconcile(args.operation_id)
        print(json.dumps({'ok': True, 'result': result, **_LIMITS}, ensure_ascii=True, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error, RecursionError):
        # Do not leak paths, payloads or storage internals. A lost reply is never success.
        print(json.dumps({'ok': False, 'error': 'INVALID_OR_UNAVAILABLE',
                          'effect_confirmed': False, 'retry_authorized': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
