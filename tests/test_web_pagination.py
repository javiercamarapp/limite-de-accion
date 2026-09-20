"""Aggregate budgets and explicit paging, without sockets or network."""
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from laboratorio import evaluation, experiment_registry as registry, web_store
from laboratorio.web_app import Handler
from laboratorio.web_store import Store, AppError, LIMITS, write, write_json


class MemoryConnection:
    def __init__(self, raw):
        self.input = io.BytesIO(raw)
        self.output = bytearray()
    def settimeout(self, value): pass
    def makefile(self, *args, **kwargs): return io.BytesIO()
    def recv_into(self, buffer): return self.input.readinto(buffer)
    def sendall(self, data): self.output.extend(data)


class PaginationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / 'app')
        self.addCleanup(self.store.close)

    def data(self):
        return {'name': 'fixture', 'cases': [{'id': 'c', 'domain': 'd', 'prompt': 'p',
                'expected': 1, 'method': 'exact_json'}], 'responses': []}

    def measured(self, offset=0):
        count = [0]
        real = os.read
        def read(fd, size):
            raw = real(fd, size)
            count[0] += len(raw)
            return raw
        with patch('os.read', side_effect=read):
            result = self.store.state(offset)
        self.assertLessEqual(count[0], LIMITS['max_state_read_bytes'])
        size = web_store.json_size({'ok': True, 'result': result})
        self.assertLessEqual(size, LIMITS['max_state_json_bytes'])
        return result, count[0]

    def test_all_100_jobs_stable_global_pages(self):
        ids = []
        for i in range(100):
            if i % 5 == 0:
                item = self.store.evidence({'title': 'fixture', 'url': 'https://example.org',
                    'source_kind': 'synthetic', 'captured_at': '2020-01-01T00:00:00Z', 'content': 'synthetic'})
                kind = 'evidence'
            else:
                item = self.store.evaluate(self.data())
                kind = 'evaluations'
            ids.append(item['id'])
            # Deliberate mtime ties exercise the ID tiebreaker.
            os.utime(self.store.root / kind / item['id'], ns=(123456789, 123456789))
        offset, seen = 0, []
        while offset is not None:
            page, _ = self.measured(offset)
            current = [x['id'] for kind in web_store.KINDS for x in page[kind]]
            self.assertEqual(len(current), 20)
            self.assertEqual(page['pagination']['total_jobs'], 100)
            self.assertEqual(page['totals'], {'evaluations':80, 'experiments':80, 'evidence':20, 'demos':0})
            self.assertEqual(set(current), set(sorted(ids)[offset:offset + 20]))
            seen.extend(current)
            offset = page['pagination']['next_offset']
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(set(seen), set(ids))
        self.assertEqual(self.store.state(300)['pagination']['next_offset'], None)

    def legacy_job(self, domain):
        # A legitimate pre-metadata-limit fixture, with real registry hashes.
        data = self.data()
        data['cases'][0]['domain'] = domain
        result = evaluation.evaluate(data['cases'], data['responses'])
        identifier, path = self.store._new('evaluations')
        for name, value in [('cases', data['cases']), ('responses', []), ('result', result)]:
            write_json(path / (name + '.json'), value)
        write(path / 'evaluator.py', registry.read_file(Path(evaluation.__file__).absolute(), 2_000_000))
        registry.initialize(path / 'registry')
        registry.append(path / 'registry', self.store._spec(identifier, path))
        write_json(path / 'item.json', {'id': identifier, 'name': 'legacy', 'created_at': web_store.now(), 'result': result})
        return identifier

    def test_large_legacy_jobs_reserve_before_snapshot(self):
        ids = {self.legacy_job('D' * 990000) for _ in range(4)}
        offset, seen, measurements = 0, set(), []
        while offset is not None:
            with patch.object(self.store, '_snapshot', wraps=self.store._snapshot) as snapshot:
                page, read_bytes = self.measured(offset)
            self.assertLessEqual(snapshot.call_count, 1)
            self.assertEqual(page['pagination']['returned_jobs'], 1)
            measurements.append(read_bytes)
            seen.update(x['id'] for x in page['evaluations'])
            offset = page['pagination']['next_offset']
            if offset is not None:
                self.assertIn('PAGE_BUDGET', [w['code'] for w in page['warnings']])
        self.assertEqual(ids, seen)
        print('legacy paging bytes per response:', measurements)

    def test_huge_partial_job_skipped_without_payload_read(self):
        identifier, path = self.store._new('evaluations')
        write(path / 'item.json', b'x' * 2_000_001)
        valid = self.store.evaluate(self.data())
        with patch.object(self.store, '_snapshot', wraps=self.store._snapshot) as snapshot:
            state, _ = self.measured()
        self.assertEqual(snapshot.call_count, 1)
        self.assertEqual([x['id'] for x in state['evaluations']], [valid['id']])
        self.assertEqual(state['totals']['evaluations'], 2)
        self.assertIn({'code':'JOB_TOO_LARGE','component':'evaluations','id':identifier}, state['warnings'])
        self.assertIsNone(state['pagination']['next_offset'])

    def test_metadata_rejected_before_slot_and_numbers_unchanged(self):
        for key, size in [('id',129), ('domain',129), ('prompt',4097), ('domain',990000)]:
            data = self.data()
            data['cases'][0][key] = 'x' * size
            with patch.object(self.store, '_new', wraps=self.store._new) as slot:
                with self.assertRaises(AppError): self.store.evaluate(data)
                slot.assert_not_called()
        data = self.data()
        data['cases'][0]['expected'] = 100000000000000000001
        data['responses'] = [{'id':'c','answer':100000000000000000001}]
        self.assertEqual(self.store.evaluate(data)['result']['correct'], 1)

    def test_ledger_preflight_before_show(self):
        write(self.store.root / 'forecasts' / '00000001.json', b'x' * 32769)
        with patch.object(self.store.ledger, 'show', side_effect=AssertionError('payload read')):
            state = self.store.state()
        self.assertIn({'code':'LEDGER_LIMIT','component':'forecasts'}, state['warnings'])
        self.assertIsNone(state['forecasts']['score'])

    def test_http_query_contract_in_memory(self):
        server = SimpleNamespace(store=self.store, host='127.0.0.1:12345', token='session')
        valid = ['', '?offset=0', '?offset=20', '?offset=300']
        invalid = ['?', '?offset=-1', '?offset=301', '?offset=1.0', '?offset=01', '?offset=+1',
                   '?offset=1&offset=2', '?offset=0&token=session', '?token=session', '?offset=%31',
                   '?offset=0&x=1', '?offset=', '?offset=true', '?offset=1#x']
        for query in valid + invalid:
            with self.subTest(query=query):
                raw = (f'GET /api/state{query} HTTP/1.1\r\nHost: {server.host}\r\n'
                       'X-App-Token: session\r\n\r\n').encode()
                conn = MemoryConnection(raw)
                Handler(conn, ('127.0.0.1', 1), server)
                self.assertEqual(int(bytes(conn.output).split(b' ')[1]), 200 if query in valid else 400)
        for offset in (True, -1, 301, '0', 1.5):
            with self.assertRaises(AppError): self.store.state(offset)

    def test_partial_and_symlink_warn_without_claiming_validation(self):
        partial, _ = self.store._new('evaluations')
        linked, path = self.store._new('evidence')
        os.symlink(self.store.root / 'workspace.json', path / 'item.json')
        with patch.object(self.store, '_snapshot', wraps=self.store._snapshot) as snapshot:
            page, _ = self.measured()
        self.assertEqual(snapshot.call_count, 0)
        self.assertEqual(page['totals']['evaluations'], 1)
        self.assertEqual(page['totals']['evidence'], 1)
        self.assertEqual(page['pagination']['returned_jobs'], 0)
        self.assertEqual({w['id'] for w in page['warnings']}, {partial, linked})
        self.assertIsNone(page['pagination']['next_offset'])

    def test_wire_state_limit_before_sending_success(self):
        server = SimpleNamespace(store=SimpleNamespace(state=lambda **kw: {'huge':'x' * (4 * 1024 * 1024)}),
                                 host='127.0.0.1:12345', token='session')
        conn = MemoryConnection(b'GET /api/state HTTP/1.1\r\nHost: 127.0.0.1:12345\r\nX-App-Token: session\r\n\r\n')
        Handler(conn, ('127.0.0.1', 1), server)
        self.assertEqual(int(bytes(conn.output).split(b' ')[1]), 413)
        self.assertLess(len(conn.output), 4096)

    def test_frontend_explicit_cursor_and_no_fetch_all(self):
        script = Path('src/laboratorio/web_assets/app.js').read_text()
        # Execute the actual cursor refresh/navigation/save functions with mocked UI.
        start = script.index('  async function refresh(')
        end = script.index('  async function run(', start)
        refresh = script[start:end]
        start = script.index('  async function save(')
        save = script[start:script.index('  function button(', start)]
        start = script.index('  function pagination()')
        pagination = script[start:script.index('  function overview()', start)]
        harness = '''let cursor=0, state=null, token='secret', connected=false;
const previousPages=[], calls=[];
const connection=()=>{}, render=()=>{}, notify=()=>{};
const el=(tag,attrs,...children)=>({children});
const button=(label,handler)=>({label,handler});
const api=async(path,body)=>{calls.push([path,body]);return path.startsWith('/api/state')?{pagination:{offset:cursor,next_offset:cursor+20,total_jobs:100,returned_jobs:20}}:{id:'new'};};
''' + refresh + save + pagination + '''
(async()=>{await refresh(); if(calls.length!==1)throw Error('autoload');
await pagination().children[2].handler(); if(cursor!==20||calls.length!==2)throw Error('next');
await pagination().children[0].handler(); if(cursor!==0||calls.length!==3)throw Error('previous');
await pagination().children[2].handler(); await save('/api/evaluations',{},'saved');
if(cursor!==0||previousPages.length!==0||calls.filter(x=>x[0]==='/api/evaluations').length!==1)throw Error('save');
if(calls.length!==6)throw Error('unexpected fetch');})().catch(e=>{console.error(e);process.exit(1)});
'''
        run = subprocess.run(['node', '-e', harness], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
