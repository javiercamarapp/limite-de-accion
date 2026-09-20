# Estado verificable — actualizado el 20 de septiembre de 2026 (UTC)

## Aplicación local 0.2

Ya existe interfaz gráfica en español: Resumen, Evaluaciones, Experimentos, Pronósticos, Evidencia y Control. Arranque: `uv run --locked limite-app`; URLpor defecto `http://127.0.0.1:8765`. Persistencia, exportaciones, errores visibles y paginación; no maqueta. [Guía](docs/web-app/GUIA.md).

**732 pruebas +22 subtests**, sin skips, en fuente y sdist limpio. Wheel instalado: recorrido Chromium real, móvil, precisión de enteros,21registros paginados y persistencia tras reiniciar. Tres revisiones técnicas, correcciones y aceptación independiente de las regresiones finales. [Evidencia y límites](docs/web-app/VERIFICACION.md).

Aplicación publicada en `5f127f9`; clon remoto nuevo también pasa732tests+22subtests. Instancia de entrega comprobada en `http://127.0.0.1:8765` — su disponibilidad posterior depende del proceso local.

La tanda web terminó por meta local cumplida, con máximo12agentes/3horas; consumió8ejecuciones secuenciales. No renovó el contador24/24 ni quitó elSTOP anterior. El servidor gráfico no es un supervisor de agentes.

**Sigue sin ser producto enterprise:** no despliegue público, autenticación humana/H1, C1-T02, aislamiento adversarial ni validación reservada/prospectiva. La UI evalúa respuestas aportadas; no ejecuta inferencia ni entrenamiento desde el navegador.

## Checkpoint CLI anterior — histórico

Los seis trabajos de la cola local están integrados en cinco commits de código publicados en `main`, hasta `83171eb`: CLI endurecida/operador, experimentos, pronósticos, importación offline de evidencia y consola de estado. **688 pruebas sin fallos ni skips** en host, sdist limpio y clon público; wheel instalado por separado y recorrido de cuatro almacenes con servicio Unix real verificados. [Registro completo y limitaciones](docs/VERIFICATION-20260920.es.md).

El supervisor antiguo se detuvo de forma controlada por el bloqueo de validación en sandbox; su STOP y estado se conservaron. La integración continuó supervisada, con el mismo contador y deadline, y publicación manual tras revisión/pruebas. No hay que interpretar un estado histórico como proceso vivo. El presupuesto acumulado está en `runs/continuo-20260919/integration/budget.json`: **24/24 consumidas**, incluida auditoría final. Tanda detenida por presupuesto, sin supervisor ni agente activos; no se presenta como ejecución continua vigente.

**Producto enterprise NO completo.** En ese checkpoint, consola significaba CLI JSON/texto; la versión0.2 posterior añade interfaz gráfica local. Importación offline no significa observatorio web automático. H1, C1-T02, aislamiento adversarial, despliegue y evaluación/adaptación reservada siguen pendientes.

Las secciones inferiores son checkpoints históricos y sus cifras no sustituyen las actuales.

## Alcance entregado
Incremento local experimental, no entrega enterprise completa. Repositorio público con licencia MIT (publicación autorizada y verificada después de esta recuperación): https://github.com/javiercamarapp/limite-de-accion, rama predeterminada `main`. La rama local de construcción es `feat/laboratorio-local`.

## Continuación pública: Unix, controlador durable y preflight

