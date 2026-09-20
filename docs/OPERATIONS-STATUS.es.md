# Estado operativo LOCAL READONLY

Con el paquete instalado:

```sh
python -m laboratorio.operations_status --operator-root /ruta/operador --experiments /ruta/registro --forecasts /ruta/pronosticos --evidence /ruta/bundle --format json
python -m laboratorio.operations_status --forecasts /ruta/pronosticos --format text
python -m laboratorio.operations_status
```

Todas las rutas son opcionales e independientes. Se aceptan rutas locales absolutas o relativas al directorio actual, sin `..`, URI, controles ni symlinks. `--format` acepta `json` (predeterminado) o `text`. Los argumentos desconocidos o inválidos se rechazan sin reproducirlos en el error.

API:

```python
from laboratorio.operations_status import collect_status, format_text

report = collect_status(operator_root=None, experiments=None,
                        forecasts=None, evidence=None)
print(format_text(report))
```

La consola consulta almacenamiento existente. No inicia servicios, conexiones de socket, despachos, reconciliaciones, reparaciones ni importaciones de evidencia. No autentica humanos. No proporciona HTTP, HTML ni interfaz visual. No modifica el presupuesto ni inicia otro contador: `budget_used` cuenta las operaciones persistidas, cualquiera que sea su estado.

## Estados y códigos de salida

| Estado | Significado |
| --- | --- |
| `AVAILABLE` | Lectura validada del componente; no significa listo para operar ni completo. |
| `NOT_CONFIGURED` | No se proporcionó esa ruta. Sin ninguna ruta, también es el estado general. |
| `MISSING` | Falta la ruta o un archivo requerido detectado antes de la API. |
| `INVALID` | Almacenamiento inseguro, corrupto, fuera de límites, cambio observado durante lectura o estructura rechazada por la API. Un bundle parcial rechazado por su verificador también puede aparecer aquí. |
| `INCOMPLETE` | Registro íntegro cuyo último manifiesto declara artefactos faltantes/inválidos o no tiene resultados; incluye registro vacío. |

El estado general usa prioridad `INVALID`, `MISSING`, `INCOMPLETE`. Si no hay ninguno, muestra `AVAILABLE` cuando al menos un componente está disponible; los componentes omitidos continúan explícitamente `NOT_CONFIGURED`. Nunca se emite un `READY` general.

Código **0**: lectura válida, incluso configuración parcial o ninguna ruta. Código **2**: argumentos inválidos, componente declarado faltante/inválido o registro incompleto. Un error de componente no impide consultar los demás. Los errores de lectura se representan en el informe; los de argumentos usan un mensaje fijo en stderr, sin traceback ni rutas.

## Datos publicados

- Operador: presupuesto total y usado; conteos `RESERVED`, `DISPATCHING`, `UNKNOWN`, `CONFIRMED`, `REJECTED`; deadline, última observación y bloqueo persistido del reloj. Los estados son declaraciones almacenadas. `UNKNOWN` nunca cuenta como confirmado. `service_alive: null`: archivos no prueban que un servicio esté vivo.
- Experimentos: cantidad de versiones, estado de la última versión, historial de versión/estado/hash y hash de cabecera. Se reutilizan `export_registry` y `verify_export`. La cadena comprueba integridad de metadatos persistidos; `files_checked` y `anchor_checked` son falsos. No se vuelven a leer los originales.
- Pronósticos: `Ledger.score()` aporta resueltos, pendientes, vencidos, Brier y `baseline_brier` (referencia constante p=0.5), fecha local y retroceso del reloj. `overdue` es subconjunto de `pending`. Sin resoluciones, ambos scores son `null`, nunca cero. Las fechas declaradas no demuestran registro prospectivo.
- Evidencia: `verify_bundle` comprueba hashes de las copias locales. Se publican cantidad y conteos de origen **declarado** (`public`, `synthetic`, `authorized`), sin títulos, contenido, URLs ni rutas. No se consultan originales ni se abren URLs. Una declaración `authorized` no autentica a quien la escribió.

Siempre son falsos `enterprise_complete`, `C1_T02_verified`, `human_authenticated`, `evidence_verified`, `prospective_validation` y `dispatch_authorized`. Ningún score ni estado autoriza despacho. Un hash coincidente prueba solamente integridad relativa a esos metadatos, no autenticidad ni verdad de la evidencia.

La salida JSON usa campos permitidos, `null` y números finitos. El texto sólo representa etiquetas fijas, estados permitidos, timestamps validados y números: no imprime cadenas arbitrarias de metadatos. No se publican intents, recibos, credenciales ni configuración libre.

