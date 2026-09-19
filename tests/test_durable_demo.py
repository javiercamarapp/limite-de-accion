"""A real CLI/socket/SQLite round trip, with explicitly synthetic identity."""
import json
from pathlib import Path
import tempfile

from test_cli import cli, ROOT


def test_cli_durable_control_recovers_without_replay():
    with tempfile.TemporaryDirectory(prefix='.durable-demo-test-', dir=ROOT) as directory:
        out = Path(directory) / 'run'
        result = cli('demo-durable-control', '--out', out)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['status'] == 'PASS'
        assert report['operation_before_recovery'] == 'UNKNOWN'
        assert report['operation_after_recovery'] == 'CONFIRMED'
        assert report['recovery_transport_calls'] == ['execute', 'get_receipt']
        assert report['final_event']['version'] == 1
        assert report['revoked_operation'] == 'REJECTED'
        assert report['C1_T02_verified'] is False
        assert report['separate_os_identities'] is False
        assert report['human_approval_performed'] is False
        assert report['injected_response_loss'] is True
        assert json.loads((out / 'report.json').read_text()) == report
        assert json.loads((out / 'controller-export.json').read_text())['operations'][0]['status'] == 'CONFIRMED'
        assert not list(out.glob('*.sock'))
        # A second invocation must not overwrite a previous run or its database.
        before = (out / 'report.json').read_bytes()
        repeat = cli('demo-durable-control', '--out', out)
        assert repeat.returncode != 0
        assert (out / 'report.json').read_bytes() == before
