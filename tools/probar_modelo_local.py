"""Lote fijo con watchdog; las variables offline NO constituyen un sandbox OS."""
import argparse
import json
import os
import signal
import selectors
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

B = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(B / 'src'))
from laboratorio.evaluation import make_cases, public_cases, evaluate, loads_strict, MAX_TEXT

POLL_SECONDS = 0.05
TERM_GRACE_SECONDS = 0.5
MAX_LOG_BYTES = 2_000_000
READ_CHUNK = 65536


def read_text_bounded(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Entrada debe ser archivo regular')
        if info.st_size > MAX_TEXT:
            raise ValueError('Entrada demasiado grande')
        data = stream.read(MAX_TEXT + 1)
        if len(data) > MAX_TEXT:
            raise ValueError('Entrada demasiado grande')
        return data.decode('utf-8')


def remaining(monotonic_deadline, civil_deadline):
    return min(monotonic_deadline - time.monotonic(), civil_deadline - time.time())


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_output(value):
    # Do not resolve away symlinks before validating the path.
    out = Path(os.path.abspath(value))
    runs = B / 'runs'
    if not out.is_relative_to(runs) or out == runs:
        raise ValueError('Salida debe estar dentro de runs/')
    current = runs
    for part in (None, *out.relative_to(runs).parts[:-1]):
        if part is not None:
            current /= part
        if current.is_symlink():
            raise ValueError('Symlink no permitido en salida')
        current.mkdir(exist_ok=True)
    out.mkdir(exist_ok=False)
    return out


def cleanup(child):
    """Signal only the session/process group created for this child, then reap."""
    if child is None:
        return
    def send(sig):
        try:
            os.killpg(child.pid, sig)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # macOS can report EPERM for a group whose last process has exited.
            # Accept this only for a probe AND after observing our child's exit;
            # never suppress a denied signal to a live process.
            if sig == 0:
                try:
                    # The group can disappear before waitpid reports the exit.
                    child.wait(timeout=POLL_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                if child.returncode is not None:
                    return False
            raise
    try:
        if send(signal.SIGTERM):
            mono = time.monotonic() + TERM_GRACE_SECONDS
            civil = time.time() + TERM_GRACE_SECONDS
            while remaining(mono, civil) > 0:
                child.poll()
                if not send(0):
                    return
                time.sleep(min(POLL_SECONDS, max(0, remaining(mono, civil))))
            send(signal.SIGKILL)
    finally:
        try:
            child.wait(timeout=TERM_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            # Bound reaping even if group signaling failed; this Popen is ours.
            child.kill()
            child.wait(timeout=TERM_GRACE_SECONDS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--seed', type=int, default=17)
    p.add_argument('--per-family', type=int, default=4)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--cases')
    p.add_argument('--adapter')
    p.add_argument('--profile', choices=['base', 'typed'], default='base')
    args = p.parse_args()
    if not 30 <= args.timeout <= 600 or not 1 <= args.per_family <= 20:
        raise ValueError('Presupuesto fuera de límites')
    civil_start, mono_start = time.time(), time.monotonic()
    civil_deadline = civil_start + args.timeout
    if os.environ.get('LAB_BUILD_DEADLINE'):
        civil_deadline = min(civil_deadline, datetime.fromisoformat(os.environ['LAB_BUILD_DEADLINE']).timestamp())
    timeout = min(args.timeout, civil_deadline - civil_start)
    mono_deadline = mono_start + timeout
    out = create_output(args.out)
    state = {'start_utc': datetime.now(timezone.utc).isoformat(), 'status': 'RUNNING',
             'timeout_seconds': timeout, 'model_tools': False, 'os_sandbox_verified': False}
    child = None
    cases = None
    report = None
    error = None
    interrupted = []
    previous = {}
    def on_signal(signum, frame):
        # Deferred handling also covers the interval before Popen returns its PID.
        interrupted.append(signum)
    def check_interrupt():
        if interrupted:
            raise KeyboardInterrupt('Runner interrumpido')
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, on_signal)
        atomic_json(out / 'state.json', state)
        cases = loads_strict(read_text_bounded(args.cases)) if args.cases else make_cases(args.seed, args.per_family)
        evaluate(cases, [])
        atomic_json(out / 'references.json', cases)
        atomic_json(out / 'cases.json', public_cases(cases))
        (out / 'home').mkdir()
        (out / 'tmp').mkdir()
        env = {'PATH': str(B / '.venv/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
               'HOME': str(out / 'home'), 'TMPDIR': str(out / 'tmp'), 'PYTHONUTF8': '1',
               'PYTHONHASHSEED': '0', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
               'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'TOKENIZERS_PARALLELISM': 'false'}
        cmd = [sys.executable, str(B / 'tools/inferencia_mlx.py'), '--cases', str(out / 'cases.json'),
               '--output', str(out / 'inference.json'), '--profile', args.profile]
        if args.adapter:
            cmd += ['--adapter', args.adapter]
        state['command'] = cmd
        check_interrupt()
        if remaining(mono_deadline, civil_deadline) <= 0:
            state['status'] = 'TIMEOUT'
        else:
            with (out / 'worker.stdout').open('xb') as stdout, (out / 'worker.stderr').open('xb') as stderr, selectors.DefaultSelector() as selector:
                child = subprocess.Popen(cmd, cwd=B, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                state['pid'] = child.pid
                atomic_json(out / 'state.json', state)
                for pipe, destination in ((child.stdout, stdout), (child.stderr, stderr)):
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, destination)
                logged = 0
                while True:
                    check_interrupt()
                    budget = remaining(mono_deadline, civil_deadline)
                    if budget <= 0:
                        state['status'] = 'TIMEOUT'
                        break
                    # Operational size check only: this is not an OS disk quota.
                    try:
                        info = (out / 'inference.json').lstat()
                        if stat.S_ISREG(info.st_mode) and info.st_size > MAX_TEXT:
                            raise ValueError('Resultado de inferencia demasiado grande')
                    except FileNotFoundError:
                        pass
                    for key, _ in selector.select(min(POLL_SECONDS, budget)):
                        data = os.read(key.fileobj.fileno(), min(READ_CHUNK, MAX_LOG_BYTES - logged + 1))
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        available = MAX_LOG_BYTES - logged
                        key.data.write(data[:available])
                        logged += len(data)
                        if logged > MAX_LOG_BYTES:
                            raise ValueError('Límite total de logs excedido')
                    if child.poll() is not None and not selector.get_map():
                        state['status'] = 'FINISHED' if child.returncode == 0 else 'FAILED'
                        break
    except BaseException as exc:
        state['status'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) or interrupted else 'FAILED'
        error = exc
    finally:
        try:
            cleanup(child)
        except BaseException as exc:
            state['status'] = 'FAILED'
            error = error or exc
        if child:
            for pipe in (child.stdout, child.stderr):
                if pipe is not None:
                    pipe.close()
        state['returncode'] = child.returncode if child else None
        try:
            raw = {'responses': [], 'format_errors': []}
            inference = out / 'inference.json'
            try:
                text = read_text_bounded(inference)
            except FileNotFoundError:
                raw['format_errors'].append('Resultado de inferencia ausente')
            else:
                raw = loads_strict(text)
                if type(raw) is not dict or type(raw.get('responses')) is not list or type(raw.get('format_errors')) is not list:
                    raise ValueError('Formato de inferencia inválido')
            report = evaluate(cases, raw['responses'])
            if state['status'] == 'FINISHED' and (report['missing'] or raw['format_errors']):
                state['status'] = 'FAILED'
            report.update({'format_errors': raw['format_errors'], 'model': raw.get('model'),
                           'revision': raw.get('revision'), 'elapsed_seconds': raw.get('elapsed_seconds'),
                           'mlx_peak_bytes': raw.get('mlx_peak_bytes')})
        except BaseException as exc:
            error = error or exc
            if state['status'] == 'FINISHED':
                state['status'] = 'FAILED'
            try:
                report = evaluate(cases, [])
            except Exception:
                report = {}
            report.update({'format_errors': [str(exc)], 'elapsed_seconds': None, 'mlx_peak_bytes': None})
        # state.json is authoritative once terminal persistence closes. Files are
        # individually atomic, not a crash-safe two-file transaction. SIGKILL is
        # outside this protocol. Block signals at the closing boundary, restoring
        # the previous handlers before unblocking; later signals belong to caller.
        closing_mask = None
        failures = 0
        state['end_utc'] = datetime.now(timezone.utc).isoformat()
        try:
            while True:
                if interrupted:
                    state['status'] = 'INTERRUPTED'
                    state['signal'] = interrupted[0]
                if error:
                    state['error'] = f'{type(error).__name__}: {error}'
                report.update({'execution_status': state['status'],
                               'benchmark': 'PUBLIC_SYNTHETIC_SMOKE_NOT_HELD_OUT'})
                try:
                    report_error = None
                    try:
                        atomic_json(out / 'evaluation.json', report)
                    except BaseException as exc:
                        report_error = exc
                        error = exc
                        state['status'] = 'INTERRUPTED' if interrupted else 'FAILED'
                        state['error'] = f'{type(exc).__name__}: {exc}'
                        if interrupted:
                            state['signal'] = interrupted[0]
                    # A handler can run inside either persistence operation.
                    if interrupted and state['status'] != 'INTERRUPTED':
                        continue
                    atomic_json(out / 'state.json', state)
                    if report_error is not None:
                        raise report_error
                except BaseException as exc:
                    error = exc
                    state['status'] = 'INTERRUPTED' if interrupted else 'FAILED'
                    state['error'] = f'{type(exc).__name__}: {exc}'
                    report['execution_status'] = state['status']
                    failures += 1
                    if failures <= 1:
                        continue
                    # Even when terminal state cannot be saved, report the failure
                    # where possible and keep the persistence error visible.
                    try:
                        atomic_json(out / 'evaluation.json', report)
                    except BaseException:
                        pass
                    break
                closing_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set(previous))
                if interrupted and state['status'] != 'INTERRUPTED':
                    signal.pthread_sigmask(signal.SIG_SETMASK, closing_mask)
                    closing_mask = None
                    continue
                break
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if closing_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, closing_mask)
    if error and not isinstance(error, KeyboardInterrupt):
        raise error
    print(json.dumps({k: report.get(k) for k in ('execution_status', 'total', 'correct', 'missing',
                                                'accuracy', 'coverage', 'elapsed_seconds', 'mlx_peak_bytes')}, indent=2))
    return 0 if state['status'] == 'FINISHED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