## Límites de lectura y concurrencia

Se recorren directorios físicos sin seguir symlinks; se rechazan FIFO, enlaces duros, archivos especiales, archivos ajenos o con escritura compartida entre los insumos consultados. JSON pasa por los decodificadores estrictos existentes (sin claves duplicadas, NaN ni booleanos donde se requieren enteros). La configuración del operador también conserva las restricciones de propiedad y padres confiables de su API.

Antes de las APIs heredadas hay enumeración y tamaños acotados:

| Componente | Límite |
| --- | --- |
| Operador | 32 entradas; configuración 65 536 bytes; SQLite 8 MiB; 1 000 operaciones y 1 000 intents; límite SQLite de 65 536 bytes para valores y filas codificadas. |
| Experimentos | 256 entradas, 64 000 bytes por archivo, 16 384 000 bytes agregados. |
| Pronósticos | 2 001 entradas, 32 KiB por archivo, 16 MiB agregados. |
| Evidencia | 17 entradas, manifiesto 64 KiB, cada copia 1 MiB, copias agregadas 16 MiB. |

SQLite requiere formato normal de journal, sin sidecars, vistas, triggers ni tablas virtuales. El operador usa **una sola conexión y transacción de lectura**, mediante `operator_cli._readonly`; sustituye expresamente el recorrido anterior por `operator_cli.query`, que abría una segunda conexión sin límites. Conserva la validación de configuración, propiedad y padres privados de `_load`. Nunca instancia un controlador ni ejecuta recuperación.

Antes de leer el esquema o cualquier columna se fijan límites con `Connection.setlimit`: `SQLITE_LIMIT_LENGTH=65536`, `SQLITE_LIMIT_SQL_LENGTH=16384`, `SQLITE_LIMIT_COLUMN=32`, `SQLITE_LIMIT_EXPR_DEPTH=32`, `SQLITE_LIMIT_COMPOUND_SELECT=1` y `SQLITE_LIMIT_ATTACHED=0`. Se desactiva `trusted_schema` y se interrumpe el trabajo al alcanzar el intervalo de 200 000 instrucciones del manejador de progreso. El límite de longitud opera dentro de SQLite antes de entregar valores a Python; no depende de medir memoria después de una asignación grande. También limita la fila codificada completa, por lo que puede rechazar campos individualmente menores al límite.

El DDL permitido es una descripción inmutable del esquema actual del core: las tres tablas, sus constraints y tipos, los cuatro índices automáticos y el índice parcial `active_event`. Sólo se ignora whitespace fuera de literales; no se aceptan migraciones desconocidas. `PRAGMA table_xinfo` verifica orden, nombres, tipos, nulabilidad, valores predeterminados, claves primarias y ausencia de columnas hidden/generadas. Todo ello precede a la lectura de datos. Se rechazan tanto columnas generadas que inventan `CONFIRMED` como expresiones que producirían cadenas de 64 MiB.

Los datos se recorren por cursor con columnas explícitas, `NOT INDEXED` y `LIMIT`: hasta 1 001 filas para detectar exceso de 1 000, y hasta dos para exigir una sola fila de estado. No hay `SELECT *`, `count(*)`, `fetchall` de datos ni segunda conexión. Se comprueban configuración durable, IDs únicos, referencias a intents, exclusividad de intent/aprobación y evento activo, correspondencia calendario/evento y enum de estado. Los intents pasan por JSON estricto, `authority._intent_snapshot`, `intent_digest` e igualdad del ID persistido. Recalcular un hash no convierte una estructura inválida en válida.

`CONFIRMED` exige un recibo JSON estricto compatible con `DurableController._receipt`, llamado como función estática: identidad, digest, recurso, tiempos y enteros exactos, sin aceptar booleanos como enteros. Los otros estados requieren `receipt_json IS NULL`; un recibo pendiente no se convierte en confirmación. Una declaración confirmada compatible sigue siendo **sólo lo persistido**, sin autenticidad ni efecto externo verificado.

Se compara identidad, tamaño y tiempos de los archivos antes y después de las lecturas; los cambios observados invalidan el componente. Los límites son conservadores y pueden rechazar almacenes legítimos más grandes.

La instantánea **NO es atómica entre componentes** y los timestamps locales **NO están certificados**. Las APIs heredadas reabren rutas: la comprobación previa/posterior no constituye aislamiento frente a un proceso malicioso del mismo UID que sustituya y restaure archivos concurrentemente. Tampoco se acredita vida del servicio, autenticación humana, validación prospectiva, producto empresarial completo ni C1-T02.

