"""Banco SQLite local; no habilita el bucle C1 ni efectos externos.

El reloj es configuración confiable. El principal de execute procede de un
canal externo confiable; create_event, approve y revoke_all son APIs admin.
Este módulo NO autentica el reloj, el principal ni el acceso administrativo.
Su integración real, la protección de la DB y el aislamiento siguen pendientes.
No es un motor de contención completo ni una validación de C1-T02.
"""

from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import re
import secrets
import sqlite3
import threading


_MAX_INTEGER = 2**53 - 1
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_TIMESTAMP = re.compile(
    r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
    r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z"
)
_IDS = ("intent_id", "run_id", "principal_id", "calendar_id", "event_id")
_FIELDS = frozenset((*_IDS, "schema_version", "operation", "expected_version",
                     "start_utc", "end_utc"))


def _identifier(value):
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Identificador ASCII inválido")


def _integer(value):
    if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
        raise ValueError("Entero fuera del contrato")


def _timestamp(value):
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("Se requiere fecha UTC con segundos y sufijo Z")
    datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    return value


def _interval(start, end):
    if _timestamp(end) <= _timestamp(start):
        raise ValueError("El final debe ser posterior al inicio")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _intent_snapshot(intent):
    if type(intent) is not dict:
        raise ValueError("Intent debe ser un objeto")
    intent = intent.copy()
    if any(type(key) is not str for key in intent) or intent.keys() != _FIELDS:
        raise ValueError("Intent requiere exactamente los diez campos C1")
    for key in _IDS:
        _identifier(intent[key])
    for key, expected in (("schema_version", "C1.intent.v1"),
                          ("operation", "RESCHEDULE_EVENT")):
        if type(intent[key]) is not str or intent[key] != expected:
            raise ValueError("Constante de Intent inválida")
    _integer(intent["expected_version"])
    _interval(intent["start_utc"], intent["end_utc"])
    return intent


