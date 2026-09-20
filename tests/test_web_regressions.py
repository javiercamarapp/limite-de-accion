import io
import json
from email.message import Message
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from laboratorio import evaluation, web_store
from laboratorio.web_store import Store, AppError
from laboratorio.web_app import Handler


class WebRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='/private/tmp')
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'app')
        self.addCleanup(lambda: self.store.close())

    def cases(self, expected=1):
        return [{'id': 'c', 'domain': 'fixture', 'prompt': 'Synthetic',
                 'expected': expected, 'method': 'numeric', 'tolerance': 0}]

    def create(self):
        return self.store.evaluate({'name': 'fixture', 'cases': self.cases(),
                                    'responses': [{'id': 'c', 'answer': 1}]})

    def raw(self, responses, cases=None):
        return self.store.evaluate({'name': 'raw', 'cases_json': cases or json.dumps(self.cases()),
                                    'responses_json': responses})

    def test_raw_precision_and_export(self):
        big = 100000000000000000001
        item = self.raw('[{"id":"c","answer":100000000000000000001}]',
                        json.dumps(self.cases(big)))
        self.assertEqual(item['result']['correct'], 1)
        exported = self.store.export('evaluation', item['id'])
        self.assertEqual(exported['responses'][0]['answer'], big)
        self.assertEqual(exported['result'], evaluation.evaluate(exported['cases'], exported['responses']))
        different = self.raw('[{"id":"c","answer":100000000000000000001}]',
                             json.dumps(self.cases(1e20)))
        self.assertEqual(different['result']['correct'], 0)
        h = Handler.__new__(Handler)
        h.path = '/api/export?kind=evaluation&id=' + item['id']
        h.command = 'GET'
        h.headers = Message()
        h.headers['Host'] = '127.0.0.1:8765'
        h.headers['X-App-Token'] = 'fixture'
        h.server = SimpleNamespace(store=self.store, host='127.0.0.1:8765', token='fixture')
        h.send_response = lambda status: self.assertEqual(status, 200)
        h.send_header = lambda *args: None
        h.end_headers = lambda: None
        h.wfile = io.BytesIO()
        h._run()
        self.assertIn(str(big).encode(), h.wfile.getvalue())
        self.assertTrue(json.loads(h.wfile.getvalue())['ok'])

    def test_raw_invalid_creates_nothing_and_contract_is_exact(self):
        for answer in ('NaN', 'Infinity', '-Infinity', '1e400'):
            with self.subTest(answer=answer), self.assertRaises(AppError):
                self.raw('[{"id":"c","answer":' + answer + '}]')
        with self.assertRaises(AppError):
            self.raw('[{"id":"c","answer":0,"answer":1}]')
        with self.assertRaises(AppError):
            self.raw('[]', '[{"id":"c","id":"d"}]')
        valid = {'name': 'raw', 'cases_json': json.dumps(self.cases()), 'responses_json': '[]'}
        for extra in ({'cases': self.cases()}, {'unknown': 1}, {'responses_json': []}):
            with self.assertRaises(AppError): self.store.evaluate(valid | extra)
        self.assertEqual(list((self.store.root / 'evaluations').iterdir()), [])
        self.assertEqual(self.create()['result']['correct'], 1)

    def test_http_raw_contract_and_invalid_inputs(self):
        valid = {'name': 'raw HTTP', 'cases_json': json.dumps(self.cases(100000000000000000001)),
                 'responses_json': '[{"id":"c","answer":100000000000000000001}]'}
        def post(body):
            h = Handler.__new__(Handler)
            h.path, h.command = '/api/evaluations', 'POST'
            h.headers = Message()
            raw = json.dumps(body).encode()
            for key, value in {'Host': '127.0.0.1:8765', 'Origin': 'http://127.0.0.1:8765',
                               'X-App-Token': 'fixture', 'Content-Type': 'application/json',
                               'Content-Length': str(len(raw))}.items(): h.headers[key] = value
            h.server = SimpleNamespace(store=self.store, host='127.0.0.1:8765',
                                       origin='http://127.0.0.1:8765', token='fixture')
            h.rfile, h.wfile = io.BytesIO(raw), io.BytesIO()
            status = []
            h.send_response = status.append
            h.send_header = lambda *args: None
            h.end_headers = lambda: None
            h._run()
            return status[0], json.loads(h.wfile.getvalue())
        for answer in ('NaN', 'Infinity', '-Infinity', '1e400', '1,"answer":2'):
            code, result = post(valid | {'responses_json': '[{"id":"c","answer":' + answer + '}]'})
            self.assertEqual(code, 400)
            self.assertFalse(result['ok'])
        self.assertEqual(list((self.store.root / 'evaluations').iterdir()), [])
        code, result = post(valid)
        self.assertEqual(code, 200)
        self.assertEqual(result['result']['result']['correct'], 1)
        for extra in ({'cases': self.cases()}, {'unknown': 1}):
            self.assertEqual(post(valid | extra)[0], 400)

    def test_json_type_corruption(self):
        for field, value in [('total', True), ('authorizes_actions', 0), ('correct', True), ('row', 1)]:
            item = self.create()
            if field == 'row': item['result']['rows'][0]['correct'] = value
            else: item['result'][field] = value
            path = self.store.root / 'evaluations' / item['id'] / 'item.json'
            path.write_text(json.dumps(item))
            with self.assertRaises(AppError): self.store.export('evaluation', item['id'])
        state = self.store.state()
        self.assertEqual(state['evaluations'], [])
        self.assertEqual(state['experiments'], [])
        self.assertTrue(state['warnings'])

    def test_workspace_and_evidence_types(self):
        item = self.store.evidence({'title': 'Fixture', 'url': 'https://example.org',
            'source_kind': 'synthetic', 'captured_at': '2020-01-01T00:00:00Z', 'content': 'Fixture'})
        item['source_count'] = True
        (self.store.root / 'evidence' / item['id'] / 'item.json').write_text(json.dumps(item))
        with self.assertRaises(AppError): self.store.export('evidence', item['id'])
        root = self.store.root
        self.store.close()
        (root / 'workspace.json').write_text('{"version":true}')
        with self.assertRaises(AppError): Store(root)

    def test_mutation_during_verification_aborts(self):
        item = self.create()
        path = self.store.root / 'evaluations' / item['id'] / 'responses.json'
        real = self.store.verify_experiment
        def changed(data):
            report = real(data)
            path.write_text('[]')
            return report
        with patch.object(self.store, 'verify_experiment', side_effect=changed):
            with self.assertRaises(AppError): self.store.export('evaluation', item['id'])
        self.assertEqual(path.read_text(), '[]')

    def test_observed_changed_never_available(self):
        item = self.create()
        real = self.store.verify_experiment
        def changed(data):
            report = real(data)
            (self.store.root / 'evaluations' / item['id'] / 'evaluator.py').write_text('# changed')
            return report
        with patch.object(self.store, 'verify_experiment', side_effect=changed):
            state = self.store.state()
        self.assertEqual(state['evaluations'], [])
        self.assertEqual(state['experiments'], [])
        self.assertTrue(state['warnings'])

    def test_multiline_persists_and_privacy(self):
        f = {'id': 'f', 'question': 'Synthetic', 'probability': .5,
             'issued_at': '2020-01-01T00:00:00Z', 'resolve_at': '2020-01-02T00:00:00Z',
             'resolution_rule': 'Primera condición\nSegunda\r\nTercera\tcondición'}
        self.store.forecast({'forecast': f})
        root = self.store.root
        self.store.close()
        self.store = Store(root)
        self.assertEqual(self.store.state()['forecasts']['forecasts'][0]['forecast'], f)
        for rule in ('text\x00bad', 'text\x1fbad', 'text\x7fbad', 'text\n/private/secret'):
            with self.assertRaises(AppError):
                self.store.forecast({'forecast': f | {'id': 'bad', 'resolution_rule': rule}})

    def test_ledger_mutation_does_not_mix_rows_and_score(self):
        self.store.forecast({'forecast': {'id': 'f', 'question': 'Synthetic', 'probability': .5,
             'issued_at': '2020-01-01T00:00:00Z', 'resolve_at': '2020-01-02T00:00:00Z',
             'resolution_rule': 'Synthetic'}})
        real = self.store.ledger.show
        def changed():
            shown = real()
            with self.store._input({'id': 'f', 'outcome': True, 'resolved_at': '2020-01-03T00:00:00Z',
                                    'evidence_url': 'https://example.org'}) as path:
                self.store.ledger.resolve(path)
            return shown
        with patch.object(self.store.ledger, 'show', side_effect=changed):
            state = self.store.state()
        if state['forecasts']['score'] is not None:
            self.assertEqual(state['forecasts']['score']['resolved'], len(state['forecasts']['resolutions']))
        else: self.assertTrue(state['warnings'])

    def test_demo_event_version_type_without_running_demo(self):
        identifier, path = self.store._new('demos')
        result = dict(status='PASS', operation_before_recovery='UNKNOWN',
            operation_after_recovery='CONFIRMED', revoked_operation='REJECTED',
            recovery_transport_calls=['execute', 'get_receipt'],
            all_controller_transport_calls=['execute', 'get_receipt', 'execute'],
            synthetic_data=True, synthetic_clock=True, injected_response_loss=True,
            separate_os_identities=False, human_approval_performed=False,
            C1_T02_verified=False, external_effects=False,
            final_event={'calendar_id': 'demo_calendar', 'event_id': 'demo_event',
                'start_utc': '2026-09-20T10:00:00Z', 'end_utc': '2026-09-20T10:30:00Z',
                'title': 'SYNTHETIC EVENT', 'version': 1})
        item = {'id': identifier, 'created_at': '2020-01-01T00:00:00Z', 'result': result}
        web_store.write_json(path / 'item.json', item)
        self.assertEqual(self.store.export('demo', identifier), item)
        result['final_event']['version'] = True
        (path / 'item.json').write_text(json.dumps(item))
        with self.assertRaises(AppError): self.store.export('demo', identifier)

    def test_export_keeps_validated_reads_and_hashes(self):
        item = self.create()
        real = self.store._snapshot
        def after_validation(kind, identifier):
            snapshot = real(kind, identifier)
            (self.store.root / kind / identifier / 'responses.json').write_text('[]')
            return snapshot
        with patch.object(self.store, '_snapshot', side_effect=after_validation):
            exported = self.store.export('evaluation', item['id'])
        self.assertEqual(exported['responses'], [{'id': 'c', 'answer': 1}])
        self.assertEqual(exported['result'], evaluation.evaluate(exported['cases'], exported['responses']))

    def test_incomplete_snapshot_is_controlled_and_preserved(self):
        item = self.create()
        path = self.store.root / 'evaluations' / item['id']
        (path / 'responses.json').unlink()
        before = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
        with self.assertRaises(AppError): self.store.export('evaluation', item['id'])
        state = self.store.state()
        self.assertEqual(state['evaluations'], [])
        self.assertTrue(state['warnings'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()})

    def test_frontend_raw_payload_safe_generator_and_blob(self):
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const nodes = new Map();
class Element {
 constructor(tag='div') {this.tagName=tag;this.children=[];this.attrs={};this.listeners={};this.value='';this.disabled=false;this.classList={toggle(){},remove(){},contains(){return false;}};}
 setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')nodes.set(v,this);}
 getAttribute(k){return this.attrs[k];} removeAttribute(k){delete this.attrs[k];}
 append(...v){this.children.push(...v);} replaceChildren(...v){this.children=v;}
 addEventListener(k,v){this.listeners[k]=v;}
 querySelector(selector){return walk(this).find(n=>n.tagName===selector);}
 matches(){return false;} focus(){} scrollIntoView(){} remove(){} click(){}
}
function walk(n){return [n,...n.children.flatMap(c=>c instanceof Element?walk(c):[])];}
global.Node=Element;global.FormData=class {};
for(const id of ['view','main','notification','warnings','connection','breadcrumb','refresh','menu-toggle','navigation','skip-link'])nodes.set(id,new Element());
global.document={getElementById:id=>nodes.get(id),createElement:t=>new Element(t),createTextNode:v=>({textContent:v}),querySelectorAll:()=>[],addEventListener(){},body:new Element()};
global.location={hash:'#evaluaciones'};global.window={addEventListener(){},scrollTo(){}};
let source=fs.readFileSync(process.argv[1],'utf8');
source=source.replace("  run($('refresh'),async()=>{try{await refresh(true);}catch(error){render();throw error;}});", "  globalThis.testApp={evaluations,download,setState:value=>state=value};");
vm.runInThisContext(source);
testApp.setState({evaluations:[]});
const page=testApp.evaluations();
const all=page.filter(Boolean).flatMap(walk);
const byLabel=label=>all.find(n=>n.tagName==='button' && n.children.some(c=>c.textContent===label));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const requests=[];
global.fetch=async (path,options)=>{requests.push({path,body:JSON.parse(options.body)});return {ok:false,status:400,json:async()=>({ok:false,error:{message:'fixture'}})};};
(async()=>{
 const cases=' [ {"id":"c","expected":100000000000000000001} ] ';
 for(const responses of ['[{"id":"c","answer":100000000000000000001}]','[{"id":"c","answer":0,"answer":1}]','[{"id":"c","answer":1e400}]','[{"id":"c","answer":NaN}]']) {
  nodes.get('cases').value=cases; nodes.get('responses').value=responses; nodes.get('evaluation-name').value='fixture';
  nodes.get('evaluation-form').listeners.submit({preventDefault(){}}); await tick();
  assert.deepStrictEqual(requests.at(-1),{path:'/api/evaluations',body:{name:'fixture',cases_json:cases,responses_json:responses}});
 }
 for(const [id,other] of [['seed','per-family'],['per-family','seed']]) {
  for(const value of ['9007199254740993','1e400','1.5']) {
   nodes.get(id).value=value;nodes.get(other).value='1';const before=requests.length;
   byLabel('Generar catálogo').listeners.click();await tick();assert.strictEqual(requests.length,before);
  }
 }
 const before=requests.length;byLabel('Ejemplo sintético').listeners.click();await tick();assert.strictEqual(requests.length,before);
 const fixture=[{id:'fixture',expected:1},{id:'fixture2',expected:2}];
 global.fetch=async()=>({ok:true,status:200,json:async()=>({ok:true,result:{cases:fixture}})});
 nodes.get('seed').value='17';nodes.get('per-family').value='1';
 byLabel('Generar catálogo').listeners.click();await tick();byLabel('Ejemplo sintético').listeners.click();await tick();
 assert.deepStrictEqual(JSON.parse(nodes.get('responses').value),[{id:'fixture',answer:2}]);
 nodes.get('cases').value=cases;nodes.get('responses').value='unchanged';
 byLabel('Ejemplo sintético').listeners.click();await tick();assert.strictEqual(nodes.get('responses').value,'unchanged');
 const bytes=Buffer.from('{"ok":true,"result":{"answer":100000000000000000001}}');
 const blob=new Blob([bytes]);let captured;
 global.fetch=async()=>({ok:true,blob:async()=>blob,json:async()=>{throw Error('Download must not parse JSON');}});
 global.URL={createObjectURL:b=>{captured=b;return 'blob:fixture';},revokeObjectURL(){}};
 global.setTimeout=fn=>fn();await testApp.download('evaluation','fixture');
 assert.strictEqual(captured,blob);assert.deepStrictEqual(Buffer.from(await captured.arrayBuffer()),bytes);
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script, 'src/laboratorio/web_assets/app.js'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__': unittest.main()
