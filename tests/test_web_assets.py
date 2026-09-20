"""Asset contract checks without binding sockets or using remote resources."""
import ast
from email.message import Message
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

from laboratorio.web_app import ASSETS, CSP, Handler
from laboratorio.web_store import Store

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / 'src/laboratorio/web_assets'


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.tags = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class WebAssetsTests(unittest.TestCase):
    def test_document_accessibility_and_local_resources(self):
        doc = Document((ASSET_DIR / 'index.html').read_text())
        ids = [a['id'] for _, a in doc.tags if 'id' in a]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(('html', {'lang': 'es'}), doc.tags)
        self.assertTrue(any(t == 'main' and a.get('id') == 'main' for t, a in doc.tags))
        self.assertTrue(any(a.get('aria-live') == 'polite' for _, a in doc.tags))
        self.assertTrue(any(a.get('aria-controls') == 'navigation' and a.get('aria-expanded') == 'false' for _, a in doc.tags))
        for tag, attrs in doc.tags:
            self.assertNotIn('style', attrs)
            self.assertFalse(any(k.startswith('on') for k in attrs))
            for name in ('src', 'href'):
                if name in attrs:
                    self.assertTrue(attrs[name].startswith(('/', '#')))
            if tag == 'script':
                self.assertEqual(attrs['src'], '/app.js')
        for route in ('resumen', 'evaluaciones', 'experimentos', 'pronosticos', 'evidencia', 'control'):
            self.assertTrue(any(a.get('href') == '#' + route for _, a in doc.tags))

    def test_real_handler_serves_all_assets_without_network(self):
        for route, (name, mime) in ASSETS.items():
            handler = Handler.__new__(Handler)
            handler.path, handler.command = route, 'GET'
            handler.headers = Message()
            handler.headers['Host'] = '127.0.0.1:8765'
            handler.server = SimpleNamespace(host='127.0.0.1:8765', token='test-session')
            captured = {}
            handler.send_response = lambda code: captured.update(status=code)
            handler.send_header = lambda key, value: captured.update({key: value})
            handler.end_headers = lambda: None
            handler.wfile = io.BytesIO()
            handler._run()
            self.assertEqual(captured['status'], 200, route)
            self.assertEqual(captured['Content-Type'], mime)
            self.assertEqual(captured['Content-Security-Policy'], CSP)
            self.assertNotIn('unsafe-inline', CSP)
            self.assertEqual(handler.wfile.getvalue(), (ASSET_DIR / name).read_bytes())

    def test_script_security_and_all_api_routes(self):
        source = (ASSET_DIR / 'app.js').read_text()
        for forbidden in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'eval(', 'new Function', 'localStorage', 'sessionStorage', 'console.'):
            self.assertNotIn(forbidden, source)
        for route in ('bootstrap', 'state', 'catalog', 'evaluations', 'experiments/verify', 'forecasts', 'resolutions', 'evidence', 'evidence/verify', 'demo', 'export?kind='):
            self.assertIn('/api/' + route, source)
        self.assertIn("'X-App-Token'", source)
        self.assertIn('response.blob()', source)
        self.assertIn('URL.revokeObjectURL', source)
        self.assertIn('rowLimit = 50', source)
        self.assertIn("new TextDecoder('utf-8',{fatal:true})", source)
        self.assertNotRegex(source, r'/api/(approve|dispatch)')
        subprocess.run(['node', '--check', str(ASSET_DIR / 'app.js')], check=True, capture_output=True, text=True)

    def test_responsive_focus_and_static_svg(self):
        css = (ASSET_DIR / 'style.css').read_text()
        for token in ('prefers-reduced-motion', ':focus-visible', 'max-width:700px', 'overflow:auto', '[hidden]'):
            self.assertIn(token, css)
        self.assertNotIn('@import', css)
        self.assertNotIn('url(', css)
        svg = ET.fromstring((ASSET_DIR / 'icon.svg').read_text())
        for node in svg.iter():
            self.assertNotIn(node.tag.rsplit('}', 1)[-1], ('script', 'foreignObject', 'image'))
            self.assertFalse(any(k.startswith('on') for k in node.attrib))

    def test_all_views_render_actual_backend_shapes_in_node(self):
        # A small DOM contract harness, not a browser/visual QA claim.
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            with Store(Path(temporary) / 'app') as store:
                cases = store.catalog({'seed': 17, 'per_family': 2})['cases']
                item = store.evaluate({'name': '<script>user text</script>', 'cases': cases, 'responses': [{'id': c['id'], 'answer': c['expected']} for c in cases[:-1]]})
                store.forecast({'forecast': {'id': 'historical', 'question': 'Synthetic question', 'probability': .7, 'issued_at': '2020-01-01T00:00:00Z', 'resolve_at': '2020-01-02T00:00:00Z', 'resolution_rule': 'Synthetic rule'}})
                store.evidence({'title': 'Synthetic evidence', 'url': 'https://example.org/synthetic', 'source_kind': 'synthetic', 'captured_at': '2020-01-03T00:00:00Z', 'content': 'Explicit synthetic fixture.'})
                state = store.state()
                reports = {'experiment': store.verify_experiment({'id': item['id']}), 'evidence': store.verify_evidence({'id': state['evidence'][0]['id']})}
        harness = r'''
const fs = require('fs'), vm = require('vm');
const assert = require('assert');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = new Map();
class Element {
 constructor(tag='div') {this.tagName=tag;this.children=[];this.attrs={};this.listeners={};this.value='';this.disabled=false;this.classList={toggle(){},remove(){},contains(){return false;}};}
 setAttribute(k,v){this.attrs[k]=String(v);if(k==='id')nodes.set(v,this);}
 getAttribute(k){return this.attrs[k];}
 removeAttribute(k){delete this.attrs[k];}
 append(...v){this.children.push(...v);}
 replaceChildren(...v){this.children=v;}
 addEventListener(k,v){this.listeners[k]=v;}
 querySelector(selector){return walk(this).find(n=>n.tagName===selector);}
 matches(){return false;}
 focus(){} scrollIntoView(){} remove(){} click(){}
}
function walk(n){return [n,...n.children.flatMap(c=>c instanceof Element?walk(c):[])];}
global.Node=Element;
for(const id of ['view','main','notification','warnings','connection','breadcrumb','refresh','menu-toggle','navigation','skip-link'])nodes.set(id,new Element());
const nav=Object.keys({resumen:1,evaluaciones:1,experimentos:1,pronosticos:1,evidencia:1,control:1}).map(x=>{const a=new Element('a');a.hash='#'+x;return a;});
global.document={getElementById:id=>nodes.get(id),createElement:t=>new Element(t),createTextNode:v=>({textContent:v}),querySelectorAll:s=>s==='#navigation>a'?nav:[],addEventListener(){},body:new Element()};
global.location={hash:'#resumen'};
const events={};global.window={addEventListener:(k,v)=>events[k]=v,scrollTo:(x,y)=>{assert.strictEqual(x,0);assert.strictEqual(y,0);}};
global.fetch=async path=>({ok:true,status:200,json:async()=>({ok:true,result:path==='/api/bootstrap'?{csrf_token:'memory-only'}:fixture.state})});
let source=fs.readFileSync(process.argv[1],'utf8');
// Exercise verifier renderers with reports actually generated by Store.
source=source.replace('function render() {', 'globalThis.checkReports = () => { verifyView('+JSON.stringify(fixture.reports.experiment)+',"experiment"); verifyView('+JSON.stringify(fixture.reports.evidence)+',"evidence"); }; function render() {');
vm.runInThisContext(source);
setImmediate(()=>{
 assert.strictEqual(nodes.get('connection').textContent,'Servicio conectado');
 for(const route of ['resumen','evaluaciones','experimentos','pronosticos','evidencia','control']) {
  location.hash='#'+route;events.hashchange();
  assert(walk(nodes.get('view')).some(n=>n.tagName==='h1'),route);
  for(const node of walk(nodes.get('view')))if(['input','select','textarea'].includes(node.tagName)) {
   assert(walk(nodes.get('view')).some(n=>n.tagName==='label' && n.attrs.for===node.attrs.id),'missing label '+node.attrs.id);
  }
 }
 checkReports();
 console.log('Six views and real verification reports rendered; form labels checked.');
});
'''
        result = subprocess.run(['node', '-e', harness, str(ASSET_DIR / 'app.js')], input=json.dumps({'state': state, 'reports': reports}), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Six views', result.stdout)


if __name__ == '__main__':
    unittest.main()
