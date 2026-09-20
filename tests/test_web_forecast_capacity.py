"""Admission must never turn successful writes into an unreadable web ledger."""
from pathlib import Path
import hashlib

import pytest
from laboratorio.web_store import Store, AppError


def forecast(i, long=False):
    return {'id': f'f{i}', 'question': 'q' * (4096 if long else 16),
            'probability': .5, 'issued_at': '2020-01-01T00:00:00Z',
            'resolve_at': '2020-01-02T00:00:00Z',
            'resolution_rule': 'r' * (4096 if long else 16)}


def resolution(i, url='https://example.org/result'):
    return {'id': f'f{i}', 'outcome': False, 'resolved_at': '2020-01-03T00:00:00Z', 'evidence_url': url}


def snapshot(root):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.iterdir()}


def test_admission_reserves_resolution_room_and_never_hides_accepted(tmp_path):
    with Store(tmp_path.resolve() / 'app') as store:
        accepted = 0
        for i in range(100):
            before = snapshot(store.root / 'forecasts')
            try:
                store.forecast({'forecast': forecast(i, True)})
            except AppError as error:
                assert error.status == 413
                assert snapshot(store.root / 'forecasts') == before
                break
            accepted += 1
            state = store.state()
            assert len(state['forecasts']['forecasts']) == accepted
            assert state['forecasts']['score'] is not None
            assert not any(w['component'] == 'forecasts' for w in state['warnings'])
        assert 0 < accepted < 100
        for i in range(accepted):
            store.resolve({'resolution': resolution(i, 'https://example.org/' + 'a' * 2028)})
        state = store.state()
        assert state['forecasts']['score']['resolved'] == accepted
        assert not state['warnings']
    with Store(tmp_path.resolve() / 'app') as reopened:
        assert reopened.state()['forecasts']['score']['resolved'] == accepted


def test_one_hundred_short_forecasts_remain_resolvable(tmp_path):
    with Store(tmp_path.resolve() / 'app') as store:
        for i in range(100):store.forecast({'forecast': forecast(i)})
        for i in range(100):store.resolve({'resolution': resolution(i)})
        state = store.state()
        assert len(state['forecasts']['forecasts']) == 100
        assert state['forecasts']['score']['resolved'] == 100
        assert state['forecasts']['score']['pending'] == 0
        assert not state['warnings']


def test_old_valid_84_long_records_still_visible_and_resolvable(tmp_path):
    with Store(tmp_path.resolve() / 'app') as store:
        # Reproduce the old API's persisted records without changing its core.
        for i in range(84):
            with store._input(forecast(i, True)) as path:store.ledger.add(path)
        assert len(store.state()['forecasts']['forecasts']) == 84
        store.resolve({'resolution': resolution(0)})
        assert store.state()['forecasts']['score']['resolved'] == 1


def test_resolution_utf8_byte_limit_is_checked_before_writing(tmp_path):
    with Store(tmp_path.resolve() / 'app') as store:
        store.forecast({'forecast': forecast(0)})
        before = snapshot(store.root / 'forecasts')
        with pytest.raises(AppError):store.resolve({'resolution': resolution(0, 'https://example.org/' + 'é' * 1500)})
        assert snapshot(store.root / 'forecasts') == before
