'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const titles = {resumen:'Resumen', evaluaciones:'Evaluaciones', experimentos:'Experimentos', pronosticos:'Pronósticos', evidencia:'Evidencia', control:'Control'};
  let token = null, state = null, busy = false, connected = false, selectedEvaluation = null, rowLimit = 50;
  let cursor = 0;
  const previousPages = [];
  const drafts = new Map();
  const verification = new Map();
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === 'class') node.className = value;
      else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
      else if (key === 'value') node.value = value;
      else if (value !== false && value != null) node.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat(Infinity)) if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  }
  const text = value => value == null ? '—' : String(value);
  const pct = value => value == null ? '—' : new Intl.NumberFormat('es', {style:'percent',maximumFractionDigits:1}).format(value);
  const number = value => value == null ? '—' : new Intl.NumberFormat('es', {maximumFractionDigits:4}).format(value);
  function date(value) { if (!value) return '—'; const d = new Date(value); return Number.isNaN(d.getTime()) ? String(value) : new Intl.DateTimeFormat('es', {dateStyle:'medium',timeStyle:'short'}).format(d); }
  function utc(value) { const d = new Date(value); if (!value || Number.isNaN(d.getTime())) throw new Error('Completa una fecha y hora válidas.'); return d.toISOString().replace(/\.\d{3}Z$/, 'Z'); }
  function localDate(value) { const d = new Date(value); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0,19); }
  function notify(message, error = false) { const n = $('notification'); n.textContent = message; n.className = `notification${error ? ' error' : ''}`; n.hidden = false; }
  function connection() { $('connection').textContent = connected ? 'Servicio conectado' : 'Sin conexión confirmada'; $('connection').className = `badge ${connected ? 'good' : 'warn'}`; }
  async function api(path, body) {
    const post = body !== undefined;
    const headers = path === '/api/bootstrap' ? {} : {'X-App-Token':token || ''};
    if (post) headers['Content-Type'] = 'application/json';
    let response, payload;
    try {
      response = await fetch(path, {method:post ? 'POST':'GET', headers, body:post ? JSON.stringify(body):undefined, cache:'no-store', credentials:'same-origin'});
      payload = await response.json();
    } catch (_) {
      connected = false; connection();
      throw new Error(post ? 'Resultado INCIERTO: se perdió la respuesta. Actualiza el estado antes de volver a enviar; no se reintentó la operación.' : 'No se pudo consultar el servicio local. Comprueba que esté activo y pulsa Actualizar.');
    }
    if (!response.ok || payload.ok !== true) {
      if (response.status === 403) { connected = false; connection(); }
      const message = payload.error?.message || 'Respuesta del servidor no válida.';
      throw new Error(`${post && response.status >= 500 ? 'Resultado INCIERTO. ' : ''}${message}${response.status === 403 ? ' Pulsa Actualizar para renovar la sesión.' : ''}${post && response.status >= 500 ? ' Consulta el estado antes de volver a enviar.' : ''}`);
    }
    return payload.result;
  }
  async function refresh(bootstrap = false) {
    if (bootstrap || !token) token = (await api('/api/bootstrap')).csrf_token;
    state = await api(cursor === 0 ? '/api/state' : `/api/state?offset=${cursor}`); connected = true; connection(); render();
  }
  async function run(button, work) {
    if (busy) return;
    busy = true;
    const buttons = [...document.querySelectorAll('button')];
    const prior = buttons.map(b => b.disabled);
    buttons.forEach(b => { b.disabled = true; });
    if (button) button.setAttribute('aria-busy','true');
    try { await work(); } catch (error) { notify(error.message || 'La operación no pudo completarse.', true); }
    finally { busy = false; buttons.forEach((b,i) => { b.disabled = prior[i]; }); if (button) button.removeAttribute('aria-busy'); }
  }
  async function save(path, body, message, after) {
    const result = await api(path, body);
    cursor = 0; previousPages.length = 0;
    if (after) after(result);
    notify(message);
    try { await refresh(); } catch (error) { notify(`${message} No se pudo actualizar la vista. ${error.message}`, true); }
    return result;
  }
  function button(label, handler, secondary = false) { const b = el('button', {type:'button', class:secondary ? 'secondary' : ''}, label); b.addEventListener('click', () => run(b, () => handler(b))); return b; }
  function badge(value, kind = '') { return el('span', {class:`badge ${kind}`}, text(value)); }
  function hash(value) { return el('span', {class:'mono hash',title:text(value),tabindex:'0','aria-label':`SHA-256 completo: ${text(value)}`}, value ? `${value.slice(0,12)}…${value.slice(-6)}`:'—'); }
  function metric(label, value, note) { return el('div', {class:'metric'}, el('div',{class:'metric-label'},label),el('div',{class:'metric-value'},text(value)),el('div',{class:'metric-note'},note)); }
  function metrics(...items) { return el('div',{class:'metrics'},...items); }
  function card(title, description, ...children) { return el('section',{class:'card'},el('div',{class:'card-head'},el('div',{},el('h2',{},title), description ? el('p',{},description):null)),...children); }
  function empty(title, description, route) { return el('div',{class:'empty'},el('h3',{},title),el('p',{},description),route ? el('a',{class:'link-button',href:`#${route}`},'Crear primer registro'):null); }
  function notice(message, info = false) { return el('div',{class:`notice${info ? ' info':''}`},message); }
  function table(caption, headers, rows) { return el('div',{class:'table-wrap',tabindex:'0',role:'region','aria-label':caption},el('table',{},el('caption',{},caption),el('thead',{},el('tr',{},headers.map(h => el('th',{scope:'col'},h)))),el('tbody',{},rows.map(row => el('tr',{},row.map(cell => el('td',{},cell))))))); }
  function details(pairs) { return el('dl',{class:'detail-list'},pairs.flatMap(([key,value])=>[el('dt',{},key),el('dd',{},value instanceof Node ? value:text(value))])); }
  function field(id, label, type = 'text', options = {}) {
    const {wide, hint, value, ...attrs} = options;
    let input;
    if (type === 'textarea') input = el('textarea',{id,name:id,...attrs});
    else input = el('input',{id,name:id,type,...attrs});
    if (value != null) input.value = value;
    if (hint) input.setAttribute('aria-describedby',`${id}-hint`);
    return el('div',{class:`field${wide ? ' wide':''}`},el('label',{for:id},label),input,hint ? el('p',{class:'hint',id:`${id}-hint`},hint):null);
  }
  function selectField(id,label,choices,hint) { return el('div',{class:'field'},el('label',{for:id},label),el('select',{id,name:id,required:true,'aria-describedby':hint ? `${id}-hint`:null},choices.map(([value,name])=>el('option',{value},name))),hint ? el('p',{class:'hint',id:`${id}-hint`},hint):null); }
  function form(id, content, submitText, handler) { const submit = el('button',{type:'submit'},submitText); const f = el('form',{id},content,el('div',{class:'form-actions'},submit,el('span',{class:'hint'},'Validación final a cargo del servidor.'))); f.addEventListener('submit',e=>{e.preventDefault();run(submit,()=>handler(new FormData(f)));}); return f; }
  function safeInteger(id) { const value = Number($(id).value); if (!$(id).value.trim() || !Number.isSafeInteger(value)) throw new Error('Semilla y cantidad deben ser enteros seguros.'); return value; }
  function fileField(id,label,target,maxBytes) { const f = field(id,label,'file',{accept:'.txt,.json,text/plain,application/json',hint:`UTF-8 · máximo ${maxBytes === 1048576 ? '1 MiB' : '2 MB'}.`}); f.querySelector('input').addEventListener('change',e=>run(null,async()=>{const file = e.target.files[0]; if (!file) return; if(file.size>maxBytes) throw new Error('El archivo supera el límite permitido.'); let content; try {content = new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());} catch(_){throw new Error('El archivo no es texto UTF-8 válido.');} $(target).value=content; notify('Archivo cargado en el formulario. Aún no se ha guardado.');})); return f; }
  async function download(kind,id) {
    let response;
    try { response = await fetch(`/api/export?kind=${encodeURIComponent(kind)}&id=${encodeURIComponent(id)}`,{headers:{'X-App-Token':token || ''},cache:'no-store',credentials:'same-origin'}); }
    catch(_){throw new Error('No se pudo descargar. Comprueba la conexión y vuelve a intentarlo.');}
    if(!response.ok){let payload;try{payload=await response.json();}catch(_){}throw new Error(payload?.error?.message || 'La descarga fue rechazada.');}
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const a = el('a',{href:url,download:`${kind}-${id}.json`}); document.body.append(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),1000); notify('Exportación JSON descargada.');
  }
  const exportButton = (kind,id)=>button('Exportar JSON',()=>download(kind,id),true);
  function pageHead(title,description,action) { return el('div',{class:'page-head'},el('div',{},el('p',{class:'eyebrow'},'LABORATORIO / LOCAL'),el('h1',{},title),el('p',{},description)),action ? el('div',{class:'actions'},action):null); }
  const total = kind => state.totals?.[kind] ?? (state.totals ? null : state[kind].length);
  function pageEmpty(kind, title, description, route) {
    return total(kind) !== 0 ? empty('Sin registros validados en esta página',
      'Hay registros en otras páginas o pendientes de validación. Usa Anterior / Siguiente y consulta las advertencias.') : empty(title, description, route);
  }
  function pagination() {
    const p = state.pagination || {offset:0,next_offset:null,total_jobs:0,returned_jobs:0};
    const back = button('Anterior', async()=>{
      const target = previousPages[previousPages.length - 1];
      const old = cursor; cursor = target;
      try { await refresh(); previousPages.pop(); render(); } catch(error) { cursor = old; throw error; }
    }, true);
    back.disabled = previousPages.length === 0;
    const next = button('Siguiente', async()=>{
      const old = cursor; cursor = p.next_offset;
      try { await refresh(); previousPages.push(old); render(); } catch(error) { cursor = old; throw error; }
    }, true);
    next.disabled = p.next_offset === null;
    return el('nav', {class:'pagination','aria-label':'Páginas de registros'}, back,
      el('span',{}, `${p.returned_jobs} registros validados en esta página · ${p.total_jobs} registros almacenados · posición ${p.offset}. Los totales incluyen registros parciales; no son conteos PASS.`), next);
  }
  function overview() {
    const f=state.forecasts.score;
    const activity=[...state.evaluations.map(x=>({name:x.name,kind:'Evaluación',at:x.created_at,route:'evaluaciones'})),...state.evidence.map(x=>({name:x.title,kind:'Evidencia importada',at:x.imported_at,route:'evidencia'})),...state.demos.map(x=>({name:'Demostración sintética',kind:x.result.status,at:x.created_at,route:'control'})),...state.forecasts.forecasts.map(x=>({name:x.forecast.question,kind:'Pronóstico registrado',at:x.registered_at,route:'pronosticos'})),...state.forecasts.resolutions.map(x=>({name:x.resolution.id,kind:'Resolución registrada',at:x.registered_at,route:'pronosticos'}))].sort((a,b)=>b.at.localeCompare(a.at));
    return [pageHead('Tu laboratorio, en perspectiva','Evaluaciones, registros y evidencia del workspace actual.',el('a',{href:'#evaluaciones',class:'link-button'},'Nueva evaluación')),
      metrics(metric('Evaluaciones',total('evaluations'),'Registros almacenados'),metric('Experimentos',total('experiments'),'Registros almacenados'),metric('Pronósticos pendientes',f?.pending,'Según el ledger del servidor'),metric('Documentos',total('evidence'),'Registros almacenados')),
      notice('Servicio frontend conectado ≠ operador vivo. Los resultados describen este workspace; no certifican capacidades generales.',true),
      el('div',{class:'grid overview-grid'},card('Actividad reciente','Fechas reales de registro',activity.length ? activity.slice(0,8).map(x=>el('div',{class:'activity'},el('div',{},el('a',{href:`#${x.route}`},x.name),el('small',{},x.kind)),el('time',{datetime:x.at},date(x.at)))):state.pagination?.total_jobs ? empty('Sin actividad validada en esta página','Consulta los registros en otras páginas y las advertencias.') : empty('Tu workspace está listo','Genera un catálogo o importa un documento para iniciar un registro real.')),
      card('Continuar una investigación','Cada acción conserva su registro en el servidor',el('div',{class:'stack'},[['evaluaciones','Evaluar respuestas','Casos, exactitud y cobertura por dominio.'],['pronosticos','Registrar un pronóstico','Probabilidades, resolución y puntuación Brier.'],['evidencia','Importar evidencia','Texto aportado por ti y huella de integridad.']].map(([route,title,desc])=>el('a',{href:`#${route}`,class:'quick-action'},el('strong',{},title+' →'),el('span',{},desc)))))),
      card('Estado del entorno','Lectura actual del backend',details([['Operador',state.operator.status],['Advertencias',state.warnings.length],['Límite de trabajos por tipo',state.limits.max_jobs],['Validación prospectiva',state.gates.prospective_validation === false ? 'No acreditada (false)':'Consultar Control']]))];
  }
  function evaluationResult(item) {
    const r=item.result;
    return card(item.name,`Registrada ${date(item.created_at)}`,el('div',{class:'actions'},badge(r.status,r.missing ? 'warn':'good'),exportButton('evaluation',item.id)),el('p',{class:'hint mono'},item.id),
      metrics(metric('Exactitud',pct(r.accuracy),`${r.correct} correctas / ${r.total} casos`),metric('Cobertura',pct(r.coverage),`${r.answered} respuestas`),metric('Pendientes',r.missing,'Casos sin respuesta'),metric('Total de casos',r.total,'Sólo esta evaluación')),
      table('Resultados por dominio',['Dominio','Casos','Correctas','Respondidas'],Object.entries(r.by_domain).map(([domain,v])=>[domain,v.total,v.correct,v.answered])),
      el('h3',{},'Detalle de casos'),table('Casos evaluados',['ID','Dominio','Respuesta','Resultado'],r.rows.slice(0,rowLimit).map(x=>[el('span',{class:'mono'},x.id),x.domain,x.answered ? 'Recibida':'Faltante',badge(!x.answered ? 'Pendiente':x.correct ? 'Correcta':'Incorrecta',!x.answered ? 'warn':x.correct ? 'good':'error')])),
      el('p',{class:'row-count'},`Mostrando ${Math.min(rowLimit,r.rows.length)} de ${r.rows.length} casos.`),r.rows.length>rowLimit ? button('Mostrar 50 más',()=>{rowLimit+=50;render();},true):null,
      notice('Estos resultados sólo cubren los casos enviados. No acreditan inteligencia general ni autorizan acciones.',true));
  }
  function evaluations() {
    let generatedFixture = null;
    const catalog = button('Generar catálogo',async()=>{const result=await api('/api/catalog',{seed:safeInteger('seed'),per_family:safeInteger('per-family')});generatedFixture=JSON.stringify(result.cases,null,2);$('cases').value=generatedFixture;notify('Catálogo generado. Revisa los casos y añade respuestas antes de evaluar.');});
    const example=button('Ejemplo sintético',()=>{if (generatedFixture === null || $('cases').value !== generatedFixture) throw new Error('Genera un catálogo sin modificar para usar el ejemplo sintético.'); const cases=JSON.parse(generatedFixture); if(!cases.length) throw new Error('Genera o carga un catálogo primero.'); $('responses').value=JSON.stringify(cases.slice(0,-1).map((c,i)=>({id:c.id,answer:i===0 && typeof c.expected==='number' ? c.expected+1:c.expected})),null,2);$('evaluation-name').value='Ejemplo sintético · catálogo';$('eval-example-note').hidden=false;notify('Respuestas sintéticas cargadas: incluyen una respuesta faltante. No se han evaluado.');},true);
    const editor=form('evaluation-form',[
      field('evaluation-name','Nombre de evaluación','text',{required:true,maxlength:120,wide:true,placeholder:'Ej. Modelo local · lote de septiembre'}),
      el('h3',{},'1. Prepara los casos'),el('div',{class:'inline-fields'},field('seed','Semilla','number',{value:17,required:true,step:1}),field('per-family','Casos por familia','number',{value:2,min:1,required:true,step:1}),catalog),
      el('div',{class:'fields'},field('cases','Casos (array JSON)','textarea',{required:true,wide:true,placeholder:'[{"id":"caso-1", …}]'}),fileField('cases-file','Cargar casos desde archivo','cases',2000000)),
      el('h3',{},'2. Añade las respuestas'),example,el('p',{id:'eval-example-note',class:'notice',hidden:true},'EJEMPLO SINTÉTICO: respuestas construidas a partir de las referencias; no proceden de un modelo.'),
      el('div',{class:'fields'},field('responses','Respuestas (array JSON)','textarea',{required:true,wide:true,placeholder:'[{"id":"caso-1","answer":42}]',hint:'Usa [] para registrar todos los casos como pendientes.'}),fileField('responses-file','Cargar respuestas desde archivo','responses',2000000))
    ],'Ejecutar y guardar evaluación',()=>save('/api/evaluations',{name:$('evaluation-name').value,cases_json:$('cases').value,responses_json:$('responses').value},'Evaluación guardada y registro experimental creado.',r=>{selectedEvaluation=r.id;rowLimit=50;}));
    const list=[...state.evaluations].sort((a,b)=>b.created_at.localeCompare(a.created_at));
    const chosen=list.find(x=>x.id===selectedEvaluation) || list[0];
    return [pageHead('Evaluaciones','Mide exactitud y cobertura sobre casos concretos. Los resultados se conservan en el servidor.'),card('Nueva evaluación','JSON del evaluador · hasta 500 casos · cuerpo máximo 2 MB',editor),card('Historial',`${list.length} en esta página · ${text(total('evaluations'))} registros almacenados`,list.length ? table('Historial de evaluaciones',['Nombre','Fecha','Exactitud','Cobertura','Acción'],list.map(x=>[x.name,date(x.created_at),pct(x.result.accuracy),pct(x.result.coverage),button(x.id===chosen?.id ? 'Seleccionada':'Ver resultado',()=>{selectedEvaluation=x.id;rowLimit=50;render();$('evaluation-detail').scrollIntoView({block:'start'});},true)])):pageEmpty('evaluations','Aún no hay evaluaciones','Genera un catálogo, aporta respuestas y ejecuta tu primera evaluación.')),chosen ? el('div',{id:'evaluation-detail'},evaluationResult(chosen)):null];
  }
  function verifyView(report,kind) {
    if(kind==='experiment')return [details([['Archivos',badge(report.files.state,report.files.state==='MATCH'?'good':'warn')],['Exportación',report.export.integrity],['Versiones',report.export.versions],['Hash de cabecera',hash(report.export.head_sha256)],['Autenticidad verificada',text(report.files.authenticity_verified)],['Ancla comprobada',text(report.export.anchor_checked)]]),table('Artefactos comprobados',['Grupo','Nombre','Estado','SHA-256'],Object.entries(report.files.artifacts || {}).flatMap(([group,items])=>items.map(x=>[group,x.name,x.status,hash(x.sha256)])))];
    return [details([['Integridad',badge(report.integrity,report.integrity==='MATCH'?'good':'warn')],['SHA-256',hash(report.sha256)],['Fuentes',report.manifest?.sources?.length],['Importación',date(report.manifest?.imported_at)]]),notice('La coincidencia de hashes no verifica la veracidad ni la propiedad de la fuente.')];
  }
  function verifyButton(kind,id) {return button('Verificar',async()=>{const report=await api(kind==='experiment'?'/api/experiments/verify':'/api/evidence/verify',{id});verification.set(`${kind}:${id}`,report);await refresh();notify('Comprobación terminada. Consulta integridad y límites en el registro.');},true);}
  function experiments() {
    return [pageHead('Experimentos','Trazabilidad de entradas, respuestas, resultados y código del evaluador.'),notice('AVAILABLE indica legibilidad. MATCH indica coincidencia de archivos; no acredita autenticidad ni un ancla externa.'),card('Registro experimental',`${state.experiments.length} en esta página · ${text(total('experiments'))} registros almacenados`,state.experiments.length ? table('Experimentos registrados',['Experimento','Estado','Versión','Hash de cabecera','Acciones'],state.experiments.map(x=>[el('div',{},el('strong',{},x.name),el('p',{class:'hint'},date(x.created_at)),el('span',{class:'mono'},x.id)),badge(x.state),x.versions,hash(x.head_sha256),el('div',{class:'actions'},verifyButton('experiment',x.id),exportButton('experiment',x.id))])):pageEmpty('experiments','El registro comienza con una evaluación','Cada evaluación guardada crea su manifiesto experimental.','evaluaciones')),state.experiments.filter(x=>verification.has(`experiment:${x.id}`)).map(x=>card(`Comprobación · ${x.name}`,'Resultado de files + export',verifyView(verification.get(`experiment:${x.id}`),'experiment')))];
  }
  function forecasts() {
    const ledger=state.forecasts, score=ledger.score;
    if (!score) return [pageHead('Pronósticos','El historial no se pudo consultar.'),notice('El ledger está incompleto, dañado o excede un límite. Esto NO significa que no haya pronósticos: se conservaron los archivos. Revisa las advertencias y recupera una copia por la CLI antes de volver a escribir.')];
    const resolved=new Set(ledger.resolutions.map(x=>x.resolution.id));
    const pending=ledger.forecasts.filter(x=>!resolved.has(x.forecast.id));
    const example=button('Cargar ejemplo histórico sintético',()=>{const values={'forecast-id':`sintetico-${Date.now()}`,'question':'EJEMPLO SINTÉTICO: ¿ocurrió el evento ficticio?','probability':'0.7','issued-at':localDate('2020-01-01T00:00:00Z'),'resolve-at':localDate('2020-01-02T00:00:00Z'),'resolution-rule':'Ejemplo sintético: resolver como verdadero para probar el formulario.','resolved-at':localDate('2020-01-03T00:00:00Z'),'evidence-url':'https://example.org/ejemplo-sintetico'};for(const [id,v]of Object.entries(values))$(id).value=v;updateRetrospective();notify('Ejemplo histórico sintético cargado. No se ha enviado al servidor.');},true);
    const create=form('forecast-form',el('div',{class:'fields'},field('forecast-id','ID del pronóstico','text',{required:true,placeholder:'evento-2026-001'}),field('probability','Probabilidad (0 a 1)','number',{required:true,min:0,max:1,step:'any',placeholder:'0.70'}),field('question','Pregunta verificable','text',{required:true,wide:true,maxlength:4096}),field('issued-at','Fecha de emisión · hora local','datetime-local',{required:true,step:1}),field('resolve-at','Fecha de resolución prevista · hora local','datetime-local',{required:true,step:1,oninput:updateRetrospective}),field('resolution-rule','Regla de resolución','textarea',{required:true,wide:true,maxlength:4096}),el('p',{id:'retrospective',class:'notice',hidden:true},'Registro retrospectivo: la fecha prevista ya pasó. Este ejemplo no constituye validación prospectiva.')),'Registrar pronóstico',()=>save('/api/forecasts',{forecast:{id:$('forecast-id').value,question:$('question').value,probability:Number($('probability').value),issued_at:utc($('issued-at').value),resolve_at:utc($('resolve-at').value),resolution_rule:$('resolution-rule').value}},'Pronóstico registrado.'));
    const resolution=form('resolution-form',el('div',{class:'fields'},selectField('resolution-id','Pronóstico por resolver',[['','Selecciona un ID'],...pending.map(x=>[x.forecast.id,x.forecast.id])]),selectField('outcome','Resultado',[['true','Verdadero · ocurrió'],['false','Falso · no ocurrió']]),field('resolved-at','Fecha de resolución efectiva · hora local','datetime-local',{required:true,step:1}),field('evidence-url','URL de evidencia','url',{required:true,placeholder:'https://…',hint:'Referencia declarada; el servidor no verifica su contenido.'})),'Guardar resolución',()=>save('/api/resolutions',{resolution:{id:$('resolution-id').value,outcome:$('outcome').value==='true',resolved_at:utc($('resolved-at').value),evidence_url:$('evidence-url').value}},'Resolución registrada.'));
    const statusLabels={pending:'Pendiente',overdue:'Vencido',resolved:'Resuelto'};
    return [pageHead('Pronósticos','Registra una probabilidad, define su regla y contrástala con un resultado explícito.'),metrics(metric('Resueltos',score?.resolved,'Con resultado registrado'),metric('Pendientes',score?.pending,`${text(score?.overdue)} vencidos`),metric('Brier',number(score?.brier),'Menor es mejor · sin resueltos: —'),metric('Brier de referencia',number(score?.baseline_brier),'Baseline del backend')),
      notice('Sin certificación prospectiva. Las fechas se convierten de tu hora local a UTC; la evidencia de resolución no se verifica.'),card('Nuevo pronóstico','Campos exactos del ledger; guardar es una acción explícita.',example,create),card('Resolver un pronóstico','Sólo IDs registrados sin resolución',pending.length ? null:notice('No hay pronósticos pendientes. Registra uno para poder resolverlo.',true),resolution),card('Historial de pronósticos',`${ledger.forecasts.length} registros`,ledger.forecasts.length ? table('Pronósticos',['ID / pregunta','Probabilidad','Emisión / resolución','Estado','Resultado'],ledger.forecasts.map(x=>{const r=ledger.resolutions.find(r=>r.resolution.id===x.forecast.id)?.resolution;return [el('div',{},el('strong',{},x.forecast.id),el('p',{class:'hint'},x.forecast.question),el('details',{},el('summary',{},'Regla de resolución'),el('p',{},x.forecast.resolution_rule))),pct(x.forecast.probability),el('div',{},date(x.forecast.issued_at),el('br'),date(x.forecast.resolve_at)),badge(statusLabels[x.status] || x.status,x.status==='overdue'?'warn':''),r ? el('div',{},r.outcome ? 'Verdadero':'Falso',el('p',{class:'hint'},date(r.resolved_at)),el('span',{class:'break'},r.evidence_url)):'—'];})):empty('Todavía no hay pronósticos','Crea uno con una pregunta y una regla de resolución explícita.'))];
  }
  function updateRetrospective(){if($('retrospective'))$('retrospective').hidden=!$('resolve-at').value || new Date($('resolve-at').value)>=new Date();}
  function evidence() {
    const example=button('Cargar ejemplo sintético',()=>{$('evidence-title').value='EJEMPLO SINTÉTICO · observación';$('source-url').value='https://example.org/ejemplo-sintetico';$('source-kind').value='synthetic';$('captured-at').value=localDate(new Date());$('content').value='EJEMPLO SINTÉTICO. Se observaron 12 paneles en un escenario ficticio. No constituye evidencia del mundo real.';notify('Ejemplo sintético preparado. Pulsa Importar para guardarlo.');},true);
    const editor=form('evidence-form',el('div',{class:'fields'},field('evidence-title','Título','text',{required:true,maxlength:200}),field('source-url','URL de referencia','url',{required:true,placeholder:'https://…',hint:'Sólo se registra la URL; no se descarga.'}),selectField('source-kind','Tipo de fuente',[['public','Pública'],['synthetic','Sintética'],['authorized','Autorizada']],'Declaración del aportante; no prueba propiedad ni permisos.'),field('captured-at','Fecha de captura · hora local','datetime-local',{required:true,step:1}),field('content','Contenido del documento','textarea',{required:true,wide:true,hint:'Pega texto propio, público o que tengas autorización para aportar. Máximo 1 MiB UTF-8.'}),fileField('content-file','Cargar documento UTF-8','content',1048576)),'Importar evidencia',()=>{if(new TextEncoder().encode($('content').value).length>1048576)throw new Error('El contenido supera 1 MiB UTF-8.');return save('/api/evidence',{title:$('evidence-title').value,url:$('source-url').value,source_kind:$('source-kind').value,captured_at:utc($('captured-at').value),content:$('content').value},'Documento importado.');});
    return [pageHead('Evidencia','Conserva documentos aportados explícitamente y comprueba su integridad.'),card('Importar documento','Contenido local · sin descarga de URL',notice('Aporta contenido propio, público o autorizado. El tipo de fuente es declarativo y no acredita titularidad.'),example,editor),card('Documentos registrados',`${state.evidence.length} en esta página · ${text(total('evidence'))} registros almacenados`,state.evidence.length ? table('Documentos importados',['Documento','Fuente / captura','Integridad','SHA-256','Acciones'],state.evidence.map(x=>[el('div',{},el('strong',{},x.title),el('p',{class:'hint break'},x.url),el('span',{class:'mono'},x.id)),el('div',{},x.source_kind,el('p',{class:'hint'},date(x.captured_at))),badge(x.integrity),hash(x.sha256),el('div',{class:'actions'},verifyButton('evidence',x.id),exportButton('evidence',x.id))])):pageEmpty('evidence','Aún no hay documentos','Pega contenido o carga un archivo UTF-8 para registrar su primera huella.')),state.evidence.filter(x=>verification.has(`evidence:${x.id}`)).map(x=>card(`Comprobación · ${x.title}`,'Integridad del bundle local',verifyView(verification.get(`evidence:${x.id}`),'evidence')))];
  }
  function operatorSummary(value) {
    if(!value || typeof value!=='object')return text(value);
    return details(Object.entries(value).map(([k,v])=>[k,typeof v==='object' && v!==null ? operatorSummary(v):text(v)]));
  }
  function control() {
    const demo=button('Ejecutar demostración sintética',()=>save('/api/demo',{},'Demostración sintética registrada.'));
    const labels={enterprise_complete:'Producto empresarial completo',C1_T02_verified:'C1-T02 verificado',human_authenticated:'Autenticación humana',evidence_verified:'Evidencia verificada',prospective_validation:'Validación prospectiva'};
    return [pageHead('Control','Observa los límites del producto y ensaya la recuperación en un escenario sintético.'),el('div',{class:'grid'},card('Operador','Resumen opcional · sólo lectura',badge(state.operator.status),notice('La conexión de esta interfaz al servicio no demuestra que el operador esté vivo.',true),operatorSummary(Object.fromEntries(Object.entries(state.operator).filter(([k])=>k!=='status')))),card('Capacidad del workspace','Presupuestos y conteos informados por la API',details([['Evaluaciones',`${text(total('evaluations'))} / ${state.limits.max_jobs} registros almacenados`],['Evidencia',`${text(total('evidence'))} / ${state.limits.max_jobs} registros almacenados`],['Demostraciones',`${text(total('demos'))} / ${state.limits.max_jobs} registros almacenados`],['Cuerpo máximo',`${state.limits.max_body_bytes} bytes`],['Documento máximo',`${state.limits.max_content_bytes} bytes`]]))),
      card('Demostración de recuperación','Escenario nuevo para cada ejecución',notice('Calendario ficticio, mismo UID, no autenticación humana. Reloj y datos sintéticos; no produce efectos externos ni ejecuta aprobaciones del operador real.'),demo),
      card('Historial de demostraciones',`${state.demos.length} en esta página · ${text(total('demos'))} registros almacenados`,state.demos.length ? [...state.demos].sort((a,b)=>b.created_at.localeCompare(a.created_at)).map(x=>el('section',{class:'card'},el('div',{class:'card-head'},el('div',{},el('h3',{},date(x.created_at)),badge(x.result.status,'good')),exportButton('demo',x.id)),details([['Recuperación',`${x.result.operation_before_recovery} → ${x.result.operation_after_recovery}`],['Efecto en calendario ficticio',`Versión ${x.result.final_event.version} · ${x.result.final_event.title}`],['Operación revocada',x.result.revoked_operation],['Llamadas de recuperación',x.result.recovery_transport_calls.join(' → ')],['Efectos externos',text(x.result.external_effects)],['Identidades OS separadas',text(x.result.separate_os_identities)],['Aprobación humana realizada',text(x.result.human_approval_performed)]]))):pageEmpty('demos','No se han ejecutado demostraciones','La ejecución explícita crea un resultado persistente del escenario sintético.')),
      card('Límites del producto','Banderas devueltas por el backend',table('Gates del producto',['Condición','Valor informado'],Object.entries(state.gates).map(([key,value])=>[labels[key] || key,badge(text(value),value===false?'warn':'')])) ,el('p',{class:'hint'},'false significa que esta aplicación no acredita esa condición.'))];
  }
  function snapshot(){for(const input of document.querySelectorAll('#view input:not([type=file]), #view textarea, #view select')) drafts.set(input.id,input.value);}
  function render() {
    snapshot();
    const route=Object.hasOwn(titles,location.hash.slice(1))?location.hash.slice(1):'resumen';
    $('breadcrumb').textContent=titles[route];document.title=`${titles[route]} · Límite de Acción`;
    document.querySelectorAll('#navigation>a').forEach(a=>{if(a.hash===`#${route}`)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    if(!state){$('view').replaceChildren(pageHead(titles[route],'Esperando datos del backend local.'),empty('No hay estado disponible','Pulsa Actualizar para conectar con el servicio.'));return;}
    const routes={resumen:overview,evaluaciones:evaluations,experimentos:experiments,pronosticos:forecasts,evidencia:evidence,control};
    $('view').replaceChildren(pagination(), ...routes[route]().flat(Infinity).filter(Boolean));
    for(const [id,value]of drafts){const input=$(id);if(input && input.matches('input:not([type=file]),textarea,select'))input.value=value;}
    updateRetrospective();
    $('warnings').replaceChildren(...state.warnings.map(w=>el('p',{},`Advertencia del backend: ${w.code} · ${w.component}${w.id ? ` · ${w.id}`:''}. El listado puede estar incompleto; no equivale a ausencia de registros.`)));
    $('warnings').hidden=state.warnings.length===0;
  }
  $('menu-toggle').addEventListener('click',()=>{const open=$('menu-toggle').getAttribute('aria-expanded')!=='true';$('menu-toggle').setAttribute('aria-expanded',String(open));$('menu-toggle').textContent=open?'Cerrar menú':'Abrir menú';$('navigation').classList.toggle('open',open);});
  function closeMenu(){ $('menu-toggle').setAttribute('aria-expanded','false');$('menu-toggle').textContent='Abrir menú';$('navigation').classList.remove('open'); }
  document.addEventListener('keydown',e=>{if(e.key==='Escape' && $('navigation').classList.contains('open')){closeMenu();$('menu-toggle').focus();}});
  $('navigation').addEventListener('click',e=>{if(e.target.closest('a'))closeMenu();});
  $('skip-link').addEventListener('click',e=>{e.preventDefault();$('main').focus();});
  window.addEventListener('hashchange',()=>{render();closeMenu();$('main').focus({preventScroll:true});window.scrollTo(0,0);});
  $('refresh').addEventListener('click',()=>run($('refresh'),async()=>{await refresh(true);notify('Estado actualizado desde el servidor.');}));
  run($('refresh'),async()=>{try{await refresh(true);}catch(error){render();throw error;}});
})();
