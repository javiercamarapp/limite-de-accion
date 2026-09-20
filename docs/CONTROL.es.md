# Control local: transporte, persistencia y recuperación

## Estado y alcance

Implementado: receptor SQLite de calendario ficticio, dos canales Unix con identidad del kernel, controlador durable y pruebas inocuas de permisos en Docker. **No equivale a C1-T02, aislamiento adversarial, una VM dedicada ni autenticación de una persona.** No actúa sobre calendarios externos.

En Linux, el transporte consulta `SO_PEERCRED`; en macOS, `getpeereid`. El UID admitido, rol y principal son configuración confiable del receptor, no campos elegibles en JSON. Cada canal sirve una lista distinta de métodos. El socket tiene modo 0600; se rechazan padres compartidos/escribibles por grupo u otros, enlaces y endpoints preexistentes. El envío JSONL tiene tamaño y tiempo acotados; el cliente termina su mitad de escritura. No hay reintentos de transporte.

UID no significa humano: un proceso permitido del mismo UID puede usar el canal correspondiente. La separación exige usuarios/procesos y permisos reales; los tests host y la demo usan el mismo UID y **no** la demuestran.

## Recorrido ejecutable sin Docker

```bash
uv sync --locked --extra dev
uv run --locked laboratorio demo-durable-control --out runs/control-ejemplo
```

Usar un directorio **nuevo**, bajo padres confiables. No se sobrescribe una corrida anterior. En macOS, mantener corta la ruta absoluta de los sockets (límite del sistema operativo); la ruta sugerida funciona en el checkout verificado. Directorios compartidos como `/tmp` no son una alternativa segura.

La demo:

1. Crea un calendario y una aprobación completamente sintéticos.
2. Registra intención y reserva una operación/budget en SQLite.
3. Persiste `DISPATCHING` antes de enviar al receptor Unix.
4. Descarta deliberadamente la primera respuesta **después** del efecto: queda `UNKNOWN`.
5. Cierra/reabre el controlador. Una llamada a dispatch **no reenvía** esa operación.
6. Reconciliación consulta `get_receipt`; sólo un recibo concordante produce `CONFIRMED`.
7. Aprueba sintéticamente otra intención, revoca y verifica `REJECTED`, sin segundo efecto.

Artefactos privados: `receiver.sqlite3`, `controller.sqlite3`, `controller-export.json`, `report.json`. Los sockets se retiran al cerrar. La lista `recovery_transport_calls` debe ser exactamente `["execute", "get_receipt"]`; `all_controller_transport_calls` agrega el intento revocado. La pérdida de respuesta se inyecta en la aplicación, no es una caída física inducida.

## Endurecimiento del CLI y regresión de muerte de proceso

Los comandos que leen JSON (`score`, `forecast-score`, `backtest`) sólo aceptan archivos regulares UTF-8 de hasta 2.000.000 bytes. Se rechazan enlaces simbólicos tanto en el archivo como en sus padres, FIFO, directorios y componentes `..`. La apertura recorre descriptores de directorio con `O_NOFOLLOW`; la lectura es acotada y usa apertura no bloqueante para evitar esperar a un escritor de FIFO. El parser estricto existente sigue rechazando JSON malformado, claves duplicadas y valores no finitos. En macOS, proporcionar rutas reales (`/private/tmp/...` para entradas, no el alias `/tmp/...`).

La salida de `demo-durable-control` exige un directorio nuevo. Sus padres se verifican por descriptor: propietarios root/UID efectivo, sin escritura de grupo/otros, sin enlaces ni `..`. Los padres faltantes se crean privados. Un error puede dejar directorios y artefactos parciales para diagnóstico; no se borran ni sobrescriben al repetir. Elegir otra ruta para una nueva corrida. Las conexiones y receptores se registran para cierre desde su creación, incluso si falla el fixture, SQLite o el arranque de un hilo. La retirada de sockets conserva el control de inode de la biblioteca existente y no elimina un archivo que haya reemplazado el socket. No se promete resistencia frente a procesos hostiles del mismo UID que cambien esos directorios durante la ejecución.

Los errores de entrada, ruta y almacenamiento SQLite producen código de salida `2`, stdout vacío y un objeto JSON en stderr con `error` y `actions_authorized: false`. Los errores de sintaxis de argumentos conservan el comportamiento de argparse. Los informes del recorrido siguen declarando reloj/datos sintéticos, ausencia de autenticación humana y `C1_T02_verified: false`.

