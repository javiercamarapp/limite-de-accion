"""Preparación durable C1; no prueba C1-T02, humano real ni aislamiento.

La configuración (ruta, transporte, reloj) debe venir de una fuente confiable.
El reloj no tiene garantía del OS. Sólo el receptor valida la aprobación externa.
Cada apertura convierte DISPATCHING en UNKNOWN, incluso si otra instancia sigue
viva: no hay detección de procesos muertos. Eso puede adelantar una lectura de
reconciliación mientras el envío sigue en vuelo; ausencia nunca libera el evento
ni permite reenviar. Una respuesta exacta posterior aún puede confirmar.
No se mantiene una transacción SQLite durante llamadas al transporte.
"""
from contextlib import contextmanager
import json
import sqlite3
import threading

from .authority import (_canonical, _identifier, _integer, _intent_snapshot,
                        _timestamp, intent_digest)


class DurableController:
    """Registro previo y un solo intento de envío por operación, sin retries.

    ValueError indica entrada inválida; PermissionError, conflicto o límite.
    Los errores de almacenamiento se propagan: no representan éxito del efecto.
    Use close() o el administrador de contexto para liberar la conexión.
    """

    def __init__(self, path, *, transport, deadline, max_operations, clock):
        _timestamp(deadline)
        if type(max_operations) is not int or not 1 <= max_operations <= 1000:
            raise ValueError('max_operations debe ser entero entre 1 y 1000')
        if not callable(transport) or not callable(clock):
            raise ValueError('transport y clock deben ser funciones confiables')
        self._transport, self._clock, self._path = transport, clock, path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute('PRAGMA synchronous = FULL')
            self._db.execute('PRAGMA foreign_keys = ON')
            with self._transaction():
                self._db.execute('''CREATE TABLE IF NOT EXISTS controller_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    deadline TEXT NOT NULL, max_operations INTEGER NOT NULL,
                    last_observed TEXT NOT NULL, clock_blocked INTEGER NOT NULL DEFAULT 0)''')
                self._db.execute('''CREATE TABLE IF NOT EXISTS intents (
                    intent_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
                    intent_json TEXT NOT NULL)''')
                self._db.execute('''CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    intent_id TEXT NOT NULL UNIQUE REFERENCES intents(intent_id),
                    approval_id TEXT NOT NULL UNIQUE,
                    calendar_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN
                    ('RESERVED','DISPATCHING','UNKNOWN','CONFIRMED','REJECTED')),
                    receipt_json TEXT)''')
                self._db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS active_event
                    ON operations(calendar_id, event_id)
                    WHERE status IN ('RESERVED','DISPATCHING','UNKNOWN')''')
                state = self._metadata()
                if state is None:
                    self._db.execute('INSERT INTO controller_state VALUES (1, ?, ?, ?, 0)',
                                     (deadline, max_operations, _timestamp(clock())))
                elif state['deadline'] != deadline or state['max_operations'] != max_operations:
                    raise PermissionError('Configuración durable inmutable')
                else:
                    self._observe_clock()  # Persistir bloqueo, permitir consultas al abrir.
                self._db.execute("UPDATE operations SET status = 'UNKNOWN' WHERE status = 'DISPATCHING'")
        except BaseException:
            self._db.close()
            raise

    def close(self):
        with self._lock:
            self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _metadata(self):
        row = self._db.execute('SELECT * FROM controller_state WHERE singleton = 1').fetchone()
        return dict(row) if row else None

    def _observe_clock(self):
        state = self._metadata()
        try:
            now = _timestamp(self._clock())
        except Exception:
            self._db.execute('UPDATE controller_state SET clock_blocked = 1')
            return 'Reloj inválido'
        if now < state['last_observed']:
            self._db.execute('UPDATE controller_state SET clock_blocked = 1')
            return 'El reloj retrocedió'
        self._db.execute('UPDATE controller_state SET last_observed = ?', (now,))
        if state['clock_blocked']:
            return 'Reloj bloqueado durablemente'
        if now >= state['deadline']:
            return 'Deadline vencido'
        return None

    @contextmanager
    def _transaction(self, *, timed=False):
        with self._lock:
            self._db.execute('BEGIN IMMEDIATE')
            try:
                if timed:
                    error = self._observe_clock()
                    if error:
                        self._db.commit()
                        raise PermissionError(error)
                # Un rechazo posterior no debe olvidar el último reloj observado.
                self._db.execute('SAVEPOINT work')
                try:
                    yield
                except BaseException:
                    self._db.execute('ROLLBACK TO work')
                    self._db.execute('RELEASE work')
                    self._db.commit()
                    raise
                self._db.execute('RELEASE work')
                self._db.commit()
            except BaseException:
                self._db.rollback()
                raise

    def register(self, intent):
        intent = _intent_snapshot(intent)
        canonical, digest = _canonical(intent), intent_digest(intent)
        with self._transaction(timed=True):
            previous = self._db.execute('SELECT intent_json FROM intents WHERE intent_id = ?',
                                        (intent['intent_id'],)).fetchone()
            if previous:
                if previous['intent_json'] != canonical:
                    raise PermissionError('intent_id inmutable')
                return intent['intent_id']
            count = self._db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]
            if count >= self._metadata()['max_operations'] * 4:
                raise PermissionError('Límite de propuestas agotado')
            self._db.execute('INSERT INTO intents VALUES (?, ?, ?)',
                             (intent['intent_id'], digest, canonical))
        return intent['intent_id']

    def _operation(self, operation_id):
        row = self._db.execute('SELECT * FROM operations WHERE operation_id = ?',
                               (operation_id,)).fetchone()
        if row is None:
            raise KeyError(operation_id)
        result = dict(row)
        result['receipt'] = json.loads(result.pop('receipt_json') or 'null')
        return result

    def _intent(self, intent_id):
        row = self._db.execute('SELECT intent_json FROM intents WHERE intent_id = ?',
                               (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return json.loads(row['intent_json'])

    def reserve(self, intent_id, approval_id, operation_id):
        for value in (intent_id, approval_id, operation_id):
            _identifier(value)
        # Recuperar una reserva idéntica es una lectura, incluso tras caducar.
        with self._lock:
            existing = self._existing_reservation(intent_id, approval_id, operation_id)
            if existing is not None:
                return existing
        with self._transaction(timed=True):
            existing = self._existing_reservation(intent_id, approval_id, operation_id)
            if existing is not None:
                return existing
            intent = self._intent(intent_id)
            count = self._db.execute('SELECT COUNT(*) FROM operations').fetchone()[0]
            if count >= self._metadata()['max_operations']:
                raise PermissionError('Presupuesto acumulativo agotado')
            try:
                self._db.execute('INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?, NULL)',
                                 (operation_id, intent_id, approval_id, intent['calendar_id'],
                                  intent['event_id'], 'RESERVED'))
            except sqlite3.IntegrityError as exc:
                raise PermissionError('Aprobación, intención o evento ya reservado') from exc
            return self._operation(operation_id)

    def _existing_reservation(self, intent_id, approval_id, operation_id):
        try:
            existing = self._operation(operation_id)
        except KeyError:
            return None
        if existing['intent_id'] != intent_id or existing['approval_id'] != approval_id:
            raise PermissionError('operation_id inmutable')
        return existing

    @staticmethod
    def _receipt(response, operation, intent):
        if (type(response) is not dict or set(response) != {'ok', 'result'}
                or response['ok'] is not True or type(response['result']) is not dict):
            return None
        receipt = response['result'].copy()
        expected = {'operation_id': operation['operation_id'],
                    'approval_id': operation['approval_id'], 'intent_digest': intent_digest(intent),
                    'principal_id': intent['principal_id'], 'calendar_id': intent['calendar_id'],
                    'event_id': intent['event_id'], 'start_utc': intent['start_utc'],
                    'end_utc': intent['end_utc'], 'version': intent['expected_version'] + 1}
        if set(receipt) != set(expected) | {'authority_epoch', 'applied_at'}:
            return None
        if any(type(receipt[k]) is not type(v) or receipt[k] != v for k, v in expected.items()):
            return None
        try:
            _integer(receipt['version'])
            _integer(receipt['authority_epoch'])
            _timestamp(receipt['applied_at'])
        except ValueError:
            return None
        return receipt

    @staticmethod
    def _rejected(response):
        return (type(response) is dict and set(response) == {'ok', 'error'}
                and response['ok'] is False and type(response['error']) is dict
                and set(response['error']) == {'code'}
                and type(response['error']['code']) is str
                and response['error']['code'] in ('DENIED', 'INVALID_REQUEST'))

    def _finish(self, operation_id, status, receipt=None):
        with self._transaction():
            current = self._operation(operation_id)
            # Una reconciliación concurrente ya confirmada jamás pierde evidencia.
            if current['status'] in ('DISPATCHING', 'UNKNOWN'):
                self._db.execute('UPDATE operations SET status = ?, receipt_json = ? WHERE operation_id = ?',
                                 (status, _canonical(receipt) if receipt is not None else None, operation_id))
            return self._operation(operation_id)

    def dispatch(self, operation_id):
        _identifier(operation_id)
        with self._lock:
            operation = self._operation(operation_id)
            if operation['status'] != 'RESERVED':
                return operation
            with self._transaction(timed=True):
                operation = self._operation(operation_id)
                if operation['status'] != 'RESERVED':
                    return operation
                intent = self._intent(operation['intent_id'])
                self._db.execute("UPDATE operations SET status = 'DISPATCHING' WHERE operation_id = ?",
                                 (operation_id,))
        # Fuera de la transacción: DISPATCHING ya está durable antes del callback.
        try:
            response = self._transport({'method': 'execute', 'params': {
                'intent': intent.copy(), 'approval_id': operation['approval_id'],
                'operation_id': operation_id}})
            receipt = self._receipt(response, operation, intent)
            status = 'CONFIRMED' if receipt else ('REJECTED' if self._rejected(response) else 'UNKNOWN')
        except BaseException as exc:
            self._finish(operation_id, 'UNKNOWN')
            if not isinstance(exc, Exception):
                raise
            return self.get_operation(operation_id)
        # Fallos de persistencia aquí propagan; DISPATCHING permite recuperación.
        return self._finish(operation_id, status, receipt)

    def reconcile(self, operation_id):
        _identifier(operation_id)
        with self._lock:
            operation = self._operation(operation_id)
            if operation['status'] != 'UNKNOWN':
                return operation
            intent = self._intent(operation['intent_id'])
        try:
            response = self._transport({'method': 'get_receipt', 'params': {'operation_id': operation_id}})
            receipt = self._receipt(response, operation, intent)
        except Exception:
            receipt = None
        if receipt is not None:
            return self._finish(operation_id, 'CONFIRMED', receipt)
        return self.get_operation(operation_id)

    def get_operation(self, operation_id):
        _identifier(operation_id)
        with self._lock:
            return self._operation(operation_id)

    def export_state(self):
        """Snapshot JSON consistente; no consulta reloj ni escribe almacenamiento."""
        with self._lock:
            self._db.execute('BEGIN')
            try:
                state = self._metadata()
                state['clock_blocked'] = bool(state['clock_blocked'])
                ids = self._db.execute('SELECT operation_id FROM operations ORDER BY operation_id').fetchall()
                intents = self._db.execute('SELECT * FROM intents ORDER BY intent_id').fetchall()
                return {'metadata': state,
                        'intents': [{'intent': json.loads(r['intent_json']), 'intent_digest': r['intent_digest']}
                                    for r in intents],
                        'operations': [self._operation(r['operation_id']) for r in ids]}
            finally:
                self._db.rollback()
