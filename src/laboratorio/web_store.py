"""Private, bounded local application storage. Same-UID processes remain trusted."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from . import evaluation, experiment_registry as registry, evidence_import
from .forecast_ledger import Ledger
from .forecasts import score_binary_forecasts
from .operations_status import collect_status
from .control_demo import run_demo

LIMITS = {'max_body_bytes': 2_000_000, 'max_content_bytes': 1_048_576, 'max_jobs': 100,
          'max_state_read_bytes': 32 * 1024 * 1024, 'max_state_json_bytes': 4 * 1024 * 1024,
          'page_size': 20}
GATES = dict.fromkeys(('enterprise_complete', 'C1_T02_verified', 'human_authenticated',
                       'evidence_verified', 'prospective_validation'), False)
ID = re.compile(r'[a-f0-9]{32}\Z')
KINDS = ('evaluations', 'evidence', 'demos')
# 201 ledger files * (32KiB payload + 4KiB preflight margin) fit in 8MiB.
# Admission reserves future resolution space in the smaller JSON view budget.
LEDGER_READ_BYTES = 8 * 1024 * 1024
LEDGER_JSON_BYTES = 1024 * 1024
RESOLUTION_RESERVE_BYTES = 8192
RESOLUTION_URL_BYTES = 2048


class AppError(Exception):
    def __init__(self, status=400, code='INVALID_INPUT', message='Datos inválidos.'):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def checked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        try:
            self._anchor()
            return method(self, *args, **kwargs)
        except AppError:
            raise
        except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
            raise AppError() from None
        except (OSError, RuntimeError):
            raise AppError(500, 'STORAGE_ERROR', 'Operación no confirmada.') from None
    return call


def fields(data, names):
    if type(data) is not dict or set(data) != set(names):
        raise AppError()
    evaluation._finite(data)
    raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
    if len(raw) > LIMITS['max_body_bytes']:
        raise AppError(413, 'LIMIT', 'Límite excedido.')
    if evidence_import._has_secret(raw):
        raise AppError()


def private(info, directory=False):
    if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != os.geteuid() or info.st_mode & 0o077
            or (not directory and info.st_nlink != 1)):
        raise AppError(500, 'UNSAFE_STORAGE', 'Almacenamiento inválido.')


def names(path, maximum, directories=False):
    with registry._directory(path) as fd:
        private(os.fstat(fd), True)
        found = []
        with os.scandir(fd) as entries:
            for entry in entries:
                if len(found) >= maximum:
                    raise AppError(413, 'LIMIT', 'Límite excedido.')
                private(entry.stat(follow_symlinks=False), directories)
                found.append(entry.name)
        return sorted(found)


def write(path, data):
    with registry._directory(path.parent) as fd:
        private(os.fstat(fd), True)
        registry._publish(fd, path.name, data)


def write_json(path, value):
    write(path, json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())


def same_json(left, right):
    return evaluation._canonical(left) == evaluation._canonical(right)


def readable_text(value, maximum=4096):
    if type(value) is not str:
        raise AppError()
    # Validate a copy; preserve the original rule, including CR/LF and tabs.
    evidence_import._text(value.translate(str.maketrans({'\n': ' ', '\r': ' ', '\t': ' '})), maximum)


def stamp(path):
    info = path.lstat()
    private(info, stat.S_ISDIR(info.st_mode))
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


def snapshot_stamp(path, depth=0):
    before = stamp(path)
    if not stat.S_ISDIR(before[5]):
        return before
    if depth > 2:
        raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento inválido.')
    with registry._directory(path) as fd:
        with os.scandir(fd) as entries:
            children = {}
            for entry in entries:
                if len(children) >= 201:
                    raise AppError(413, 'LIMIT', 'Límite excedido.')
                children[entry.name] = snapshot_stamp(path / entry.name, depth + 1)
    if before != stamp(path):
        raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento cambiado.')
    return before, children


def read_bytes(path):
    before = stamp(path)
    raw = registry.read_file(path, 2_000_000)
    if before != stamp(path):
        raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento cambiado.')
    return raw


def read_json(path):
    try:
        private(path.lstat())
        return evaluation.loads_strict(read_bytes(path).decode('utf-8'))
    except (ValueError, OSError, UnicodeError):
        raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento incompleto o dañado.') from None


def preflight(path, *, depth=0, maximum=16, per_file=2_000_000):
    """Bounded physical metadata scan; no payload reads or symlink traversal.

    Four copies cover snapshot + artifact verification + registry re-reads,
    with a per-file margin. Only two directory levels are ever accepted.
    """
    total = 0
    with registry._directory(path) as fd:
        private(os.fstat(fd), True)
        with os.scandir(fd) as entries:
            for index, entry in enumerate(entries):
                if index >= maximum:
                    raise AppError(413, 'LIMIT', 'Demasiados archivos.')
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    private(info, True)
                    if depth >= 2:
                        raise AppError(413, 'LIMIT', 'Demasiados niveles.')
                    total += preflight(path / entry.name, depth=depth + 1,
                                       maximum=maximum, per_file=per_file)
                else:
                    source = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    try:
                        info = os.fstat(source)
                        private(info)
                        if info.st_size > per_file:
                            raise AppError(413, 'LIMIT', 'Archivo demasiado grande.')
                        total += info.st_size + 4096
                    finally:
                        os.close(source)
    return total


def json_size(value):
    # Count one bounded component once, never reserialize the accumulated page.
    return sum(len(part.encode('utf-8')) for part in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(value))


class Store:
    def __init__(self, workspace, operator_root=None):
        self.root = Path(os.path.abspath(workspace))
        self.operator_root = operator_root
        self._fd = self._lock = None
        try:
            # Create missing CLI parent directories through physical openat traversal.
            parent_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
            try:
                for component in self.root.parent.parts[1:]:
                    try:
                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    except FileNotFoundError:
                        os.mkdir(component, 0o700, dir_fd=parent_fd)
                        child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                    os.close(parent_fd)
                    parent_fd = child
            finally:
                os.close(parent_fd)
            with registry._directory(self.root.parent) as parent:
                try:
                    os.mkdir(self.root.name, 0o700, dir_fd=parent)
                    fresh = True
                except FileExistsError:
                    fresh = False
                self._fd = os.open(self.root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            private(os.fstat(self._fd), True)
            self._lock = os.open('.lock', os.O_RDWR | (os.O_CREAT if fresh else 0) | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=self._fd)
            private(os.fstat(self._lock))
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AppError(409, 'WORKSPACE_BUSY', 'Workspace en uso.') from None
            self._anchor()
            if fresh:
                for kind in KINDS:
                    os.mkdir(kind, 0o700, dir_fd=self._fd)
                Ledger(self.root / 'forecasts').init()
                write_json(self.root / 'workspace.json', {'version': 1})
                os.fsync(self._fd)
            if not same_json(read_json(self.root / 'workspace.json'), {'version': 1}):
                raise AppError(500, 'CORRUPT_STORAGE', 'Workspace inválido.')
            self.ledger = Ledger(self.root / 'forecasts')
        except BaseException:
            self.close()
            raise

    def close(self):
        for attr in ('_lock', '_fd'):
            fd = getattr(self, attr, None)
            if fd is not None:
                os.close(fd)
                setattr(self, attr, None)

    def __enter__(self): return self
    def __exit__(self, *args): self.close()

    def _anchor(self):
        if self._fd is None:
            raise AppError(500, 'CLOSED', 'Almacén cerrado.')
        with registry._directory(self.root) as fd:
            current, held = os.fstat(fd), os.fstat(self._fd)
            private(current, True)
            lock = os.stat('.lock', dir_fd=fd, follow_symlinks=False)
            private(lock)
            if ((current.st_dev, current.st_ino) != (held.st_dev, held.st_ino)
                    or (lock.st_dev, lock.st_ino) != (os.fstat(self._lock).st_dev, os.fstat(self._lock).st_ino)):
                raise AppError(500, 'UNSAFE_STORAGE', 'Almacenamiento cambiado.')

    def _jobs(self, kind):
        result = names(self.root / kind, 100, True)
        if any(ID.fullmatch(n) is None for n in result):
            raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento inválido.')
        return result

    def _slot(self, kind):
        if len(self._jobs(kind)) >= 100:
            raise AppError(413, 'LIMIT', 'Máximo de trabajos alcanzado.')

    def _new(self, kind):
        self._slot(kind)
        identifier = uuid.uuid4().hex
        path = self.root / kind / identifier
        with registry._directory(path.parent) as fd:
            os.mkdir(identifier, 0o700, dir_fd=fd)
            os.fsync(fd)
        return identifier, path

    def _job(self, kind, identifier):
        if type(identifier) is not str or ID.fullmatch(identifier) is None:
            raise AppError()
        if identifier not in self._jobs(kind):
            raise AppError(404, 'NOT_FOUND', 'Recurso desconocido.')
        return self.root / kind / identifier

    def _spec(self, identifier, path):
        return {'experiment_id': identifier, 'source': 'authorized', 'configuration': {'evaluator': 'local-v1'},
                'inputs': [{'name': n, 'path': str(path / (n + '.json'))} for n in ('cases', 'responses')],
                'results': [{'name': 'result', 'path': str(path / 'result.json')}],
                'code': [{'name': 'evaluator', 'path': str(path / 'evaluator.py')}]}

    @checked
    def catalog(self, data):
        fields(data, ('seed', 'per_family'))
        cases = evaluation.make_cases(**data)
        public = evaluation.public_cases(cases)
        return {'cases': [dict(p, **{k: c[k] for k in c if k not in p}) for p, c in zip(public, cases)]}

    @checked
    def evaluate(self, data):
        if type(data) is dict and set(data) == {'name', 'cases_json', 'responses_json'}:
            fields(data, ('name', 'cases_json', 'responses_json'))
            data = {'name': data['name'], 'cases': evaluation.loads_strict(data['cases_json']),
                    'responses': evaluation.loads_strict(data['responses_json'])}
        fields(data, ('name', 'cases', 'responses'))
        evidence_import._text(data['name'], 120)
        if type(data['cases']) is not list or len(data['cases']) > 500:
            raise AppError()
        for case in data['cases']:
            if type(case) is not dict: raise AppError()
            for key, maximum in (('id', 128), ('domain', 128), ('prompt', 4096)):
                value = case.get(key)
                if type(value) is not str or len(value) > maximum: raise AppError()
        result = evaluation.evaluate(data['cases'], data['responses'])
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > 1_990_000:
            raise AppError(413, 'LIMIT', 'Resultado demasiado grande.')
        identifier, path = self._new('evaluations')
        for name, value in [('cases', data['cases']), ('responses', data['responses']), ('result', result)]:
            write_json(path / (name + '.json'), value)
        write(path / 'evaluator.py', registry.read_file(Path(evaluation.__file__).absolute(), 2_000_000))
        registry.initialize(path / 'registry')
        manifest = registry.append(path / 'registry', self._spec(identifier, path))
        if manifest['manifest']['state'] != 'AVAILABLE':
            raise AppError(500, 'INCOMPLETE', 'Registro experimental incompleto.')
        item = {'id': identifier, 'name': data['name'], 'created_at': now(), 'result': result}
        write_json(path / 'item.json', item)
        return item

    @checked
    def verify_experiment(self, data):
        fields(data, ('id',))
        path = self._job('evaluations', data['id'])
        if names(path / 'registry', 1) != ['000001.json']:
            raise AppError(500, 'CORRUPT_STORAGE', 'Registro incompleto.')
        return {'files': registry.check_files(path / 'registry', self._spec(data['id'], path)),
                'export': registry.verify_export(registry.export_registry(path / 'registry'))}

    def _ledger_state(self):
        if preflight(self.root / 'forecasts', depth=2, maximum=201, per_file=32768) > LEDGER_READ_BYTES:
            raise AppError(413, 'LIMIT', 'Ledger demasiado grande.')
        before = snapshot_stamp(self.root / 'forecasts')
        names(self.root / 'forecasts', 201)
        shown = self.ledger.show()
        if len(shown['forecasts']) > 100 or len(shown['resolutions']) > 100:
            raise AppError(413, 'LIMIT', 'Límite excedido.')
        for row in shown['forecasts']:
            for key in ('question', 'resolution_rule'):
                readable_text(row['forecast'][key])
        for row in shown['resolutions']:
            evidence_import._url(row['resolution']['evidence_url'])
        forecasts = [r['forecast'] for r in shown['forecasts']]
        resolutions = [r['resolution'] for r in shown['resolutions']]
        score = score_binary_forecasts(forecasts, resolutions, shown['as_of'])
        resolved = {r['id'] for r in resolutions}
        score.update(overdue=sum(f['id'] not in resolved and f['resolve_at'] <= shown['as_of'] for f in forecasts),
                     as_of=shown['as_of'], clock_regressed=shown['clock_regressed'], prospective_validation=False)
        if before != snapshot_stamp(self.root / 'forecasts'):
            raise AppError(500, 'CORRUPT_STORAGE', 'Ledger cambiado durante la lectura.')
        return {'forecasts': shown['forecasts'], 'resolutions': shown['resolutions'], 'score': score}

    def _admit_ledger(self, state, *, forecast=None, resolution=None):
        """Check the projected view BEFORE writing; reserve room to resolve new items.

        Legacy ledgers may have no reserved space. Resolutions can still reduce
        their pending set provided the resulting actual view remains readable.
        """
        forecasts = list(state['forecasts'])
        resolutions = list(state['resolutions'])
        timestamp = now()
        if forecast is not None:
            forecasts.append({'forecast': forecast, 'registered_at': timestamp, 'status': 'overdue'})
        if resolution is not None:
            resolutions.append({'resolution': resolution, 'registered_at': timestamp})
        score = score_binary_forecasts([f['forecast'] for f in forecasts],
                                       [r['resolution'] for r in resolutions], timestamp)
        projected = {'forecasts': forecasts, 'resolutions': resolutions, 'score': score}
        # Margin covers score diagnostics, commas and changes of status spelling.
        size = json_size(projected) + 4096
        if forecast is not None:
            size += (len(forecasts) - len(resolutions)) * RESOLUTION_RESERVE_BYTES
        if size > LEDGER_JSON_BYTES:
            raise AppError(413, 'LEDGER_CAPACITY',
                           'Cupo del ledger alcanzado; no se guardaron cambios. Resuelve pendientes o usa otro workspace.')

    @contextmanager
    def _input(self, value):
        name = self.root / ('.input-' + uuid.uuid4().hex)
        write_json(name, value)
        info = name.lstat()
        try:
            yield name
        finally:
            current = name.lstat()
            if (current.st_dev, current.st_ino, current.st_nlink) == (info.st_dev, info.st_ino, 1):
                name.unlink()

    @checked
    def forecast(self, data):
        fields(data, ('forecast',))
        if type(data['forecast']) is not dict: raise AppError()
        for key in ('question', 'resolution_rule'):
            readable_text(data['forecast'].get(key))
        state = self._ledger_state()
        forecasts = [r['forecast'] for r in state['forecasts']]
        if len(forecasts) >= 100:
            raise AppError(413, 'LIMIT', 'Máximo de pronósticos alcanzado.')
        if type(data['forecast']) is dict and any(f['id'] == data['forecast'].get('id') for f in forecasts):
            raise AppError(409, 'CONFLICT', 'Pronóstico ya registrado.')
        score_binary_forecasts(forecasts + [data['forecast']], [r['resolution'] for r in state['resolutions']], now())
        self._admit_ledger(state, forecast=data['forecast'])
        with self._input(data['forecast']) as path:
            return self.ledger.add(path)

    @checked
    def resolve(self, data):
        fields(data, ('resolution',))
        state = self._ledger_state()
        r = data['resolution']
        if type(r) is not dict: raise AppError()
        if not any(f['forecast']['id'] == r.get('id') for f in state['forecasts']):
            raise AppError(404, 'NOT_FOUND', 'Pronóstico desconocido.')
        if any(x['resolution']['id'] == r.get('id') for x in state['resolutions']):
            raise AppError(409, 'CONFLICT', 'Resolución ya registrada.')
        evidence_import._url(r.get('evidence_url'))
        if len(r['evidence_url'].encode('utf-8')) > RESOLUTION_URL_BYTES:
            raise AppError(413, 'LIMIT', 'La URL de resolución supera 2048 bytes UTF-8.')
        score_binary_forecasts([f['forecast'] for f in state['forecasts']],
                               [x['resolution'] for x in state['resolutions']] + [r], now())
        self._admit_ledger(state, resolution=r)
        with self._input(r) as path:
            return self.ledger.resolve(path)

    @checked
    def evidence(self, data):
        fields(data, ('title', 'url', 'source_kind', 'captured_at', 'content'))
        meta = {k: data[k] for k in ('title', 'url', 'source_kind', 'captured_at')}
        evidence_import._metadata(dict(meta, id='document'))
        if type(data['content']) is not str: raise AppError()
        raw = data['content'].encode('utf-8')
        if len(raw) > LIMITS['max_content_bytes']:
            raise AppError(413, 'LIMIT', 'Documento demasiado grande.')
        evidence_import._content(raw)
        identifier, path = self._new('evidence')
        write(path / 'content.txt', raw)
        write_json(path / 'spec.json', {'sources': [dict(meta, id=identifier, path=str(path / 'content.txt'))]})
        report = evidence_import.import_bundle(path / 'spec.json', path / 'bundle')
        item = dict(meta, id=identifier, imported_at=report['manifest']['imported_at'],
                    sha256=report['sha256'], integrity=report['integrity'], source_count=1)
        write_json(path / 'item.json', item)
        return item

    @checked
    def verify_evidence(self, data):
        fields(data, ('id',))
        return evidence_import.verify_bundle(self._job('evidence', data['id']) / 'bundle')

    @checked
    def demo(self, data):
        fields(data, ())
        self._slot('demos')
        # Reserve a private parent; core itself requires a nonexistent output.
        if len(os.fsencode(self.root.parent)) + len('/d12345678/r/d.sock') >= 104:
            raise AppError(400, 'DEMO_PATH_TOO_LONG', 'La demo necesita un workspace con ruta más corta.')
        identifier, path = self._new('demos')
        temporary = Path(tempfile.mkdtemp(prefix='d', dir=self.root.parent))
        stamp = temporary.lstat()
        output = temporary / 'r'
        try:
            result = run_demo(output)
            if result['status'] != 'PASS' or not same_json(result['final_event']['version'], 1):
                raise AppError(500, 'DEMO_FAILED', 'Demo no confirmada.')
            item = {'id': identifier, 'created_at': now(), 'result': result}
            write_json(path / 'item.json', item)
            return item
        finally:
            # Only our unchanged directories and the core's exact regular files.
            # Unexpected artifacts are retained; never recursively remove anything.
            try:
                if temporary.lstat().st_ino == stamp.st_ino:
                    with registry._directory(output) as fd:
                        allowed = {'receiver.sqlite3', 'controller.sqlite3', 'controller-export.json', 'report.json'}
                        found = names(output, 4)
                        if set(found) <= allowed:
                            for name in found: os.unlink(name, dir_fd=fd)
                            output.rmdir()
                    temporary.rmdir()
            except (OSError, ValueError, AppError):
                pass

    def _item(self, kind, identifier):
        return self._snapshot(kind, identifier)[0]

    def _snapshot(self, kind, identifier):
        path = self._job(kind, identifier)
        before = snapshot_stamp(path)
        snapshot = {}
        item = read_json(path / 'item.json')
        expected = {'id', 'name', 'created_at', 'result'} if kind == 'evaluations' else (
            {'id', 'created_at', 'result'} if kind == 'demos' else
            {'id', 'title', 'url', 'source_kind', 'captured_at', 'imported_at', 'sha256', 'integrity', 'source_count'})
        if type(item) is not dict or set(item) != expected or item['id'] != identifier:
            raise AppError(500, 'CORRUPT_STORAGE', 'Registro inválido.')
        if kind in ('evaluations', 'demos'):
            evidence_import._timestamp(item['created_at'])
        if kind == 'evaluations':
            evidence_import._text(item['name'], 120)
            raw = {name: read_bytes(path / (name + '.json')) for name in ('cases', 'responses', 'result')}
            snapshot.update({name: evaluation.loads_strict(value.decode('utf-8')) for name, value in raw.items()})
            result = evaluation.evaluate(snapshot['cases'], snapshot['responses'])
            if not same_json(result, item['result']) or not same_json(result, snapshot['result']):
                raise AppError(500, 'CORRUPT_STORAGE', 'Resultado alterado.')
            report = self.verify_experiment({'id': identifier})
            if report['files']['state'] != 'MATCH':
                raise AppError(500, 'CORRUPT_STORAGE', 'Artefactos alterados.')
            exported = registry.export_registry(path / 'registry')
            if not same_json(registry.verify_export(exported), report['export']):
                raise AppError(500, 'CORRUPT_STORAGE', 'Registro cambiado.')
            raw['evaluator'] = read_bytes(path / 'evaluator.py')
            artifacts = exported['records'][0]['manifest']['artifacts']
            expected = {group: [{'name': name, 'status': 'AVAILABLE',
                         'sha256': hashlib.sha256(raw[name]).hexdigest(), 'size': len(raw[name]), 'reason': None}
                         for name in members] for group, members in
                         (('inputs', ('cases', 'responses')), ('results', ('result',)), ('code', ('evaluator',)))}
            if not same_json(artifacts, expected) or not same_json(report['files']['artifacts'], expected):
                raise AppError(500, 'CORRUPT_STORAGE', 'Hashes de entradas incompatibles.')
            snapshot.update(experiment=exported, report=report)
        elif kind == 'evidence':
            report = self.verify_evidence({'id': identifier})
            snapshot['evidence'] = report
            source = report['manifest']['sources'][0]
            if (item['sha256'] != report['sha256'] or item['integrity'] != 'MATCH'
                    or any(item[k] != source[k] for k in ('id', 'title', 'url', 'source_kind', 'captured_at'))
                    or item['imported_at'] != report['manifest']['imported_at'] or not same_json(item['source_count'], 1)):
                raise AppError(500, 'CORRUPT_STORAGE', 'Evidencia alterada.')
        elif kind == 'demos':
            result = item['result']
            expected = {'status', 'operation_before_recovery', 'operation_after_recovery',
                        'recovery_transport_calls', 'all_controller_transport_calls',
                        'revoked_operation', 'final_event', 'synthetic_data', 'synthetic_clock',
                        'injected_response_loss', 'separate_os_identities', 'human_approval_performed',
                        'C1_T02_verified', 'external_effects'}
            if (type(result) is not dict or set(result) != expected
                    or result['status'] != 'PASS'
                    or result['operation_before_recovery'] != 'UNKNOWN'
                    or result['operation_after_recovery'] != 'CONFIRMED'
                    or result['revoked_operation'] != 'REJECTED'
                    or result['recovery_transport_calls'] != ['execute', 'get_receipt']
                    or result['all_controller_transport_calls'] != ['execute', 'get_receipt', 'execute']
                    or any(result[k] is not False for k in ('separate_os_identities',
                        'human_approval_performed', 'C1_T02_verified', 'external_effects'))
                    or any(result[k] is not True for k in ('synthetic_data', 'synthetic_clock', 'injected_response_loss'))
                    or not same_json(result['final_event'], {'calendar_id': 'demo_calendar', 'event_id': 'demo_event',
                        'start_utc': '2026-09-20T10:00:00Z', 'end_utc': '2026-09-20T10:30:00Z',
                        'title': 'SYNTHETIC EVENT', 'version': 1})):
                raise AppError(500, 'CORRUPT_STORAGE', 'Demo almacenada inválida.')
        if before != snapshot_stamp(path):
            raise AppError(500, 'CORRUPT_STORAGE', 'Almacenamiento cambiado durante la lectura.')
        return item, snapshot

    @checked
    def export(self, kind, identifier):
        mapping = {'evaluation': 'evaluations', 'experiment': 'evaluations', 'evidence': 'evidence', 'demo': 'demos'}
        if kind not in mapping: raise AppError()
        item, snapshot = self._snapshot(mapping[kind], identifier)
        if kind in ('experiment', 'evidence'): return snapshot[kind]
        if kind == 'evaluation':
            return dict(item, cases=snapshot['cases'], responses=snapshot['responses'])
        return item

    @checked
    def state(self, offset=0):
        if type(offset) is not int or not 0 <= offset <= 300:
            raise AppError()
        state = {'evaluations': [], 'experiments': [], 'evidence': [], 'demos': [],
                 'warnings': [], 'gates': dict(GATES), 'limits': dict(LIMITS), 'totals': {}}
        jobs = []
        for kind in KINDS:
            try:
                identifiers = self._jobs(kind)
                listed = [(stamp(self.root / kind / identifier)[3], identifier, kind)
                          for identifier in identifiers]
                state['totals'][kind] = len(listed)
                jobs.extend(listed)
            except (AppError, OSError, ValueError):
                state['totals'][kind] = None
                state['warnings'].append({'code': 'INVALID_STORAGE', 'component': kind})
        # Counts describe stored directories, including partial/unvalidated jobs.
        state['totals']['experiments'] = state['totals']['evaluations']
        jobs.sort(key=lambda row: (-row[0], row[1], row[2]))
        cursor, returned = offset, 0
        read_left = LIMITS['max_state_read_bytes'] - 8 * 1024 * 1024
        json_left = LIMITS['max_state_json_bytes'] - 1536 * 1024
        while cursor < len(jobs) and returned < LIMITS['page_size']:
            _, identifier, kind = jobs[cursor]
            try:
                path = self.root / kind / identifier
                estimated = 4 * preflight(path)
                # item.json is serialized once in the response. Reserve before reading.
                with registry._directory(path) as fd:
                    source = os.open('item.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                    try:
                        info = os.fstat(source)
                        private(info)
                        output = info.st_size + 4096
                    finally:
                        os.close(source)
                if estimated > read_left or output > json_left:
                    if cursor > offset and estimated <= LIMITS['max_state_read_bytes'] - 8 * 1024 * 1024 and output <= LIMITS['max_state_json_bytes'] - 1536 * 1024:
                        state['warnings'].append({'code': 'PAGE_BUDGET', 'component': kind, 'id': identifier})
                        break
                    raise AppError(413, 'LIMIT', 'Trabajo demasiado grande.')
                read_left -= estimated
                json_left -= output
                item, snapshot = self._snapshot(kind, identifier)
                experiment = None
                if kind == 'evaluations':
                    report = snapshot['report']
                    experiment = {k: item[k] for k in ('id', 'name', 'created_at')} | {
                        'state': 'AVAILABLE', 'head_sha256': report['export']['head_sha256'],
                        'versions': report['export']['versions']}
                # Detect growth/encoding surprises without serializing earlier items again.
                actual = json_size(item) + (json_size(experiment) if experiment else 0) + 2
                if actual > output:
                    raise AppError(413, 'LIMIT', 'Trabajo cambiado o demasiado grande.')
                state[kind].append(item)
                if experiment is not None: state['experiments'].append(experiment)
                returned += 1
            except (AppError, OSError, ValueError, KeyError, TypeError) as error:
                code = 'JOB_TOO_LARGE' if isinstance(error, AppError) and error.status == 413 else 'INVALID_JOB'
                state['warnings'].append({'code': code, 'component': kind, 'id': identifier})
            cursor += 1
        state['pagination'] = {'offset': offset, 'next_offset': cursor if cursor < len(jobs) else None,
                               'total_jobs': len(jobs), 'returned_jobs': returned}
        try:
            ledger = self._ledger_state()
            if json_size(ledger) > LEDGER_JSON_BYTES:
                raise AppError(413, 'LIMIT', 'Ledger demasiado grande.')
            state['forecasts'] = ledger
        except (AppError, OSError, ValueError) as error:
            state['forecasts'] = {'forecasts': [], 'resolutions': [], 'score': None}
            state['warnings'].append({'code': 'LEDGER_LIMIT' if isinstance(error, AppError) and error.status == 413
                                      else 'INVALID_STORAGE', 'component': 'forecasts'})
        try:
            if self.operator_root is not None:
                # Existing operator reader has its own file/SQL guards; reserve a
                # smaller metadata budget here for the aggregated state endpoint.
                from .operations_status import _scan
                _scan(self.operator_root, 32, 256 * 1024, 512 * 1024,
                      names={'config.json', 'controller.sqlite3'})
            operator = collect_status(operator_root=self.operator_root)['components']['operator']
            if json_size(operator) > 256 * 1024: raise ValueError()
            state['operator'] = operator
        except (AppError, OSError, ValueError):
            state['operator'] = {'status': 'INVALID'}
        if state['operator']['status'] in ('INVALID', 'MISSING'):
            state['warnings'].append({'code': 'INVALID_STORAGE', 'component': 'operator'})
        with os.scandir(self._fd) as entries:
            for index, entry in enumerate(entries):
                if index >= 108 or entry.name not in {'.lock', 'workspace.json', 'forecasts', *KINDS}:
                    state['warnings'].append({'code': 'INCOMPLETE_STORAGE', 'component': 'workspace'})
                    break
        return state