Desde este clon y con el entorno Python ya disponible:

```bash
PYTHONPATH=src /Users/javiercamaraportepetit/Proyectos/limite-de-accion/.venv/bin/python -m laboratorio demo-durable-control --out runs/control-nuevo
/Users/javiercamaraportepetit/Proyectos/limite-de-accion/.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_control_recovery_real.py
/Users/javiercamaraportepetit/Proyectos/limite-de-accion/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=short
```

`tests/test_control_recovery_real.py` contiene una regresión de SIGKILL real en dos variantes: SQLite directo y transporte Unix/SQLite. El padre espera el recibo del efecto ya confirmado por el receptor y comprueba en otra conexión que el controlador aún conserva `DISPATCHING` sin recibo. Sólo entonces mata a su propio hijo benigno, espera su terminación y verifica reapertura a `UNKNOWN`, ausencia de reenvío, reconciliación a `CONFIRMED`, horario/versión exactos y presupuesto persistente. El hijo no crea descendientes. La variante directa prueba muerte/persistencia, no credenciales del kernel; no sustituye la variante Unix. Ninguna prueba nueva se omite cuando bind está restringido.

Evidencia histórica de la propuesta en sandbox (19-sep-2026; en ese momento pendiente de revisor limpio):

- Baseline, `python -m pytest -q -p no:cacheprovider`: **364 passed, 1 failed, 37 skipped**, 402 casos. El fallo existente es `test_cli_durable_control_recovers_without_replay`, con `PermissionError: [Errno 1] Operation not permitted` al abrir el socket.
- TDD inicial del archivo nuevo: **7 failed, 6 passed**. Se observaron aceptación indebida de enlaces, bloqueo FIFO hasta timeout, aceptación de `..` y conexión SQLite sin cerrar. Dos fallos correspondían al bind restringido. Una regresión posterior del error SQLite observó `OperationalError` sin convertir a JSON antes de corregirla.
- Prueba dirigida de SIGKILL/SQLite directo y error SQLite del CLI: **2 passed**. Se ejecutó SIGKILL real y se recogió al hijo; no es una excepción simulada.
- Suite completa final, `python -m pytest -q -p no:cacheprovider --tb=short`: **377 passed, 4 failed, 37 skipped**, 418 casos. Los cuatro fallos son bind Unix denegado: la demo existente y las tres pruebas nuevas de inicio de hilo, reemplazo/cleanup y SIGKILL/Unix. Las 37 omisiones provienen de pruebas existentes, sin modificar sus reglas.
- Wheel y sdist generados con `hatchling.build.build_wheel` / `build_sdist`, usando paquetes ya presentes en caché local, sin instalar dependencias ni acceder a red.

Ese checkpoint del sandbox **no cumplía** la compuerta de cero fallos/omisiones y entonces se retuvo la publicación. Posteriormente se ejecutaron las pruebas con sockets reales en el host, se cerraron las revisiones independientes y se publicó el código; la suite integrada actual tiene 688 casos sin fallos/skips. Véase el [cierre vigente](VERIFICATION-20260920.es.md). Ninguno de esos resultados certifica producto completo, autenticación humana, separación de UID ni contención adversarial.

## Contrato del controlador

`laboratorio.controller.DurableController` recibe `transport`, `deadline`, `max_operations` y un reloj confiable. El transporte compatible es `lambda message: request(dispatcher_socket, message)`.

- `register(intent)` fija el contenido de la intención.
- `reserve(intent_id, approval_id, operation_id)` reserva antes de enviar; es idempotente sólo con el mismo contenido. Una aprobación, intención o evento pendiente no puede reutilizarse.
- `dispatch(operation_id)` envía como máximo una vez. Error/respuesta inconclusa conserva `UNKNOWN`; nunca se interpreta como ausencia de efecto.
- `reconcile(operation_id)` sólo consulta recibos. `None` no autoriza reenvío ni libera el evento.
- Reabrir convierte `DISPATCHING` en `UNKNOWN`. Configuración/budget persisten y no pueden ampliarse al reabrir. Un reloj regresivo bloquea duraderamente nuevas mutaciones.
- `export_state()` y consultas permanecen disponibles para diagnóstico tras el deadline. No restablecen presupuesto.

