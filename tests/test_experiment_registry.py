"""Real offline manifests, persistence and strict input boundaries."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from laboratorio import experiment_registry as registry


def fixture_spec(tmp_path):
    root = tmp_path.resolve()
    for name, data in [('input.json', b'{"synthetic":true}'), ('result.json', b'{"score":0}'), ('code.py', b'raise RuntimeError("never execute")\n')]:
        (root / name).write_bytes(data)
    return {'experiment_id': 'synthetic-demo', 'source': 'synthetic',
            'configuration': {'seed': 7, 'profile': 'public'},
            'inputs': [{'name': 'cases', 'path': str(root / 'input.json')}],
            'results': [{'name': 'score', 'path': str(root / 'result.json')}],
            'code': [{'name': 'evaluator', 'path': str(root / 'code.py')}]}


def test_real_hashes_versions_reopen_and_readonly_export(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    first = registry.append(path, spec)
    assert first['manifest']['version'] == 1
    assert first['manifest']['state'] == 'AVAILABLE'
    assert first['manifest']['artifacts']['inputs'][0]['sha256'] == hashlib.sha256((tmp_path / 'input.json').read_bytes()).hexdigest()
    before = (path / '000001.json').read_bytes()
    (tmp_path / 'result.json').write_text('{"score":1}')
    second = registry.append(path, spec)
    assert second['manifest']['previous_sha256'] == first['sha256']
    assert second['manifest']['version'] == 2
    assert (path / '000001.json').read_bytes() == before
    snapshot = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}
    export = registry.export_registry(path)
    assert registry.verify_export(export)['versions'] == 2
    assert registry.history(path) == [first, second]
    assert snapshot == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}
    with pytest.raises((ValueError, OSError)):
        registry.initialize(path)
    assert (path / '000001.json').read_bytes() == before


def test_missing_invalid_and_later_results_do_not_rewrite_history(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    (tmp_path / 'result.json').unlink()
    missing = registry.append(path, spec)
    assert missing['manifest']['state'] == 'MISSING'
    assert missing['manifest']['artifacts']['results'][0]['sha256'] is None
    os.mkfifo(tmp_path / 'result.json')
    invalid = registry.append(path, spec)
    assert invalid['manifest']['state'] == 'INVALID'
    assert invalid['manifest']['artifacts']['results'][0]['reason'] == 'UNSAFE_FILE'
    assert registry.history(path)[0] == missing


@pytest.mark.parametrize('change', ['declared_hash', 'secret_config', 'unknown', 'duplicate_label', 'relative', 'no_code'])
def test_bad_specs_rejected_without_append(tmp_path, change):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    if change == 'declared_hash': spec['inputs'][0]['sha256'] = '0' * 64
    if change == 'secret_config': spec['configuration']['api_key'] = 'synthetic-placeholder'
    if change == 'unknown': spec['approved'] = True
    if change == 'duplicate_label': spec['inputs'] *= 2
    if change == 'relative': spec['inputs'][0]['path'] = 'input.json'
    if change == 'no_code': spec['code'] = []
    with pytest.raises(ValueError): registry.append(path, spec)
    assert list(path.iterdir()) == []


def test_symlinks_and_secret_files_excluded(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    (tmp_path / 'link').symlink_to(tmp_path / 'input.json')
    spec['inputs'][0]['path'] = str(tmp_path.resolve() / 'link')
    record = registry.append(path, spec)
    assert record['manifest']['state'] == 'INVALID'
    (tmp_path / '.env').write_text('SYNTHETIC_SECRET=never-export-this')
    spec['inputs'][0]['path'] = str(tmp_path.resolve() / '.env')
    record = registry.append(path, spec)
    assert record['manifest']['artifacts']['inputs'][0]['reason'] == 'SECRET_EXCLUDED'
    assert 'never-export-this' not in json.dumps(registry.export_registry(path))
    (tmp_path / 'alias').symlink_to(path, target_is_directory=True)
    with pytest.raises((ValueError, OSError)): registry.history(tmp_path.resolve() / 'alias')


def test_corruption_and_partial_history_fail_closed(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    registry.append(path, spec)
    export = registry.export_registry(path)
    export['records'][0]['manifest']['configuration']['seed'] = 8
    with pytest.raises(ValueError): registry.verify_export(export)
    (path / '000002.json').write_bytes(b'{')
    with pytest.raises(ValueError): registry.history(path)
    with pytest.raises(ValueError): registry.append(path, spec)
    assert (path / '000002.json').read_bytes() == b'{'


def test_file_check_rehashes_and_does_not_claim_authenticity(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    registry.append(path, spec)
    assert registry.check_files(path, spec)['state'] == 'MATCH'
    (tmp_path / 'input.json').write_text('changed')
    assert registry.check_files(path, spec)['state'] == 'CHANGED'
    report = registry.verify_export(registry.export_registry(path))
    assert report['files_checked'] is False
    assert report['authenticity_verified'] is False


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'laboratorio.experiment_registry', *map(str, args)], env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}, capture_output=True, text=True, timeout=10)


def test_cli_real_roundtrip_and_no_overwrite(tmp_path):
    spec = fixture_spec(tmp_path)
    source = tmp_path.resolve() / 'spec.json'
    source.write_text(json.dumps(spec))
    path = tmp_path.resolve() / 'registry'
    target = tmp_path.resolve() / 'export.json'
    for args in [('init', path), ('append', path, '--spec', source), ('show', path), ('export', path, '--out', target), ('verify', target), ('check', path, '--spec', source)]:
        result = cli(*args)
        assert result.returncode == 0, result.stderr
        assert isinstance(json.loads(result.stdout), dict)
    original = target.read_bytes()
    assert cli('export', path, '--out', target).returncode == 2
    assert target.read_bytes() == original


@pytest.mark.parametrize('payload', ['{', '{"x":1,"x":2}', '{"x":NaN}', '[' * 1000, '{"x":1e999}'])
def test_cli_malformed_json_and_special_spec(tmp_path, payload):
    path = tmp_path.resolve() / 'registry'
    assert cli('init', path).returncode == 0
    source = tmp_path.resolve() / 'spec.json'
    source.write_text(payload)
    result = cli('append', path, '--spec', source)
    assert result.returncode == 2
    assert 'Traceback' not in result.stderr
    assert list(path.iterdir()) == []
    source.unlink()
    os.mkfifo(source)
    assert cli('append', path, '--spec', source).returncode == 2


@pytest.mark.parametrize('kind', ['oversize', 'hardlink', 'directory', 'symlink_parent', 'credential_content'])
def test_inadmissible_artifacts_record_invalid_without_hash(tmp_path, kind):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    artifact = tmp_path.resolve() / 'input.json'
    if kind == 'oversize': artifact.write_bytes(b'x' * (registry.MAX_FILE + 1))
    if kind == 'hardlink': os.link(artifact, tmp_path / 'hardlink')
    if kind == 'directory':
        artifact.unlink()
        artifact.mkdir()
    if kind == 'symlink_parent':
        (tmp_path / 'alias').symlink_to(tmp_path, target_is_directory=True)
        spec['inputs'][0]['path'] = str(tmp_path.resolve() / 'alias' / 'input.json')
    if kind == 'credential_content': artifact.write_text('-----BEGIN PRIVATE KEY-----\nsynthetic only')
    result = registry.append(path, spec)['manifest']
    assert result['state'] == 'INVALID'
    assert result['artifacts']['inputs'][0]['sha256'] is None
    assert result['artifacts']['inputs'][0]['size'] is None


def test_empty_results_are_missing_not_success(tmp_path):
    spec = fixture_spec(tmp_path)
    spec['results'] = []
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    assert registry.append(path, spec)['manifest']['state'] == 'MISSING'
    assert registry.check_files(path, spec)['state'] == 'MISSING'


def test_publish_failure_cleans_only_own_staging(tmp_path, monkeypatch):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    before = registry.append(path, spec)
    def fail(*args, **kwargs):
        raise OSError('synthetic link failure')
    monkeypatch.setattr(registry.os, 'link', fail)
    with pytest.raises(OSError): registry.append(path, spec)
    assert registry.history(path) == [before]
    assert sorted(p.name for p in path.iterdir()) == ['000001.json']


def test_interrupted_staging_is_visible_and_never_cleaned_by_reader(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    registry.append(path, spec)
    pending = path / '.pending-interrupted'
    pending.write_bytes(b'partial')
    with pytest.raises(ValueError): registry.history(path)
    with pytest.raises(ValueError): registry.append(path, spec)
    assert pending.read_bytes() == b'partial'


def test_concurrent_stale_writer_cannot_replace_committed_record(tmp_path, monkeypatch):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    publish = registry._publish
    def interleaved(fd, name, data):
        monkeypatch.setattr(registry, '_publish', publish)
        registry.append(path, spec)
        return publish(fd, name, data)
    monkeypatch.setattr(registry, '_publish', interleaved)
    with pytest.raises(FileExistsError): registry.append(path, spec)
    assert len(registry.history(path)) == 1
    assert sorted(p.name for p in path.iterdir()) == ['000001.json']


@pytest.mark.parametrize('field,value', [('version', True), ('state', 'PASS'), ('source', 'untrusted'), ('recorded_at', '2026-02-31T00:00:00Z')])
def test_recomputed_digest_does_not_bypass_schema(tmp_path, field, value):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    registry.append(path, spec)
    export = registry.export_registry(path)
    record = export['records'][0]
    record['manifest'][field] = value
    record['sha256'] = hashlib.sha256(registry.canonical(record['manifest'])).hexdigest()
    export['head_sha256'] = record['sha256']
    with pytest.raises(ValueError): registry.verify_export(export)


def test_limits_persist_across_reopen(tmp_path, monkeypatch):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    monkeypatch.setattr(registry, 'MAX_VERSIONS', 2)
    registry.append(path, spec)
    registry.append(path, spec)
    with pytest.raises(ValueError): registry.append(path, spec)
    assert len(registry.history(path)) == 2


def test_configuration_depth_must_roundtrip_export(tmp_path):
    spec = fixture_spec(tmp_path)
    config = {}
    spec['configuration'] = config
    for _ in range(9):
        config['nested'] = {}
        config = config['nested']
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    try:
        registry.append(path, spec)
    except ValueError:
        assert registry.history(path) == []
    else:
        exported = registry.export_registry(path)
        assert registry.verify_export(registry.strict_json(registry.canonical(exported), registry.MAX_EXPORT))['integrity'] == 'VALID'


def test_truncation_detected_against_operator_saved_head(tmp_path):
    spec = fixture_spec(tmp_path)
    path = tmp_path.resolve() / 'registry'
    registry.initialize(path)
    registry.append(path, spec)
    head = registry.append(path, spec)['sha256']
    exported = registry.export_registry(path)
    assert registry.verify_export(exported, expected_head=head)['integrity'] == 'VALID'
    exported['records'].pop()
    exported['head_sha256'] = exported['records'][0]['sha256']
    with pytest.raises(ValueError): registry.verify_export(exported, expected_head=head)
