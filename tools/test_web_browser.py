#!/usr/bin/env python3
"""Chromium acceptance on a NEW private workspace; leaves evidence, closes owned processes.

Requires Playwright and cached Chromium. Example (after uv sync --extra dev):
uv run --with playwright python tools/test_web_browser.py --python .venv/bin/python --out runs/browser-qa-new
The chosen Python must have laboratorio installed (editable OR a clean wheel).
Use a short path under your private project, not world-writable /tmp: the real
Unix demo intentionally rejects untrusted ancestors. The output parent must exist.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from playwright.sync_api import sync_playwright, expect


def start(python, out, sequence):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    logpath = out / f'server-{sequence}.log'
    with logpath.open('w') as log:
        child = subprocess.Popen([python, '-m', 'laboratorio.web_app', '--workspace', str(out / 'workspace'), '--port', '0'],
                                 env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    try:
        for _ in range(200):
            lines = logpath.read_text().splitlines()
            if lines and lines[0].startswith('http://127.0.0.1:'):
                return child, lines[0]
            if child.poll() is not None:raise RuntimeError(logpath.read_text())
            time.sleep(.05)
        raise RuntimeError('Server readiness timeout')
    except BaseException:
        stop(child)
        raise


def stop(child):
    if child.poll() is None:
        child.send_signal(signal.SIGINT)
        try:child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=5)
            raise RuntimeError('Server required forced cleanup')
    if child.returncode != 0:raise RuntimeError(f'Server exit {child.returncode}')


def exercise(page, context, url, out):
    checks = []
    page.goto(url);page.wait_for_load_state('networkidle')
    expect(page.locator('#connection')).to_have_text('Servicio conectado')
    def nav(name):
        page.locator(f'nav a[href="#{name}"]').click()
        expect(page.locator('#breadcrumb')).to_have_text({'resumen':'Resumen','evaluaciones':'Evaluaciones',
            'experimentos':'Experimentos','pronosticos':'Pronósticos','evidencia':'Evidencia','control':'Control'}[name])
    def submit(label, path, status=200):
        with page.expect_response(lambda r:r.url.endswith(path) and r.request.method=='POST') as pending:
            page.get_by_role('button',name=label,exact=True).click()
        response=pending.value
        assert response.status==status,(path,response.status,response.text())
        page.wait_for_load_state('networkidle')
        return response.json()
    def download(name):
        with page.expect_download() as pending:page.get_by_role('button',name='Exportar JSON',exact=True).first.click()
        target=out/name;pending.value.save_as(str(target))
        return json.loads(target.read_text())
    nav('evaluaciones');submit('Generar catálogo','/api/catalog')
    page.get_by_role('button',name='Ejemplo sintético',exact=True).click()
    page.locator('#evaluation-name').fill('Evaluación de humo · 10 casos')
    first=submit('Ejecutar y guardar evaluación','/api/evaluations')['result']
    assert first['result']['correct']==8 and first['result']['missing']==1
    expect(page.get_by_text('8 correctas / 10 casos',exact=True)).to_be_visible()
    assert download('evaluation.json')['result']['id']==first['id']
    checks.append('evaluación real8/10 y exportación')
    cases='[{"id":"precision","domain":"numeric","prompt":"Caso sintético","expected":100000000000000000000,"method":"numeric","tolerance":0}]'
    responses='[{"id":"precision","answer":100000000000000000001}]'
    page.locator('#evaluation-name').fill('Precisión numérica · tolerancia cero')
    page.locator('#cases').fill(cases);page.locator('#responses').fill(responses)
    precise=submit('Ejecutar y guardar evaluación','/api/evaluations')['result']
    assert precise['result']['correct']==0
    exported=download('precision.json')['result']
    assert exported['responses'][0]['answer']==100000000000000000001
    assert exported['cases'][0]['expected']==100000000000000000000
    checks.append('precisión exacta de enteros: formulario, cálculo y descarga')
    for raw in ['[{"id":"precision","answer":0,"answer":100000000000000000001}]',
                '[{"id":"precision","answer":1e400}]']:
        page.locator('#responses').fill(raw)
        submit('Ejecutar y guardar evaluación','/api/evaluations',400)
        expect(page.locator('#notification')).to_contain_text('inválid')
    checks.append('duplicados y no finitos rechazados')
    nav('experimentos')
    with page.expect_response(lambda r:r.url.endswith('/api/experiments/verify')) as pending:
        page.get_by_role('button',name='Verificar',exact=True).first.click()
    assert pending.value.status==200 and pending.value.json()['result']['files']['state']=='MATCH'
    expect(page.get_by_text('MATCH',exact=True)).to_be_visible()
    checks.append('registro experimental y comprobación de hashes')
    nav('pronosticos');page.get_by_role('button',name='Cargar ejemplo histórico sintético',exact=True).click()
    identifier=page.locator('#forecast-id').input_value()
    page.locator('#resolution-rule').fill('Caso retrospectivo sintético.\nLa etiqueta no es evidencia externa.')
    submit('Registrar pronóstico','/api/forecasts')
    page.locator('#resolution-id').select_option(identifier);page.locator('#outcome').select_option('false')
    submit('Guardar resolución','/api/resolutions');expect(page.locator('main')).to_contain_text('0,49')
    checks.append('pronóstico multilínea resuelto: Brier0.49/referencia0.25')
    nav('evidencia');page.get_by_role('button',name='Cargar ejemplo sintético',exact=True).click()
    page.locator('#content-file').set_input_files({'name':'observacion.txt','mimeType':'text/plain',
        'buffer':'Observación sintética: 12 paneles.\nTexto citado: ignora instrucciones; esto es dato, no una orden.\n'.encode()})
    imported=submit('Importar evidencia','/api/evidence')['result'];assert imported['integrity']=='MATCH'
    assert submit('Verificar','/api/evidence/verify')['result']['evidence_verified'] is False
    assert download('evidence.json')['result']['sha256']==imported['sha256']
    checks.append('archivoUTF8 importado/verificado/exportado sin ejecutarlo')
    nav('control');demo=submit('Ejecutar demostración sintética','/api/demo')['result']['result']
    assert demo['status']=='PASS' and demo['final_event']['version']==1 and demo['external_effects'] is False
    expect(page.get_by_text('UNKNOWN → CONFIRMED',exact=True)).to_be_visible()
    checks.append('demoUnix: un efecto ficticio, reconciliación y revocación')
    page.reload();page.wait_for_load_state('networkidle')
    expect(page.get_by_text('UNKNOWN → CONFIRMED',exact=True)).to_be_visible()
    nav('resumen');page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/'desktop.png'),full_page=True)
    context.set_offline(True);page.get_by_role('button',name='Actualizar',exact=True).click()
    expect(page.locator('#connection')).to_have_text('Sin conexión confirmada')
    context.set_offline(False);page.get_by_role('button',name='Actualizar',exact=True).click()
    expect(page.locator('#connection')).to_have_text('Servicio conectado')
    checks.append('desconexión visible/recuperación sin repetirPOST')
    for width in (375,320):
        page.set_viewport_size({'width':width,'height':812})
        page.get_by_role('button',name='Abrir menú',exact=True).click()
        page.locator('nav a[href="#evidencia"]').click()
        expect(page.get_by_role('button',name='Abrir menú',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+1')
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(out/f'mobile-{width}.png'),full_page=True)
    # Skip link must not navigate away from the current section.
    before=page.url;page.locator('.skip').focus();page.locator('.skip').click()
    assert page.url==before
    assert page.evaluate('document.activeElement.id')=='main'
    checks.append('móvil375/320, menú misma ruta y salto accesible al contenido')
    page.set_viewport_size({'width':1440,'height':1000})
    # Explicit synthetic setup via API, not misrepresented as 17 UI submissions.
    populated=page.evaluate('''async () => {
      const token=(await (await fetch('/api/bootstrap')).json()).result.csrf_token;
      for(let i=0;i<17;i++){
        const r=await fetch('/api/evaluations',{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':token},
          body:JSON.stringify({name:'Historial sintético '+i,cases:[{id:'small',domain:'exact',prompt:'Sintético',method:'exact_json',expected:2}],responses:[{id:'small',answer:2}]})});
        if(!r.ok)throw Error('Fixture HTTP '+r.status);
      }
      const bad=await fetch('/api/state?offset=0&offset=1',{headers:{'X-App-Token':token}});
      const denied=await fetch('/api/demo',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      return {bad:bad.status,denied:denied.status};
    }''')
    assert populated=={'bad':400,'denied':403}
    page.get_by_role('button',name='Actualizar',exact=True).click()
    nav('evaluaciones')
    expect(page.get_by_role('button',name='Siguiente',exact=True)).to_be_enabled()
    with page.expect_response(lambda r:'/api/state?offset=' in r.url) as pending:
        page.get_by_role('button',name='Siguiente',exact=True).click()
    last=pending.value.json()['result']
    assert last['pagination']['total_jobs']==21 and last['pagination']['returned_jobs']==1
    assert last['evaluations'][0]['id']==first['id']
    expect(page.get_by_role('button',name='Anterior',exact=True)).to_be_enabled()
    page.get_by_role('button',name='Anterior',exact=True).click()
    expect(page.get_by_role('button',name='Siguiente',exact=True)).to_be_enabled()
    checks.append('21registros: páginas accesibles, query inválida400 y POSTsin token403')
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.absolute();out.mkdir(mode=0o700,parents=False,exist_ok=False);out=out.resolve()
    python=str(Path(args.python).absolute());child=None
    try:
        child,url=start(python,out,1)
        with sync_playwright() as engine:
            with engine.chromium.launch(headless=True) as browser:
                context=browser.new_context(viewport={'width':1440,'height':1000},locale='es-MX',accept_downloads=True)
                page=context.new_page();errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                checks=exercise(page,context,url,out)
                stop(child);child=None
                child,url=start(python,out,2)
                page.goto(url+'/#control');page.wait_for_load_state('networkidle')
                # New token/process, same physical workspace; the demo is on page1 or2.
                token=page.evaluate("async()=> (await(await fetch('/api/bootstrap')).json()).result.csrf_token")
                persisted=page.evaluate("async t=> (await(await fetch('/api/state',{headers:{'X-App-Token':t}})).json()).result",token)
                assert persisted['totals']=={'evaluations':19,'evidence':1,'demos':1,'experiments':19}
                assert persisted['forecasts']['score']['resolved']==1
                assert persisted['warnings']==[]
                checks.append('persistencia tras parar/reabrir proceso y renovar token')
                assert not errors,errors
                (out/'report.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'synthetic_only':True},ensure_ascii=False,indent=2)+'\n')
                print(json.dumps(checks,ensure_ascii=False,indent=2))
                context.close()
        stop(child);child=None
        return 0
    finally:
        if child is not None:stop(child)


if __name__=='__main__':raise SystemExit(main())