- Receptor Unix con UID obtenido del kernel, canales/allowlists separados y sockets 0600; controlador SQLite con reserva durable, un único envío y reconciliación sólo por recibo.
- `laboratorio demo-durable-control --out runs/durable-control-20260919`: **PASS**, UNKNOWN → CONFIRMED sin reenvío, horario exacto/version1, operación revocada REJECTED. Aprobación y reloj sintéticos, mismo UID del host.
- Suite integrada del coordinador: **401 passed in 8.34s, sin skips**. No se atribuye al sandbox del agente.
- `tools/preflight_local.py --out runs/unix-preflight-reviewed-20260919 --timeout 30`: **PASS, 24/24**, tres UID de guest, fuente intacta, container_removed=true. Consulta posterior de contenedores etiquetados sin resultados.
- Revisor independiente halló: comprobar sólo versión no probaba horario; timeout de dockercreate podía dejar un contenedor. Constructor añadió regresiones y fixes; coordinador releyó y ejecutó suite y Docker reales. Sin reintentar creación; recuperación por nombre/nonce propios verificados, nunca borrado por prefijo.
- Distribución final: **402 passed in 8.95s** desde sdist extraído; wheel instalado en entorno limpio con dependencias fijadas por `uv.lock`, ambas demos ejecutadas fuera de la fuente. Licencia MIT y archivos públicos inspeccionados; sin pesos/runs/.env. La comprobación encontró primero que faltaba CONTROL.es.md en la lista de inclusión: corregido, regresión añadida y build repetido. Un intento offline de instalar dependencias falló por caché incompleta; sincronización normal de dependencias públicas resolvió ese prerrequisito sin tocar el entorno MLX.
- Linux aarch64, dependencias de uv.lock verificadas por hash, suite en contenedor propio sin red: **402 passed in 17.43s**, sin skips. Primer intento FAILED por cargar Hypothesis nativo desde tmpfs noexec; se reprodujo mmap EPERM y se habilitó exec sólo en el workspace de tests confiables. No cambió código ni expectativas ni el perfil noexec de los24probes. Cleanup confirmado.
- Código de control y regresiones: commit `8e9f652`, identidad Git existente conservada y escaneo de secretos staged sin hallazgos.
- **C1_T02_verified=false**, sin VM dedicada, sin contención adversarial, sin autenticación de una persona. Guest root confiable con CHOWN/SETUID/SETGID sólo para setup; hijos sin capabilities. [Contrato y comandos](docs/CONTROL.es.md).

## Verificado en la recuperación anterior (baseline 189)

| Comprobación | Comando / resultado observado |
|---|---|
| Suite de fuente local | `.venv/bin/python -m pytest -q` → **189 passed in 5.99s** |
| Suite desde sdist extraído | Python 3.12 de un entorno limpio, `python -m pytest -q` → **189 passed in 6.83s** |
| Construcción | `uv build --offline` → exit 0; wheel y sdist generados |
| Instalación limpia | `UV_PROJECT_ENVIRONMENT=<temporal>/venv uv sync --locked --extra dev` → exit 0 |
| Wheel reconstruido desde sdist | `uv build --offline`, instalación sin dependencias nuevas en entorno limpio → exit 0 |
| CLI instalada fuera del repo | `laboratorio demo-control` → exit 0; alteración/replay/revocación comprobados; `C1_T02_verified:false` |
| Precisión instalada | expected `1e20`, answer `100000000000000000001`, tolerancia 0 → `correct:0` |
| Limpieza repetida de procesos inocuos | 80 ejecuciones de `cleanup` → cero fallos después de corregir la carrera de terminación de macOS |
| Secretos de cambios publicados | `git diff --cached --binary \| gitleaks stdin --redact --no-banner` → exit 0 para cada lote de código |
| Identidad y costes GitHub configurados | API devolvió author/committer `javiercamarapp`, Actions `enabled:false`, cero ejecuciones al comprobar tras el primer push |

Los tiempos anteriores pertenecen a esas ejecuciones concretas; no son benchmarks. Las pruebas nuevas incluyen subprocesos benignos, no modelos MLX ni software adversario.

### Auditoría y correcciones

1. Revisor separado reprodujo un falso acierto por resta int/float. Agente constructor lo corrigió usando `Fraction` y añadió 92 casos de precisión. Coordinador repitió el fallo original y la suite.
2. Constructor del watchdog reprodujo seis fallos iniciales: señales dejaban hijos, respuestas incompletas podían devolver éxito, resultados inválidos no producían informe y un symlink permitía salida externa. El agente agotó su plazo sin informe final; los logs contenían rojo y verde, y el coordinador verificó los archivos y volvió a ejecutar las pruebas.
3. Segunda auditoría encontró señales durante el cierre, lecturas/logs ilimitados, estado obsoleto ante fallo de persistencia y exclusión de herramientas del sdist. Se añadieron regresiones, límites desde la lectura, captura acotada de logs y recuperación terminal finita; se verificó el sdist real.
4. La suite del coordinador detectó además una carrera macOS: un grupo podía devolver EPERM antes de que waitpid anunciara que el hijo terminó. La primera corrección pasó suite pero falló una prueba repetida: **no se conservó como solución final**. Se añadió espera breve para confirmar salida sólo ante EPERM de un sondeo, sin silenciar permisos denegados de un hijo vivo, y se evitó enviar otra señal a un grupo desaparecido. Repetición final 80/80 y suite verdes.

