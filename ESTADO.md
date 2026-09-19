# Estado verificable — recuperación del 19 de septiembre de 2026

## Alcance entregado
Incremento local experimental, no entrega enterprise completa. Repositorio privado: https://github.com/javiercamarapp/limite-de-accion, rama predeterminada `main`. La rama local de construcción es `feat/laboratorio-local`.

## Verificado en esta recuperación

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

- No verifica C1-T02, aislamiento OS o separación adversarial entre candidato y evaluador.
- No implementa autenticación administrativa externa, multiusuario, despliegue, interfaz enterprise, SSO/RBAC, monitorización operativa o recuperación productiva.
- No prueba inferencia o entrenamiento MLX actuales. La sesión anterior dejó pesos y resultados públicos de humo locales; no se reinterpretan como validación presente.
- No hay validación prospectiva, conjunto reservado independiente, curas, prevención pandémica, supervisión mundial de agentes ni contención garantizada de una superinteligencia.
- Los límites de procesos no contienen descendientes que abandonen su grupo ni código con acceso adversarial al mismo usuario. SIGKILL, disco permanentemente averiado y caída del equipo pueden impedir persistir el estado final.
- Un resultado `FINISHED`/`COMPLETE` no es una respuesta correcta ni una autorización.

## GitHub y actividad real

Commits sustantivos, sin fechas alteradas ni commits vacíos:
- `42d568a`: núcleo local instalable, evaluación, pronóstico, calendario transaccional y pruebas CLI.
- `2f6b066`: precisión numérica sin falsos aciertos por redondeo.
- `6758a59`: supervisor, límites, interrupciones, persistencia y regresiones.
- La documentación final queda en el commit posterior, visible mediante `git log`.

Los commits de código llegaron a `main`; GitHub los asocia a la cuenta del usuario. La aparición visual del gráfico puede tardar y, al ser privado el repo, depende de la opción personal de mostrar contribuciones privadas. No se cambió esa preferencia, no se activó facturación ni se configuraron Actions/Pages/Codespaces. Esto no audita ni garantiza el gasto global de la cuenta o de otras sesiones.

## Material conservado sólo localmente

`weights/`, `runs/`, manifiestos y logs de `artifacts/`, `investigacion-modelos/` y los scripts heredados de investigación/descarga no revisados. No borrarlos ni subirlos por hacer `git add .`. Los planes documentan también historia previa, no autorizan por sí solos ejecutar comandos viejos o reiniciar presupuestos.

## Siguiente frontera

Antes de ejecutar candidatos adversarios o declarar operación enterprise, resolver arquitectura de aislamiento real e identidades administrativas externas, con pruebas independientes. El laboratorio y su banco de control ficticio son componentes de preparación, no sustitutos de esa frontera. No pasar a entrenamientos caros, nuevas APIs o despliegue por el mero hecho de que la suite esté verde.
