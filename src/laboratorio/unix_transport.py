"""Receptor Unix local para una LocalAuthority ya inicializada fuera del servicio.

Cada canal tiene rol y UID fijados por configuración protegida. Si el operador
asigna el mismo UID a ambos canales, ese proceso puede abrir ambos: la integración
canónica debe usar UIDs diferentes y proteger por separado el acceso a la DB.
El identificador human_uid_N describe identidad de proceso, no autentica a una
persona. Socket/0600 no prueban aislamiento de kernel ni cumplimiento de C1-T02.

Encuadre: exactamente una línea JSON UTF-8, incluido LF, máximo 65536 bytes.
El cliente debe terminar su escritura (SHUT_WR); el receptor espera EOF antes
de actuar para rechazar segundas peticiones incluso fragmentadas. Una respuesta
JSONL y cierre. El timeout es un plazo total de lectura, no renovable por bytes.
request hace un único sendall, sin reintentos: perder la respuesta puede significar
que la operación ya ocurrió. La reconciliación queda a cargo del llamador.
Los padres deben existir, ser de root/UID efectivo y no permitir escritura a
grupo/otros; no se admiten symlinks ni siquiera en los padres (usar rutas reales).
"""
import ctypes
import math
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import threading
import time

from .authority import LocalAuthority, _identifier
from .evaluation import _canonical, loads_strict

_MAX_BYTES = 65536
_PARAMS = {
    "approve": {"intent", "original_request_digest", "expires_at"},
    "revoke": set(),
    "get_event": {"calendar_id", "event_id"},
    "execute": {"intent", "approval_id", "operation_id"},
    "get_receipt": {"operation_id"},
}
_ROLES = {"admin": {"approve", "revoke", "get_event"},
          "dispatcher": {"execute", "get_event", "get_receipt"}}
_IDENTITY_FIELDS = {"uid", "gid", "pid", "role", "principal", "principal_id",
                    "approver", "approver_id", "authenticated_principal"}


def peer_identity(sock) -> dict:
    """Credenciales del par provistas por el OS; cualquier fallo deniega acceso."""
    try:
        if sock.family != socket.AF_UNIX:
            raise OSError("Se requiere socket Unix")
        if sys.platform.startswith("linux"):
            size = struct.calcsize("3i")
            pid, uid, gid = struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size))
            if min(pid, uid, gid) < 0:
                raise OSError("Credenciales inválidas")
            return {"uid": uid, "gid": gid, "pid": pid}
        if sys.platform == "darwin":
            if hasattr(sock, "getpeereid"):
                uid, gid = sock.getpeereid()
            else:
                libc = ctypes.CDLL(None, use_errno=True)
                getpeereid = libc.getpeereid
                getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
                getpeereid.restype = ctypes.c_int
                uid_out, gid_out = ctypes.c_uint(), ctypes.c_uint()
                if getpeereid(sock.fileno(), ctypes.byref(uid_out), ctypes.byref(gid_out)) != 0:
                    raise OSError(ctypes.get_errno(), "getpeereid falló")
                uid, gid = uid_out.value, gid_out.value
            if min(uid, gid) < 0:
                raise OSError("Credenciales inválidas")
            return {"uid": uid, "gid": gid}
        raise OSError("Plataforma sin credenciales de par compatibles")
    except Exception as exc:
        raise PermissionError("No se pudo autenticar el proceso par") from exc


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError("timeout debe ser finito y positivo")
    return float(value)


def _encode(value):
    try:
        payload = (_canonical(value) + "\n").encode("utf-8")
    except (RecursionError, UnicodeError) as exc:
        raise ValueError("JSON inválido") from exc
    if len(payload) > _MAX_BYTES:
        raise ValueError("Mensaje demasiado grande")
    return payload


