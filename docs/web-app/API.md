# Contrato HTTP local v1 — aplicación 0.2

Servidor en http://127.0.0.1:8765 por defecto. CLI `python -m laboratorio.web_app --workspace runs/app --port 8765 [--operator-root R]`. Sólo loopback. El puerto 0 puede emplearse en tests. Assets `/`, `/app.js`, `/style.css`, `/icon.svg`. No archivos arbitrarios ni directory listing.

JSON respuestas: `{ok:true,result:...}`; errores `{ok:false,error:{code,message}}` con texto controlado sin rutas/inputs/raw traceback. HTTP400 validación,403 host/origin/token,404 desconocido,409 conflicto,413 límites,500 fallo no confirmado. No retry automático de POST.

GET `/api/bootstrap` → `{csrf_token,version:"1",limits:{max_body_bytes:2000000,max_content_bytes:1048576,max_jobs:100}}`. CSRF de sesión aleatorio, no persistido ni logueado. Todas las demás rutas API requieren `X-App-Token`. POST además Origin exacto de la instancia, Content-Type application/json, Content-Length único y limitado; no Transfer-Encoding. Host exacto 127.0.0.1:puerto. GET de bootstrap no implica autenticación. Cabeceras CSP/no-store/nosniff/frame-ancestors none/referrer-policy no-referrer; sin CORS. Mutaciones nunca por GET. No conexión a red externa.

GET `/api/state` (o `/api/state?offset=N`, entero 0–300, sin otros parámetros) →
```
{
 evaluations:[{id,name,created_at,result}],
 experiments:[{id,name,created_at,state,head_sha256,versions}],
 forecasts:{forecasts:[{forecast,registered_at,status}],resolutions:[{resolution,registered_at}],score:{resolved,pending,overdue,brier,baseline_brier,...}},
 evidence:[{id,title,url,source_kind,captured_at,imported_at,sha256,integrity,source_count}],
 demos:[{id,created_at,result}],
 operator:{status,...},
 warnings:[],
 gates:{enterprise_complete:false,C1_T02_verified:false,human_authenticated:false,evidence_verified:false,prospective_validation:false},
 limits:{...},
 totals:{evaluations,evidence,demos,experiments},
 pagination:{offset,next_offset,total_jobs,returned_jobs}
}
```
Los arrays evaluations/evidence/demos/experiments contienen una página global de hasta20jobs, ordenada por mtime de directorio e ID. `totals` cuenta trabajos almacenados, no trabajos aprobados. El frontend no acumula todas las páginas automáticamente. Un presupuesto previo agregado limita lecturas; JSON de estado como máximo4MiB. Archivos excesivos generan warning conid y se avanza cursor, no un bucle infinito. Almacenes dañados generan advertencias, no se silencian como listas vacías exitosas. Lista de jobs acotada, sin lectura recursiva. `operator` sólo resumen readonly del root fijado por CLI; si no existe se muestra NOT_CONFIGURED. No paths ni recibos/intents arbitrarios en el resumen.

POST `/api/catalog` body `{seed:17,per_family:2}` → `{cases:[...]}` (referencias públicas incluidas). Generación pura sin persistir ni dar por evaluado un modelo.

POST `/api/evaluations` body `{name,cases_json,responses_json}` (dos strings JSON crudos, forma usada por navegador) o `{name,cases,responses}` (arrays, compatibilidad API; no mezclar formas) → `{id,name,created_at,result}`. `cases`/`responses` son arrays del evaluador existente, máximo500casos, body2MB. Guardar entrada, respuestas y resultado reales en job privado. Crear automáticamente registro experimental del caso/resultado/código del evaluador: id del experimento igual al de evaluación, un manifiesto inicial. Se comprueban hashes de archivos reales, nunca hashes proporcionados por el navegador. Nombre1–120caracteres sin controles. IDs/dominios de casos como máximo128caracteres y prompt4096. El navegador nunca parsea/restringifica el JSON enviado para evaluar: el servidor detecta claves duplicadas/no finitos y conserva enteros grandes exactos. Las descargas conservan los bytes del envelope JSON HTTP (`ok`/`result`), sin conversión numérica en JavaScript. Datos de usuario son datos, nunca código.

POST `/api/experiments/verify` body `{id}` → resultado de check_files + verify_export del registro propio. Sólo ID interno `^[a-f0-9]{32}$`; sin rutas.

POST `/api/forecasts` body `{forecast:{id,question,probability,issued_at,resolve_at,resolution_rule}}` → resultado de Ledger.add. Todos los campos exactos del core, UTC YYYY-MM-DDTHH:MM:SSZ. Un ledger global de workspace, persistente.
Admisión del ledger: reglas multilínea conservadas, hasta100 registros y vista≤1MiB. Se calcula la vista proyectada antes de escribir y se reservan8192bytes por pendiente para una resolución futura. Si no cabe,413 LEDGER_CAPACITY sin crear el registro. La lectura física permite como máximo201 archivos≤32KiB, con preflight≤8MiB (incluye márgenes). Una vista ilegible genera warning, no vacío exitoso.

POST `/api/resolutions` body `{resolution:{id,outcome,resolved_at,evidence_url}}` → resultado Ledger.resolve. Duplicados/tempranos rechazados; outcomes bool, no string. Resultados no verifican evidencia. Dashboard muestra Brier null si pendientes.

La URL de resolución tiene además límite de2048bytes UTF-8. La resolución se admite sólo si su vista proyectada sigue legible; esto permite resolver registros válidos heredados sin exigirles retrospectivamente la reserva de admisión.

POST `/api/evidence` body `{title,url,source_kind,captured_at,content}` → mismo item de lista evidence. Un documento UTF8 cargado/pegado explícitamente,1MiB, source_kind public/synthetic/authorized declarativo. Backend crea spec/archivo interno y usa import_bundle. No `path` recibido por API ni captura web.
POST `/api/evidence/verify` body `{id}` → resultado verify_bundle propio.

POST `/api/demo` body `{}` → `{id,created_at,result}`. Ejecuta core run_demo sobre fixture NUEVO, sintético, con directorio temporal privado corto bajo padre de workspace, no sobre operator_root. Ningún parámetro de rol/identidad/path. Resultado con banderas false y efecto exactamente1. Historial persistente. No endpoint para aprobar/despachar operador real. Si ruta larga limita AF_UNIX, error controlado, nunca fingir demo exitosa.

GET `/api/export?kind=evaluation|experiment|evidence|demo&id=ID` → resultado JSON correspondiente; requiere header de sesión, nada de archivos por nombre. Frontend descarga por fetch+Blob (sin exponer token en URL).

## Persistencia y amenazas
Workspace privado y bloqueo exclusivo para una instancia. Máximo100jobs por tipo (puede limitar demos menos y documentarlo). Escrituras atómicas/no reemplazo, inputs inválidos no crean éxitos; fallos parciales quedan visibles. Reconocer symlinks/archivos especiales/cambios observados; no prometer aislamiento frente a la misma UID. Reabrir conserva historial. La sesión CSRF cambia en cada arranque. Activos empaquetados y sin CDN.