Las revisiones independientes tuvieron límites de temporales en su sandbox: no pudieron ejecutar toda la suite de procesos. La segunda sí ejecutó 93 comprobaciones numéricas/reloj y reprodujo dos fallos de persistencia en memoria. Las suites completas y las verificaciones de distribución indicadas arriba fueron ejecutadas por el coordinador; no se atribuyen al revisor.

## Lo que NO prueba esta entrega

- No verifica C1-T02 ni separación adversarial entre candidato y evaluador. Sí hay pruebas inocuas de permisos OS entre tres UID dentro de un contenedor limitado; no elevarlas a aislamiento adversarial.
- No implementa autenticación administrativa externa, multiusuario, despliegue, interfaz enterprise, SSO/RBAC, monitorización operativa o recuperación productiva.
- Inferencia MLX actual sí se ejecutó, pero sólo como humo público sintético de5casos, sin herramientas ni nueva descarga. Mismo conjunto/hash y perfiles ya existentes: base0/5, cobertura4/5, un error de formato; typed3/5, cobertura5/5, sin error de formato. Base terminó FAILED por salida incompleta aunque el trabajador salió0; typed FINISHED no significa todas correctas (falló estadística y Euler). Tiempos internos8.46s/6.34s; picos MLX2,590,867,212/2,708,276,372bytes. Plazo90s por corrida, límite de asignador MLX8GiB, sin aislamiento de red OS; procesos propios eliminados. No hay entrenamiento, mejora general demostrada ni evaluación reservada.
- No hay validación prospectiva, conjunto reservado independiente, curas, prevención pandémica, supervisión mundial de agentes ni contención garantizada de una superinteligencia.
- Los límites de procesos no contienen descendientes que abandonen su grupo ni código con acceso adversarial al mismo usuario. SIGKILL, disco permanentemente averiado y caída del equipo pueden impedir persistir el estado final.
- Un resultado `FINISHED`/`COMPLETE` no es una respuesta correcta ni una autorización.

## GitHub y actividad real

Commits sustantivos, sin fechas alteradas ni commits vacíos:
- `42d568a`: núcleo local instalable, evaluación, pronóstico, calendario transaccional y pruebas CLI.
- `2f6b066`: precisión numérica sin falsos aciertos por redondeo.
- `6758a59`: supervisor, límites, interrupciones, persistencia y regresiones.
- La documentación final queda en el commit posterior, visible mediante `git log`.

Los commits de código llegaron a `main`; GitHub los asocia a la cuenta del usuario. La aparición visual del gráfico puede tardar. El repositorio nació privado y el usuario autorizó después hacerlo público bajo MIT: GitHub confirmó `isPrivate:false` y licencia MIT; la API sin autenticación confirmó `visibility:public`. Reportes privados de vulnerabilidades habilitados, Actions desactivado. No se cambió la preferencia personal del gráfico ni se activó facturación, Pages o Codespaces. Esto no audita ni garantiza el gasto global de la cuenta o de otras sesiones.

## Material conservado sólo localmente

`weights/`, `runs/`, manifiestos y logs de `artifacts/`, `investigacion-modelos/` y los scripts heredados de investigación/descarga no revisados. No borrarlos ni subirlos por hacer `git add .`. Los planes documentan también historia previa, no autorizan por sí solos ejecutar comandos viejos o reiniciar presupuestos.

## Siguiente frontera

Antes de ejecutar candidatos adversarios o declarar operación enterprise, resolver arquitectura de aislamiento real e identidades administrativas externas, con pruebas independientes. El laboratorio y su banco de control ficticio son componentes de preparación, no sustitutos de esa frontera. No pasar a entrenamientos caros, nuevas APIs o despliegue por el mero hecho de que la suite esté verde.
