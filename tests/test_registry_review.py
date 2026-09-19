"""Regression cases from the independent experiment-registry review."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from laboratorio import experiment_registry as registry
from test_experiment_registry import fixture_spec


@pytest.mark.parametrize('config', [{'enabled': True}, {'nested': [{'enabled': True}]}])
def test_check_preserves_json_types(tmp_path, config):
    spec=fixture_spec(tmp_path);spec['configuration']=config
    root=tmp_path.resolve()/'registry';registry.initialize(root);registry.append(root,spec)
    changed=copy.deepcopy(spec)
    if 'enabled' in config:changed['configuration']['enabled']=1
    else:changed['configuration']['nested'][0]['enabled']=1
    with pytest.raises(ValueError):registry.check_files(root,changed)


@pytest.mark.parametrize('bad_path',[None,7,[],{}])
def test_bad_path_type_is_controlled_cli_error(tmp_path,bad_path):
    spec=fixture_spec(tmp_path);spec['inputs'][0]['path']=bad_path
    root=tmp_path.resolve()/'registry';registry.initialize(root)
    source=tmp_path.resolve()/'spec.json';source.write_text(json.dumps(spec))
    with pytest.raises(ValueError):registry.validate_spec(spec)
    env={**os.environ,'PYTHONPATH':str(Path(registry.__file__).resolve().parents[1])}
    result=subprocess.run([sys.executable,'-m','laboratorio.experiment_registry','append',str(root),'--spec',str(source)],capture_output=True,text=True,timeout=5,env=env)
    assert result.returncode==2
    assert json.loads(result.stderr)['operation_completed'] is False
    assert 'Traceback' not in result.stderr
    assert registry.history(root)==[]


@pytest.mark.parametrize('nested',[False,True])
def test_recognized_secret_in_configuration_key_never_persists(tmp_path,nested):
    spec=fixture_spec(tmp_path)
    key='ghp_'+'A'*40
    value={key:'synthetic-placeholder'}
    spec['configuration']={'nested':[value]} if nested else value
    root=tmp_path.resolve()/'registry';registry.initialize(root)
    with pytest.raises(ValueError):registry.append(root,spec)
    assert registry.history(root)==[]