## Verificación

```sh
python -m pytest -q tests/test_operations_status.py
```

Las pruebas crean fixtures sintéticos con las APIs de los cuatro módulos, ejecutan la CLI real con `PYTHONPATH` explícito hacia las fuentes del proyecto y comprueban bytes, mtimes y listado sin cambios. Cubren corrupción aislada, estados inciertos, pendientes/resueltos, orígenes declarados, symlinks/FIFO, JSON ambiguo, booleanos indebidos, SQLite especial, límites previos y ausencia de escapes de terminal. No requieren servicios ni sockets y no introducen skips. La verificación AF_UNIX de la base corresponde al host por separado.


### Segunda construcción: evidencia propia

Se conservaron los **27 casos originales**. Antes de corregir el módulo, la suite con la primera tanda de regresiones produjo **24 failed, 29 passed in 1.76s**, exit 1. Después de corregir: **53 passed in 2.07s**, exit 0. Comando de ambas ejecuciones:

```sh
PYTHONPATH=src ../.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_operations_status.py
```

La ampliación de recibos válidos/inválidos, hashes recalculados, referencias y límites del motor incluye un control positivo: una confirmación sintética estructuralmente válida se publica sin autenticarla. La prueba del límite exige `sqlite3.DataError` para `zeroblob(67108864)` y `printf('%67108864s','x')` en la misma conexión limitada; no provoca ni intenta medir OOM. Otra prueba impide consultar datos de la tabla con la columna generada y exige los límites antes de leer el esquema.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_operations_status.py tests/test_controller.py tests/test_authority.py
```

Resultado: **141 passed in 2.10s**, exit 0, cero skips: 72 casos propios del módulo y 69 del core. Hubo una ejecución intermedia con **1 failed, 140 passed in 3.08s**: la nueva prueba esperaba NULL para `printf`, pero este SQLite devuelve `DataError`; se corrigió esa expectativa para exigir el rechazo del motor.

Las siete reproducciones del auditor también se ejecutaron contra estas fuentes. Se leyó su script sin modificarlo en disco y se sustituyeron únicamente `ROOT` y `BASE` en memoria para usar `.l06/src` y fixtures temporales propios. Los seis casos CLI dieron **exit 2 / INVALID**, el caso de asignación dio **INVALID**, los pronósticos siguieron `AVAILABLE`, los gates permanecieron falsos y todos indicaron `unchanged=true`. El script terminó con exit 0; no se modificaron los artefactos de auditoría.

Los **643 tests del host no son ejecución propia** y no forman parte de estos resultados. No se ejecutaron servicios AF_UNIX, red, Docker, Git ni agentes.

Selección adicional de CLI sin iniciar servicios:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src ../.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/test_operator_cli.py -k 'prepare_never or strict_bounded_json or special_input or db_symlink or special_sqlite_sidecars or clock_rollback or fixture_has_no or symlink_root or query_rejects_wal or module_help'
```

Resultado: **19 passed, 6 deselected in 2.53s**, exit 0, cero skips. Los seis casos no seleccionados no se cuentan como verificados.

### Reproducción pública y comando histórico de auditoría

Las regresiones distribuidas se ejecutan desde el repositorio con `python -m pytest -q tests/test_operations_status.py`. Los bloques anteriores que usan `../.venv/bin/python` son comandos históricos del entorno de construcción; en un entorno instalado use `python`.

El siguiente comando se conserva como evidencia histórica: requiere `../.v27/runs/review-v27-independent/repro.py`, **artefacto privado no distribuido**. No es un paso de instalación ni un comando reproducible desde un clon público por sí solo:

```sh
PYTHONPATH=src ../.venv/bin/python -B - <<'PY'
from pathlib import Path
import tempfile
source = Path('../.v27/runs/review-v27-independent/repro.py')
text = source.read_text()
with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='.status-audit-') as directory:
    text = text.replace('ROOT = Path(__file__).resolve().parents[2]', 'ROOT = Path(' + repr(str(Path.cwd())) + ')')
    text = text.replace("BASE = Path(tempfile.mkdtemp(prefix='cases-', dir=Path(__file__).resolve().parent))", 'BASE = Path(' + repr(directory) + ')')
    exec(compile(text, str(source), 'exec'), {'__file__': str(source), '__name__': '__main__'})
PY
```
