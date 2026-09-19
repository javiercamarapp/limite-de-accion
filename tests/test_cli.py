"""Exercise real CLI processes, not a mocked command dispatcher."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args):
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'))
    return subprocess.run([sys.executable, '-m', 'laboratorio', *map(str, args)],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)


def save(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_cases_score_roundtrip_and_missing(tmp_path):
    generated = cli('cases', '--per-family', '1')
    assert generated.returncode == 0, generated.stderr
    cases = json.loads(generated.stdout)
    catalog = save(tmp_path, 'cases.json', cases)
    responses = save(tmp_path, 'responses.json', [
        {'id': case['id'], 'answer': case['expected']} for case in cases
    ])
    scored = cli('score', catalog, responses)
    assert scored.returncode == 0, scored.stderr
    report = json.loads(scored.stdout)
    assert report['accuracy'] == 1 and report['total'] == 5
    assert report['authorizes_actions'] is False
    missing = cli('score', catalog, save(tmp_path, 'missing.json', []))
    assert json.loads(missing.stdout)['missing'] == 5
    assert json.loads(missing.stdout)['status'] == 'INCOMPLETE'


def test_public_catalog_never_exports_references():
    result = cli('cases', '--public', '--per-family', '1')
    assert result.returncode == 0, result.stderr
    assert all(set(c) == {'id', 'domain', 'prompt'} for c in json.loads(result.stdout))


@pytest.mark.parametrize('raw', ['{bad', '{"x":1,"x":2}', 'NaN', '[' * 1000])
def test_invalid_json_fails_closed_without_traceback(tmp_path, raw):
    path = tmp_path / 'invalid.json'
    path.write_text(raw)
    result = cli('score', path, path)
    assert result.returncode == 2
    assert json.loads(result.stderr)['actions_authorized'] is False
    assert result.stdout == ''


def test_missing_file_and_oversized_input(tmp_path):
    path = tmp_path / 'missing.json'
    assert cli('score', path, path).returncode == 2
    path.write_text(' ' * 2_000_001)
    result = cli('score', path, path)
    assert result.returncode == 2
    assert json.loads(result.stderr)['actions_authorized'] is False


def test_control_demo_is_explicitly_synthetic():
    result = cli('demo-control')
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    for key in ('altered_intent_denied', 'replay_same_receipt', 'revoked_intent_denied'):
        assert report[key] is True
    assert report['human_approval_performed'] is False
    assert report['external_effects'] is False
    assert report['C1_T02_verified'] is False


def test_forecast_and_backtest_cli(tmp_path):
    empty = save(tmp_path, 'empty.json', [])
    result = cli('forecast-score', empty, empty, '--now', '2026-09-19T10:00:00Z')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['brier'] is None
    observations = save(tmp_path, 'observations.json', [
        {'date': f'2026-09-{day:02}', 'value': day} for day in range(1, 7)
    ])
    result = cli('backtest', observations)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['n'] == 2
    assert json.loads(result.stdout)['prospective_validation'] is False