def intent_digest(intent):
    """SHA-256 del JSON canónico; el prefijo no participa en el hash."""
    canonical = _canonical(_intent_snapshot(intent))
    return "C1.intent.v1:sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LocalAuthority:
    """Autoridad local con transacciones serializadas; llamadores confiables."""

    def __init__(self, path, clock):
        if not callable(clock):
            raise ValueError("clock debe ser una función de configuración confiable")
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA synchronous = FULL")
            with self._mutation():
                self._db.execute("""CREATE TABLE IF NOT EXISTS authority_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    epoch INTEGER NOT NULL)""")
                self._db.execute("INSERT OR IGNORE INTO authority_state VALUES (1, 0)")
                self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                    calendar_id TEXT NOT NULL, event_id TEXT NOT NULL,
                    start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
                    title TEXT NOT NULL, version INTEGER NOT NULL,
                    PRIMARY KEY (calendar_id, event_id))""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
                    intent_json TEXT NOT NULL, principal_id TEXT NOT NULL,
                    original_request_digest TEXT NOT NULL, approver_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL, expires_at TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0)""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                    operation_id TEXT PRIMARY KEY, intent_digest TEXT NOT NULL,
                    intent_json TEXT NOT NULL, approval_id TEXT NOT NULL UNIQUE,
                    principal_id TEXT NOT NULL, receipt_json TEXT NOT NULL)""")
        except BaseException:
            self._db.close()
            raise

    @contextmanager
    def _mutation(self):
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                try:
                    yield
                    self._db.commit()
                except BaseException:
                    self._db.rollback()
                    raise
            except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
                raise PermissionError("Conflicto de almacenamiento local") from exc

    def _epoch(self):
        return self._db.execute(
            "SELECT epoch FROM authority_state WHERE singleton = 1"
        ).fetchone()["epoch"]

    def _event(self, calendar_id, event_id):
        row = self._db.execute(
            "SELECT * FROM events WHERE calendar_id = ? AND event_id = ?",
            (calendar_id, event_id),
        ).fetchone()
        if row is None:
            raise PermissionError("Recurso inexistente")
        return dict(row)

    def _current_event(self, intent):
        event = self._event(intent["calendar_id"], intent["event_id"])
        if event["version"] != intent["expected_version"]:
            raise PermissionError("Versión del recurso en conflicto")
        if event["version"] == _MAX_INTEGER:
            raise PermissionError("No se puede incrementar la versión")
        return event

    def create_event(self, calendar_id, event_id, start_utc, end_utc, *,
                     title="", version=0):
        """API administrativa confiable; nunca reemplaza un recurso existente."""
        _identifier(calendar_id)
        _identifier(event_id)
        _interval(start_utc, end_utc)
        _integer(version)
        if type(title) is not str:
            raise ValueError("title debe ser texto")
        with self._mutation():
            self._db.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (calendar_id, event_id, start_utc, end_utc, title, version),
            )

    def get_event(self, calendar_id, event_id):
        _identifier(calendar_id)
        _identifier(event_id)
        with self._lock:
            return self._event(calendar_id, event_id)

    def approve(self, intent, *, original_request_digest, approver_id, expires_at):
        """API admin; original_request_digest debe llegar por un canal protegido."""
        intent = _intent_snapshot(intent)
        digest = intent_digest(intent)
        _identifier(approver_id)
        _timestamp(expires_at)
        if (type(original_request_digest) is not str or
                re.fullmatch(r"C1\.intent\.v1:sha256:[0-9a-f]{64}",
                             original_request_digest) is None):
            raise ValueError("Digest original fuera del contrato")
        if original_request_digest != digest:
            raise PermissionError("La solicitud original no coincide")
        with self._mutation():
            self._current_event(intent)
            if expires_at <= _timestamp(self._clock()):
                raise PermissionError("Aprobación caducada")
            approval_id = "approval_" + secrets.token_hex(24)
            self._db.execute(
                """INSERT INTO approvals
                (approval_id, intent_digest, intent_json, principal_id,
                 original_request_digest, approver_id, epoch, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (approval_id, digest, _canonical(intent), intent["principal_id"],
                 original_request_digest, approver_id, self._epoch(), expires_at),
            )
        return approval_id

    def execute(self, intent, *, approval_id, operation_id, authenticated_principal):
        """Aplica sólo horas/version; la identidad ya debe estar autenticada fuera."""
        intent = _intent_snapshot(intent)
        digest, canonical = intent_digest(intent), _canonical(intent)
        for identifier in (approval_id, operation_id, authenticated_principal):
            _identifier(identifier)
        if authenticated_principal != intent["principal_id"]:
            raise PermissionError("Principal distinto del autorizado")
        with self._mutation():
            previous = self._db.execute(
                "SELECT * FROM receipts WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if previous is not None:
                if (previous["intent_digest"] != digest or
                        previous["intent_json"] != canonical or
                        previous["approval_id"] != approval_id or
                        previous["principal_id"] != authenticated_principal):
                    raise PermissionError("Colisión de operation_id")
                return json.loads(previous["receipt_json"])
            approval = self._db.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if (approval is None or approval["consumed"] or
                    approval["intent_digest"] != digest or
                    approval["intent_json"] != canonical or
                    approval["original_request_digest"] != digest or
                    approval["principal_id"] != authenticated_principal or
                    approval["epoch"] != self._epoch()):
                raise PermissionError("Aprobación inexistente, consumida o no vigente")
            now = _timestamp(self._clock())
            if approval["expires_at"] <= now:
                raise PermissionError("Aprobación caducada")
            event = self._current_event(intent)
            self._db.execute(
                """UPDATE events SET start_utc = ?, end_utc = ?, version = version + 1
                WHERE calendar_id = ? AND event_id = ?""",
                (intent["start_utc"], intent["end_utc"],
                 intent["calendar_id"], intent["event_id"]),
            )
            self._db.execute(
                "UPDATE approvals SET consumed = 1 WHERE approval_id = ?", (approval_id,)
            )
            receipt = {
                "operation_id": operation_id, "intent_digest": digest,
                "approval_id": approval_id, "principal_id": authenticated_principal,
                "authority_epoch": approval["epoch"], "applied_at": now,
                "calendar_id": intent["calendar_id"], "event_id": intent["event_id"],
                "start_utc": intent["start_utc"], "end_utc": intent["end_utc"],
                "version": event["version"] + 1,
            }
            self._db.execute(
                "INSERT INTO receipts VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, digest, canonical, approval_id,
                 authenticated_principal, _canonical(receipt)),
            )
        return receipt

    def revoke_all(self):
        """API admin: invalida aprobaciones anteriores, sin revertir efectos."""
        with self._mutation():
            epoch = self._epoch()
            if epoch == _MAX_INTEGER:
                raise PermissionError("Epoch agotado")
            self._db.execute(
                "UPDATE authority_state SET epoch = ? WHERE singleton = 1", (epoch + 1,)
            )
        return epoch + 1
