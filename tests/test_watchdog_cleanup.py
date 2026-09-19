"""Regression for macOS EPERM when probing an already terminated process group."""
import importlib.util
from pathlib import Path
import signal
import subprocess
import sys

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[1] / 'tools/probar_modelo_local.py'
    spec = importlib.util.spec_from_file_location('cleanup_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Child:
    pid = 123456789
    returncode = None
    waited = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


def test_probe_eperm_after_observed_exit_stops_signaling(runner, monkeypatch):
    child = Child()
    calls = []

    def killpg(pid, sig):
        assert pid == child.pid
        calls.append(sig)
        if sig == signal.SIGTERM:
            child.returncode = -signal.SIGTERM
        else:
            raise PermissionError(1, 'Operation not permitted')

    monkeypatch.setattr(runner.os, 'killpg', killpg)
    runner.cleanup(child)
    assert calls == [signal.SIGTERM, 0]
    assert child.waited


def test_delayed_waitpid_after_group_disappearance(runner, monkeypatch):
    child = Child()
    def killpg(pid, sig):
        if sig == 0:
            raise PermissionError(1, 'Operation not permitted')
    def wait(timeout=None):
        child.returncode = -signal.SIGTERM
        child.waited = True
        return child.returncode
    monkeypatch.setattr(runner.os, 'killpg', killpg)
    child.wait = wait
    runner.cleanup(child)
    assert child.waited


def test_repeated_fast_termination_of_real_children(runner):
    for _ in range(20):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'],
                                 start_new_session=True)
        try:
            runner.cleanup(child)
            assert child.returncode is not None
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)


def test_permission_failure_with_live_child_is_not_suppressed(runner, monkeypatch):
    child = Child()

    def killpg(pid, sig):
        raise PermissionError(1, 'Operation not permitted')

    monkeypatch.setattr(runner.os, 'killpg', killpg)
    with pytest.raises(PermissionError):
        runner.cleanup(child)
    assert child.waited


def test_disappeared_group_gets_no_followup_kill(runner, monkeypatch):
    child = Child()
    calls = []

    def killpg(pid, sig):
        calls.append(sig)
        if sig == signal.SIGTERM:
            child.returncode = -signal.SIGTERM
        else:
            raise ProcessLookupError()

    monkeypatch.setattr(runner.os, 'killpg', killpg)
    runner.cleanup(child)
    assert calls == [signal.SIGTERM, 0]
    assert child.waited
