"""Pruebas locales con identidad de proceso; ninguna representa a una persona."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
import sys
import tempfile
import threading
import time

import pytest

from laboratorio.authority import LocalAuthority, intent_digest
from laboratorio.unix_transport import UnixReceiver, peer_identity, request


@pytest.fixture
def lab():
    # Cadena de padres protegida: /tmp compartido no es un padre confiable.
    with tempfile.TemporaryDirectory(prefix=".unix-test-", dir=Path.cwd()) as directory:
        root = Path(directory)
        authority = LocalAuthority(root / "db", clock=lambda: "2026-09-19T10:00:00Z")
        intent = dict(schema_version="C1.intent.v1", intent_id="intent_test",
                      run_id="run_test", principal_id="agent_test", calendar_id="cal_test",
                      event_id="event_test", operation="RESCHEDULE_EVENT", expected_version=0,
                      start_utc="2026-09-20T10:00:00Z", end_utc="2026-09-20T10:30:00Z")
        authority.create_event("cal_test", "event_test", "2026-09-20T08:00:00Z",
                               "2026-09-20T08:30:00Z", title="fixture")
        yield root, authority, intent
        authority._db.close()


@contextmanager
def running(lab, role="admin", **kwargs):
    root, authority, _ = lab
    require_bind(root)
    receiver = UnixReceiver(root / role, authority, allowed_uid=kwargs.pop("allowed_uid", os.getuid()),
                            role=role, principal_id="agent_test" if role == "dispatcher" else None,
                            timeout=kwargs.pop("timeout", 0.1), **kwargs)
    thread = threading.Thread(target=receiver.serve_forever)
    thread.start()
    try:
        yield receiver, root / role
    finally:
        receiver.shutdown()
        receiver.close()
        thread.join(2)
        assert not thread.is_alive()


def message(method="get_event", **params):
    return {"method": method, "params": params or (dict(calendar_id="cal_test", event_id="event_test")
                                                   if method == "get_event" else {})}


def raw(path, payload, *, eof=True):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        client.connect(str(path))
        client.sendall(payload)
        if eof:
            try:
                client.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno != errno.ENOTCONN:
                    raise
        output = b""
        while not output.endswith(b"\n"):
            chunk = client.recv(65537)
            if not chunk:
                break
            output += chunk
        return json.loads(output)


def error(code):
    return {"ok": False, "error": {"code": code}}


def test_real_peer_identity():
    a, b = socket.socketpair(socket.AF_UNIX)
    try:
        identity = peer_identity(a)
        assert identity["uid"] == os.getuid()
        assert identity["gid"] == os.getgid()
        if sys.platform.startswith("linux"):
            assert identity["pid"] == os.getpid()
    finally:
        a.close()
        b.close()


def test_approval_execute_exactly_once(lab):
    _, authority, intent = lab
    with running(lab) as (_, admin), running(lab, "dispatcher") as (_, dispatcher):
        assert stat.S_IMODE(admin.stat().st_mode) == 0o600
        params = dict(intent=intent, original_request_digest=intent_digest(intent),
                      expires_at="2026-09-19T11:00:00Z")
        wrong = {**params, "original_request_digest": intent_digest({**intent, "intent_id": "other"})}
        assert request(admin, message("approve", **wrong)) == error("DENIED")
        approval = request(admin, message("approve", **params))["result"]
        row = authority._db.execute("SELECT approver_id, original_request_digest FROM approvals").fetchone()
        assert tuple(row) == (f"human_uid_{os.getuid()}", intent_digest(intent))
        command = message("execute", intent=intent, approval_id=approval, operation_id="op_test")
        result = request(dispatcher, command)
        assert result["ok"] and result["result"]["version"] == 1
        assert request(dispatcher, command) == result
        assert request(dispatcher, {**command, "params": {**command["params"], "operation_id": "op_other"}}) == error("DENIED")
        assert request(admin, message())["result"]["version"] == 1
        assert request(admin, message())["result"]["title"] == "fixture"


def test_wrong_actor_and_revoke(lab):
    _, _, intent = lab
    with running(lab) as (_, admin), running(lab, "dispatcher") as (_, dispatcher):
        for actor, revoke in [("other_agent", False), ("agent_test", True)]:
            changed = {**intent, "principal_id": actor}
            approval = request(admin, message("approve", intent=changed, original_request_digest=intent_digest(changed),
                                              expires_at="2026-09-19T11:00:00Z"))["result"]
            if revoke:
                assert request(admin, message("revoke")) == {"ok": True, "result": 1}
            assert request(dispatcher, message("execute", intent=changed, approval_id=approval,
                                               operation_id="op_test")) == error("DENIED")
        assert request(admin, message())["result"]["version"] == 0


@pytest.mark.parametrize("role,method", [("admin", "execute"), ("dispatcher", "approve"),
    ("dispatcher", "revoke"), ("admin", "create_event"), ("admin", "delete"), ("admin", "sql")])
def test_roles_and_no_bootstrap(lab, role, method):
    with running(lab, role) as (_, path):
        assert request(path, message(method)) == error("DENIED")
        assert request(path, message())["result"]["version"] == 0


@pytest.mark.parametrize("field", ["role", "uid", "principal", "principal_id", "approver", "approver_id", "authenticated_principal"])
@pytest.mark.parametrize("location", ["top", "params"])
def test_identity_injection(lab, field, location):
    with running(lab) as (_, path):
        payload = message()
        (payload if location == "top" else payload["params"])[field] = "forged"
        assert request(path, payload) == error("INVALID_REQUEST")
        assert request(path, message())["result"]["version"] == 0


@pytest.mark.parametrize("payload", [b'{"method":"revoke","method":"revoke","params":{}}\n',
    b'{"method":"revoke","params":{"x":NaN}}\n', b'{"method":"revoke","params":{"x":1e999}}\n',
    b'{"method":', b'{}', b'{}\n{}\n', b' ' * 65537, b'\xff\n',
    b'{"method":"get_event","params":{"calendar_id":"a","calendar_id":"b"}}\n'],
    ids=["duplicate", "nan", "overflow", "truncated", "no_lf", "multiple", "oversize", "utf8", "nested_duplicate"])
def test_bad_wire_and_recovery(lab, payload):
    with running(lab) as (_, path):
        assert raw(path, payload) == error("INVALID_REQUEST")
        assert request(path, message())["result"]["version"] == 0


def test_connection_timeout_and_delayed_second_request(lab):
    with running(lab) as (_, path):
        assert raw(path, b'{', eof=False) == error("INVALID_REQUEST")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(str(path))
            client.sendall(b'{"method":"revoke","params":{}}\n')
            time.sleep(0.02)
            client.sendall(b'{}\n')
            client.shutdown(socket.SHUT_WR)
            assert json.loads(client.recv(4096)) == error("INVALID_REQUEST")
        assert request(path, message("revoke"))["result"] == 1


@pytest.mark.parametrize("setting", [dict(allowed_uid=True), dict(allowed_uid=-1), dict(allowed_uid=1.0),
    dict(role="owner"), dict(timeout=0), dict(timeout=-1), dict(timeout=True), dict(timeout=float("inf")),
    dict(timeout=float("nan")), dict(role="dispatcher"), dict(role="dispatcher", principal_id="ágent"),
    dict(role="dispatcher", principal_id="agent space")])
def test_invalid_configuration(lab, setting):
    root, authority, _ = lab
    with pytest.raises(ValueError):
        UnixReceiver(root / "invalid", authority, **{**dict(allowed_uid=os.getuid(), role="admin"), **setting})
    assert not (root / "invalid").exists()


def test_wrong_uid_configuration_or_peer_denial(lab):
    root, authority, _ = lab
    if os.geteuid() != 0:
        with pytest.raises(PermissionError):
            UnixReceiver(root / "other", authority, allowed_uid=os.getuid() + 1, role="admin")
        assert not (root / "other").exists()
    # Test-only configuration change after binding permits a real mismatched
    # peer test without chown or changing the process identity on the host.
    with running(lab) as (receiver, path):
        path.chmod(0o666)
        receiver._allowed_uid = os.getuid() + 1
        assert request(path, message("revoke")) == error("DENIED")
        receiver._allowed_uid = os.getuid()
        assert request(path, message("revoke"))["result"] == 1



def test_existing_and_untrusted_paths(lab):
    root, authority, _ = lab
    target = root / "existing"
    target.write_text("preserve")
    link = root / "link"
    link.symlink_to(target)
    for path in (target, link):
        with pytest.raises((ValueError, FileExistsError)):
            UnixReceiver(path, authority, allowed_uid=os.getuid(), role="admin")
    assert target.read_text() == "preserve" and link.is_symlink()
    unsafe = root / "unsafe"
    unsafe.mkdir(mode=0o777)
    unsafe.chmod(0o777)
    with pytest.raises(PermissionError):
        UnixReceiver(unsafe / "s", authority, allowed_uid=os.getuid(), role="admin")
    unsafe.chmod(0o700)
    (root / "alias").symlink_to(unsafe, target_is_directory=True)
    with pytest.raises(PermissionError):
        UnixReceiver(root / "alias" / "s", authority, allowed_uid=os.getuid(), role="admin")


def test_close_own_and_replaced(lab):
    root, authority, _ = lab
    require_bind(root)
    for replace in (False, True):
        path = root / "endpoint"
        receiver = UnixReceiver(path, authority, allowed_uid=os.getuid(), role="admin")
        if replace:
            path.unlink()
            path.write_text("replacement")
        receiver.shutdown()
        receiver.close()
        receiver.close()
        assert path.exists() is replace
        if replace:
            assert path.read_text() == "replacement"


def test_internal_error_is_sanitized(lab, monkeypatch):
    _, authority, _ = lab
    original = authority.get_event
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("secret storage details")
    with running(lab) as (_, path):
        monkeypatch.setattr(authority, "get_event", broken)
        assert request(path, message()) == error("INTERNAL_ERROR")
        monkeypatch.setattr(authority, "get_event", original)
        assert request(path, message())["ok"]


def test_client_response_loss_no_retry(lab):
    root, _, _ = lab
    require_bind(root)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(root / "fake"))
        server.listen()
        server.settimeout(0.2)
        received = []
        def drop():
            conn, _ = server.accept()
            with conn:
                data = b""
                while chunk := conn.recv(65536):
                    data += chunk
                received.append(data)
            try:
                conn, _ = server.accept()
            except TimeoutError:
                return
            conn.close()
            received.append(b"RETRIED")
        thread = threading.Thread(target=drop)
        thread.start()
        with pytest.raises((ValueError, OSError)):
            request(root / "fake", message(), timeout=0.1)
        thread.join(2)
        assert len(received) == 1
        assert json.loads(received[0]) == message()
        assert received[0].count(b"\n") == 1


def require_bind(root):
    """Only EPERM from the host sandbox is an explicit integration-test skip."""
    path = root / "probe"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(str(path))
        except OSError as exc:
            if exc.errno == errno.EPERM:
                pytest.skip("Host sandbox denies AF_UNIX bind (EPERM); endpoint integration unverified")
            raise
        finally:
            if path.exists():
                path.unlink()


def pair_receiver(lab, role="admin", uid=None):
    # Handler-only fixture: intentionally does not stand in for constructor tests.
    receiver = object.__new__(UnixReceiver)
    receiver._authority = lab[1]
    receiver._role = role
    receiver._allowed_uid = os.getuid() if uid is None else uid
    receiver._principal_id = "agent_test" if role == "dispatcher" else None
    receiver._timeout = 0.1
    return receiver


def pair_exchange(receiver, payload, eof=True):
    client, server = socket.socketpair(socket.AF_UNIX)
    def handle():
        with server:
            receiver._handle(server)
    thread = threading.Thread(target=handle)
    thread.start()
    try:
        with client:
            client.settimeout(2)
            client.sendall(payload)
            if eof:
                try:
                    client.shutdown(socket.SHUT_WR)
                except OSError as exc:
                    if exc.errno != errno.ENOTCONN:
                        raise
            data = b""
            while chunk := client.recv(65536):
                data += chunk
            assert data.count(b"\n") == 1
            return json.loads(data)
    finally:
        thread.join(2)
        assert not thread.is_alive()


def pair_call(receiver, command):
    return pair_exchange(receiver, json.dumps(command).encode() + b"\n")


def test_socketpair_full_authority_contract(lab):
    admin, dispatcher = pair_receiver(lab), pair_receiver(lab, "dispatcher")
    intent = lab[2]
    params = dict(intent=intent, original_request_digest=intent_digest(intent), expires_at="2026-09-19T11:00:00Z")
    assert pair_call(admin, message("approve", **{**params, "original_request_digest": "C1.intent.v1:sha256:" + "0" * 64})) == error("DENIED")
    token = pair_call(admin, message("approve", **params))["result"]
    command = message("execute", intent=intent, approval_id=token, operation_id="op_pair")
    assert pair_call(admin, command) == error("DENIED")
    assert pair_call(dispatcher, message("approve", **params)) == error("DENIED")
    for field in ("uid", "role", "principal_id", "approver_id", "authenticated_principal"):
        assert pair_call(dispatcher, {**command, field: "forged"}) == error("INVALID_REQUEST")
        assert pair_call(dispatcher, {**command, "params": {**command["params"], field: "forged"}}) == error("INVALID_REQUEST")
    other = {**intent, "principal_id": "other_agent"}
    other_token = pair_call(admin, message("approve", **{**params, "intent": other, "original_request_digest": intent_digest(other)}))["result"]
    assert pair_call(dispatcher, message("execute", intent=other, approval_id=other_token, operation_id="op_other")) == error("DENIED")
    assert pair_call(admin, message())["result"]["version"] == 0
    result = pair_call(dispatcher, command)
    assert result["ok"] and result["result"]["version"] == 1
    assert pair_call(dispatcher, command) == result
    assert pair_call(dispatcher, message("execute", **{**command["params"], "operation_id": "op_repeat"})) == error("DENIED")
    assert pair_call(admin, message())["result"]["version"] == 1
    row = lab[1]._db.execute("SELECT approver_id, original_request_digest FROM approvals WHERE approval_id = ?", (token,)).fetchone()
    assert tuple(row) == (f"human_uid_{os.getuid()}", intent_digest(intent))


@pytest.mark.parametrize("payload", [b'{"method":"revoke","method":"revoke","params":{}}\n',
    b'{"method":"revoke","params":{"x":NaN}}\n', b'{"method":"revoke","params":{"x":1e999}}\n',
    b'{', b'{}', b'{}\n{}\n', b' ' * 65537, b'\xff\n'],
    ids=["duplicate", "nan", "overflow", "truncated", "no_lf", "multiple", "oversize", "utf8"])
def test_socketpair_bad_wire_recovery(lab, payload):
    receiver = pair_receiver(lab)
    assert pair_exchange(receiver, payload) == error("INVALID_REQUEST")
    assert pair_call(receiver, message("revoke")) == {"ok": True, "result": 1}


def test_socketpair_timeout_wrong_uid_and_storage_error(lab, monkeypatch):
    receiver = pair_receiver(lab)
    assert pair_exchange(receiver, b'{', eof=False) == error("INVALID_REQUEST")
    receiver._allowed_uid = os.getuid() + 1
    assert pair_call(receiver, message("revoke")) == error("DENIED")
    receiver._allowed_uid = os.getuid()
    assert pair_call(receiver, message("revoke"))["result"] == 1
    def broken(*args, **kwargs):
        raise sqlite3.OperationalError("secret details")
    monkeypatch.setattr(lab[1], "get_event", broken)
    assert pair_call(receiver, message()) == error("INTERNAL_ERROR")


def test_unsupported_platform_fails_closed(monkeypatch):
    import laboratorio.unix_transport as transport
    a, b = socket.socketpair(socket.AF_UNIX)
    try:
        monkeypatch.setattr(transport.sys, "platform", "unsupported")
        with pytest.raises(PermissionError):
            peer_identity(a)
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("reply", [b'', b'{}\n', b'{"ok":true,"result":NaN}\n',
    b'{"ok":true,"ok":true,"result":null}\n', b'{"ok":true,"result":null}\n{}\n',
    b' ' * 65537, b'{"ok":true,"result":null}',
    b'{"ok":true,"result":{"version":1}}\n', None],
    ids=["lost", "shape", "nan", "duplicate", "multiple", "oversize", "truncated", "success", "timeout"])
def test_client_strict_response_and_single_send_over_real_socketpair(lab, monkeypatch, reply):
    import laboratorio.unix_transport as transport
    client, server = socket.socketpair(socket.AF_UNIX)
    calls, received = [], []
    class ConnectedSocket:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            client.close()
        def __getattr__(self, name):
            return getattr(client, name)
        def connect(self, path):
            calls.append("connect")
        def sendall(self, data):
            calls.append("sendall")
            client.sendall(data)
    def factory(*args):
        calls.append("socket")
        return ConnectedSocket()
    def respond():
        with server:
            data = b""
            while chunk := server.recv(65536):
                data += chunk
            received.append(data)
            if reply is None:
                time.sleep(0.15)
            elif reply:
                server.sendall(reply)
    thread = threading.Thread(target=respond)
    thread.start()
    monkeypatch.setattr(transport.socket, "socket", factory)
    try:
        if reply == b'{"ok":true,"result":{"version":1}}\n':
            assert request("unused-adapter-path", message(), timeout=0.1) == {"ok": True, "result": {"version": 1}}
        elif reply is None:
            with pytest.raises(TimeoutError):
                request("unused-adapter-path", message(), timeout=0.02)
        else:
            with pytest.raises((ValueError, OSError)):
                request("unused-adapter-path", message(), timeout=0.1)
    finally:
        thread.join(2)
    assert not thread.is_alive()
    assert calls == ["socket", "connect", "sendall"]
    assert len(received) == 1 and json.loads(received[0]) == message()


def test_client_rejects_non_json_without_sending(monkeypatch):
    import laboratorio.unix_transport as transport
    def unexpected(*args):
        pytest.fail("invalid message must not open a socket")
    monkeypatch.setattr(transport.socket, "socket", unexpected)
    for payload in ({"x": float("nan")}, {1: "nontext"}, {"x": object()}, {"x": "a" * 65536}):
        with pytest.raises(ValueError):
            request("unused", payload)


def test_peer_identity_closed_socket_fails():
    a, b = socket.socketpair(socket.AF_UNIX)
    a.close()
    b.close()
    with pytest.raises(PermissionError):
        peer_identity(a)


def test_socketpair_semantic_errors_and_response_bound(lab):
    receiver = pair_receiver(lab)
    invalid = {**lab[2], "expected_version": True}
    assert pair_call(receiver, message("approve", intent=invalid, original_request_digest=intent_digest(lab[2]),
                                     expires_at="2026-09-19T11:00:00Z")) == error("INVALID_REQUEST")
    lab[1].create_event("cal_test", "large_event", "2026-09-20T08:00:00Z", "2026-09-20T08:30:00Z", title="x" * 65536)
    assert pair_call(receiver, message("get_event", calendar_id="cal_test", event_id="large_event")) == error("INTERNAL_ERROR")
    assert pair_call(receiver, message())["result"]["version"] == 0