El almacenamiento debe estar protegido de procesos no confiables. El controlador no es un servicio de autenticación ni una cola de candidatos hostiles. Dos instancias no permiten un segundo envío de una operación, pero abrir otra puede marcar un despacho vivo como incierto: la política favorece detener/reconciliar, no disponibilidad transparente.

El receptor limita `get_receipt` a operaciones del principal configurado del canal dispatcher. `get_event` expone solamente el calendario ficticio; no modifica registros. Las respuestas no se aceptan como éxito por tener una etiqueta: se verifica concordancia del recibo con la operación reservada.

## Prueba de permisos con tres UID dentro de Docker

Desde el **checkout o sdist**, no se requiere instalar una API ni habilitar Actions. Docker debe estar disponible y el operador debe tener ya la siguiente imagen. El runner usa `--pull never`: si falta, se detiene; cualquier descarga se decide aparte.

```bash
docker image inspect python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
uv run --locked python tools/preflight_local.py --out runs/unix-ejemplo --timeout 30
```

Perfil verificado antes de ejecutar: red `none`, raíz RO, sin privileged, sin mounts privados/home/socket Docker, snapshot explícito de cinco archivos públicos RO, tmpfs 16 MiB, 256 MiB RAM, 1 CPU, 64 PIDs, `no-new-privileges`, todas las capabilities retiradas salvo CHOWN/SETUID/SETGID del launcher confiable. Hijos de UID 25001/25002/25003 quedan sin capabilities. El receptor confiable corre como root **dentro del guest**; esto no demuestra la arquitectura completa endurecida.

Se exigen los **24 probes exactos**, todos verdaderos: acceso/denegación de sockets, identidad del par, archivos protegidos, scratch propio, ausencia de ruta externa, aprobación sintética, replay, revocación y horario final exacto con una sola versión. El informe rechaza atribuciones de aprobación humana, VM dedicada o contención adversarial.

El contenedor propio se elimina por ID previamente verificado. Si `docker create` queda ambiguo, se busca únicamente el nombre aleatorio asignado antes de crear y se comprueba nombre/nonce/ID. No se elimina por prefijo ni sin propiedad verificada. Lookup inconcluso se registra como tal, no como limpieza exitosa; no se reintenta crear. Un SIGKILL del host o caída del daemon aún puede impedir completar cleanup: conservar `state.json` y conciliar manualmente, sin borrar otros contenedores.

## Evidencia del 19-sep-2026

- Primera suite integrada: **401 passed, sin skips**, 8.34 s. Tras añadir regresión de empaquetado: **402 passed** en fuente macOS (8.39s), sdist/entorno limpio macOS (8.95s) y Linux aarch64 (17.43s), todos sin skips.
- La suite Linux se ejecutó sin red dentro de su propio contenedor de pruebas: 1CPU,512MiB,64PIDs, raíz RO, sin capabilities; dependencias pequeñas descargadas en host y verificadas contra hashes de uv.lock. Su workspace de código confiable permite exec para extensiones nativas. El primer intento, con tmpfs noexec por defecto, terminó con error de importación de Hypothesis y NO se contó como PASS; un probe de mmap reprodujo EPERM. Se corrigió sólo ese entorno de tests, sin modificar pruebas ni el perfil noexec del preflight de permisos. Contenedores propios eliminados.
- Demo real Unix/SQLite: `UNKNOWN → CONFIRMED`, un efecto con horario esperado, operación revocada rechazada.
- Docker posterior a auditoría: **24/24**, fuentes intactas, contenedor propio eliminado; sin contenedores restantes con la etiqueta de este experimento en la consulta posterior.
- Auditor independiente encontró dos falsos positivos/omisiones operativas: sólo comprobar versión no demostraba cambio horario, y creación Docker ambigua podía dejar huérfanos. Se añadieron regresiones, se corrigieron y se volvió a ejecutar el preflight real.
- Auditor y constructor estaban restringidos por sandbox; sus omisiones/fallo de bind no se presentaron como pruebas reales de aislamiento. El coordinador ejecutó la suite completa y Docker fuera de esa restricción.

Pendientes: ejecución/candidato/observador en topología canónica completa, canal administrativo externo protegido y autenticación humana real, kill-switch bajo candidato adversario, VM dedicada, campañas y benchmarks independientes, adaptación de modelos, observatorio operativo, monitoreo/recuperación de despliegue. No promover un experimento inocuo a certificación de seguridad.
