import json
import os
from pathlib import Path
import tempfile
import unittest

from laboratorio.web_store import Store, AppError


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / 'app'
        self.store = Store(self.root)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_evaluation_reopen_export_integrity(self):
        cases = self.store.catalog({'seed': 17, 'per_family': 2})['cases']
        item = self.store.evaluate({'name': 'Prueba', 'cases': cases,
            'responses': [{'id': c['id'], 'answer': c['expected']} for c in cases]})
        self.assertEqual(item['result']['accuracy'], 1)
        identifier = item['id']
        self.assertEqual(self.store.verify_experiment({'id': identifier})['files']['state'], 'MATCH')
        exported = self.store.export('experiment', identifier)
        self.assertEqual(exported['records'][0]['manifest']['state'], 'AVAILABLE')
        self.assertNotIn(str(self.root), json.dumps(exported))
        self.store.close()
        self.store = Store(self.root)
        self.assertEqual(self.store.state()['evaluations'], [item])
        (self.root / 'evaluations' / identifier / 'cases.json').write_text('[]')
        self.assertEqual(self.store.verify_experiment({'id': identifier})['files']['state'], 'CHANGED')
        self.assertTrue(self.store.state()['warnings'])

    def test_evidence(self):
        item = self.store.evidence({'title': 'Documento', 'url': 'https://example.org/doc',
            'source_kind': 'synthetic', 'captured_at': '2026-01-01T00:00:00Z', 'content': 'Texto sintético'})
        self.assertEqual(self.store.verify_evidence({'id': item['id']})['integrity'], 'MATCH')
        self.assertEqual(self.store.export('evidence', item['id'])['integrity'], 'MATCH')
        self.assertEqual(self.store.state()['evidence'], [item])

    def test_forecasts(self):
        f = {'id': 'f1', 'question': 'Caso sintético', 'probability': 0.75,
            'issued_at': '2025-01-01T00:00:00Z', 'resolve_at': '2025-01-02T00:00:00Z',
            'resolution_rule': 'Resultado binario sintético'}
        self.store.forecast({'forecast': f})
        self.assertIsNone(self.store.state()['forecasts']['score']['brier'])
        with self.assertRaises(AppError): self.store.forecast({'forecast': f})
        r = {'id': 'f1', 'outcome': True, 'resolved_at': '2025-01-03T00:00:00Z', 'evidence_url': 'https://example.org/result'}
        self.store.resolve({'resolution': r})
        with self.assertRaises(AppError): self.store.resolve({'resolution': r})
        self.assertEqual(self.store.state()['forecasts']['score']['brier'], 0.0625)

    def test_boundaries_and_invalid_no_success(self):
        for data in ({'name': 'x', 'cases': [], 'responses': []},
                     {'name': '/private/secret', 'cases': [], 'responses': []}):
            with self.assertRaises(AppError): self.store.evaluate(data)
        self.assertEqual(self.store.state()['evaluations'], [])
        for identifier in ('../x', 'A' * 32, '0' * 32):
            with self.assertRaises(AppError): self.store.export('evaluation', identifier)
        for i in range(100): (self.root / 'demos' / f'{i:032x}').mkdir(mode=0o700)
        with self.assertRaises(AppError) as raised: self.store.demo({})
        self.assertEqual(raised.exception.status, 413)
        self.assertTrue(self.store.state()['warnings'])

    def test_exclusive_private_symlink_hardlink(self):
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        with self.assertRaises((AppError, ValueError, OSError)): Store(self.root)
        self.store.close()
        lock = self.root / '.lock'
        os.link(lock, self.root.parent / 'alias')
        with self.assertRaises((AppError, ValueError, OSError)): Store(self.root)
        os.unlink(self.root.parent / 'alias')
        alias = self.root.parent / 'link'
        alias.symlink_to(self.root)
        with self.assertRaises((AppError, ValueError, OSError)): Store(alias)
        self.store = Store(self.root)

    def test_invalid_limits_and_corruption(self):
        for value in (float('nan'), float('inf'), True):
            with self.assertRaises(AppError): self.store.catalog({'seed': value, 'per_family': 1})
        with self.assertRaises(AppError) as error:
            self.store.evidence({'title': 'Texto', 'url': 'https://example.org', 'source_kind': 'synthetic',
                'captured_at': '2026-01-01T00:00:00Z', 'content': 'a' * 1048577})
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(self.store.state()['evidence'], [])
        (self.root / 'forecasts' / '00000000.json').write_text('{}')
        state = self.store.state()
        self.assertTrue(state['warnings'])
        self.assertIsNone(state['forecasts']['score'])

    def test_nested_workspace_and_forecast_slots(self):
        with Store(self.root.parent / 'nested' / 'app') as nested:
            self.assertEqual(nested.state()['warnings'], [])
        for index in range(100):
            self.store.forecast({'forecast': {'id': f'f{index}', 'question': 'Sintético',
                'probability': 0.5, 'issued_at': '2025-01-01T00:00:00Z',
                'resolve_at': '2025-01-02T00:00:00Z', 'resolution_rule': 'Binario'}})
        with self.assertRaises(AppError) as error:
            self.store.forecast({'forecast': {'id': 'excess', 'question': 'Sintético',
                'probability': 0.5, 'issued_at': '2025-01-01T00:00:00Z',
                'resolve_at': '2025-01-02T00:00:00Z', 'resolution_rule': 'Binario'}})
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(len(self.store.state()['forecasts']['forecasts']), 100)

    def test_demo_real(self):
        result = self.store.demo({})
        self.assertEqual(result['result']['status'], 'PASS')
        self.assertEqual(result['result']['final_event']['version'], 1)
        self.assertFalse(result['result']['C1_T02_verified'])
        self.assertEqual(self.store.export('demo', result['id']), result)


if __name__ == '__main__': unittest.main()
