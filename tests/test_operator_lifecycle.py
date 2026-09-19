"""Regressions from independent review: cleanup must not manufacture success."""
import sqlite3
import threading

import pytest
from laboratorio import operator_cli as operator
from test_operator_cli import root, prepare


@pytest.mark.parametrize('fault', ['close', 'late_worker'])
def test_cleanup_visits_all_resources_and_reports_late_errors(root, monkeypatch, fault):
    prepare(root)
    receivers, authorities = [], []
    original = operator.LocalAuthority

    class Authority(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            authorities.append(self)

    class Receiver:
        def __init__(self, path, *args, **kwargs):
            self.path, self.done = path, threading.Event()
            self.thread = None
            self.closed = False
            receivers.append(self)

        def serve_forever(self):
            self.thread = threading.current_thread()
            self.done.wait(3)
            if fault == 'late_worker':
                raise OSError('receiver failed during shutdown')

        def close(self):
            self.closed = True
            self.done.set()
            if fault == 'close' and self.path.name == 'a.sock':
                raise PermissionError('owned endpoint cleanup failed')

    monkeypatch.setattr(operator, 'LocalAuthority', Authority)
    monkeypatch.setattr(operator, 'UnixReceiver', Receiver)
    stop = threading.Event(); stop.set()
    try:
        with pytest.raises(RuntimeError):
            operator.serve(root, stop=stop)
        assert len(receivers) == 2 and all(r.closed for r in receivers)
        assert all(r.thread is not None and not r.thread.is_alive() for r in receivers)
        with pytest.raises(sqlite3.ProgrammingError):
            authorities[0]._db.execute('SELECT 1')
    finally:
        # A failing regression must not leave its own test workers behind.
        for receiver in receivers:
            receiver.done.set()
        for receiver in receivers:
            if receiver.thread is not None:
                receiver.thread.join(3)
        for authority in authorities:
            authority._db.close()