def _read(sock, deadline):
    payload = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Tiempo de lectura agotado")
        sock.settimeout(remaining)
        chunk = sock.recv(min(4096, _MAX_BYTES + 1 - len(payload)))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > _MAX_BYTES:
            raise ValueError("Mensaje demasiado grande")
    if not payload.endswith(b"\n") or payload.count(b"\n") != 1:
        raise ValueError("Se requiere exactamente una línea JSON y EOF")
    try:
        return loads_strict(payload[:-1].decode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("UTF-8 inválido") from exc


def _error(code):
    return {"ok": False, "error": {"code": code}}


class UnixReceiver:
    """Servidor secuencial; bootstrap y acceso directo a la DB son externos."""

    def __init__(self, socket_path, authority: LocalAuthority, *, allowed_uid: int,
                 role: str, principal_id: str | None = None, timeout: float = 2.0):
        if type(allowed_uid) is not int or allowed_uid < 0:
            raise ValueError("UID inválido")
        if type(role) is not str or role not in _ROLES:
            raise ValueError("Rol inválido")
        if role == "dispatcher" or principal_id is not None:
            _identifier(principal_id)
        self._timeout = _timeout(timeout)
        if allowed_uid != os.geteuid() and os.geteuid() != 0:
            raise PermissionError("Sólo root puede asignar un socket a otro UID")
        self._path = Path(os.path.abspath(os.fspath(socket_path)))
        # lstat, sin resolve(): no ocultar symlinks en componentes de la ruta.
        for parent in reversed(self._path.parents):
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
                    or info.st_uid not in (0, os.geteuid())):
                raise PermissionError("Padre del socket no confiable")
        if os.path.lexists(self._path):
            raise FileExistsError("El endpoint ya existe")
        self._authority = authority
        self._allowed_uid = allowed_uid
        self._role = role
        self._principal_id = principal_id
        self._stop = threading.Event()
        self._stopped = threading.Event()
        self._stopped.set()
        self._lock = threading.RLock()
        self._thread_id = None
        self._active = None
        self._closed = False
        self._inode = None
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._socket.bind(str(self._path))
            info = self._path.lstat()
            self._inode = (info.st_dev, info.st_ino)
            os.chmod(self._path, 0o600)
            if allowed_uid != os.geteuid():
                os.chown(self._path, allowed_uid, -1)
            self._socket.listen(16)
            self._socket.settimeout(0.05)
        except BaseException:
            self._socket.close()
            self._unlink_owned()
            raise

    def _unlink_owned(self):
        try:
            info = self._path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self._inode:
            self._path.unlink()

    def _dispatch(self, message, identity):
        if (type(message) is not dict or set(message) != {"method", "params"}
                or type(message["method"]) is not str or type(message["params"]) is not dict):
            raise ValueError("Petición inválida")
        method, params = message["method"], message["params"]
        if _IDENTITY_FIELDS.intersection(params):
            raise ValueError("Identidad inyectada")
        if method not in _ROLES[self._role]:
            raise PermissionError("Método fuera del rol")
        if set(params) != _PARAMS[method]:
            raise ValueError("Parámetros inválidos")
        if method == "approve":
            return self._authority.approve(**params, approver_id=f"human_uid_{identity['uid']}")
        if method == "execute":
            return self._authority.execute(**params, authenticated_principal=self._principal_id)
        if method == "get_receipt":
            return self._authority.get_receipt(**params, authenticated_principal=self._principal_id)
        if method == "revoke":
            return self._authority.revoke_all()
        return self._authority.get_event(**params)

    def _handle(self, conn):
        try:
            identity = peer_identity(conn)
            message = _read(conn, time.monotonic() + self._timeout)
            if identity["uid"] != self._allowed_uid:
                raise PermissionError("UID no autorizado")
            result = self._dispatch(message, identity)
        except PermissionError:
            response = _error("DENIED")
        except (ValueError, TimeoutError):
            response = _error("INVALID_REQUEST")
        except Exception:
            response = _error("INTERNAL_ERROR")
        else:
            response = {"ok": True, "result": result}
        try:
            payload = _encode(response)
        except Exception:
            payload = _encode(_error("INTERNAL_ERROR"))
        try:
            conn.settimeout(self._timeout)
            conn.sendall(payload)
        except OSError:
            pass  # Respuesta perdida: nunca repetir la mutación.

    def serve_forever(self):
        with self._lock:
            if self._closed or self._stop.is_set():
                return
            if self._thread_id is not None:
                raise RuntimeError("El receptor ya está ejecutándose")
            self._thread_id = threading.get_ident()
            self._stopped.clear()
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = self._socket.accept()
                except TimeoutError:
                    continue
                with conn:
                    with self._lock:
                        if self._stop.is_set():
                            break
                        self._active = conn
                    try:
                        self._handle(conn)
                    finally:
                        with self._lock:
                            self._active = None
        finally:
            with self._lock:
                self._thread_id = None
                self._stopped.set()

    def shutdown(self):
        """Detiene el servicio y desbloquea una conexión incompleta; idempotente."""
        with self._lock:
            self._stop.set()
            if self._active is not None:
                try:
                    self._active.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            own_thread = self._thread_id == threading.get_ident()
        if not own_thread:
            self._stopped.wait()

    def close(self):
        """Cierra y elimina únicamente el inode de socket creado por esta instancia."""
        self.shutdown()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._socket.close()
            self._unlink_owned()


def request(socket_path, message, *, timeout=2.0) -> dict:
    """Un envío, sin retries; los errores tras envío no implican ausencia de efecto."""
    timeout = _timeout(timeout)
    payload = _encode(message)
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(os.fspath(socket_path))
        client.settimeout(max(deadline - time.monotonic(), 1e-9))
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        response = _read(client, deadline)
    if type(response) is not dict or type(response.get("ok")) is not bool:
        raise ValueError("Respuesta inválida")
    if response["ok"]:
        if set(response) != {"ok", "result"}:
            raise ValueError("Respuesta inválida")
    elif (set(response) != {"ok", "error"} or type(response["error"]) is not dict
          or set(response["error"]) != {"code"}
          or response["error"]["code"] not in ("DENIED", "INVALID_REQUEST", "INTERNAL_ERROR")):
        raise ValueError("Respuesta inválida")
    return response
