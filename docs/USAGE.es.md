# Laboratorio local de evaluación y control de IA

[Portada internacional](../README.md) · [Estado y evidencia](../ESTADO.md)

Guía operativa preservada al preparar el README internacional. Ejecuta los comandos desde la raíz del repositorio, no desde `docs/`.

**Software experimental local, no un sistema enterprise terminado ni una garantía de contención de IA.** Evalúa respuestas JSON sobre tareas sintéticas, puntúa pronósticos declarados y prueba autorización transaccional sobre un calendario ficticio. El núcleo no necesita APIs ni modelos externos para ejecutarse.

## Instalación

Python 3.12 y [uv](https://docs.astral.sh/uv/) instalados:

```bash
uv sync --extra dev --locked
uv run --locked laboratorio --help
uv run --locked laboratorio demo-control
uv run --locked python -m pytest -q
```

La primera instalación descarga dependencias de registros públicos; no llama a servicios de IA. `unittest discover` **no** ejecuta esta suite: las pruebas son pytest.

También puede construirse e instalarse el wheel:

```bash
uv build
uv pip install --python /ruta/a/venv/bin/python dist/laboratorio_control_ia-0.1.0-py3-none-any.whl
```

Después de instalar, `laboratorio` y `python -m laboratorio` funcionan fuera del repositorio. El extra opcional `local-model` instala MLX para Apple Silicon; no es necesario para los comandos siguientes y no descarga pesos automáticamente.

## Ejercicios y evaluación

Usa una carpeta de trabajo nueva para no sobrescribir archivos existentes:

```bash
mkdir -p runs/mi-evaluacion
laboratorio cases --seed 17 --per-family 4 > runs/mi-evaluacion/referencias.json
laboratorio cases --seed 17 --per-family 4 --public > runs/mi-evaluacion/preguntas.json
```

Envía sólo `preguntas.json` al modelo. El archivo de respuestas tiene este formato:

```json
[{"id":"17-arithmetic-0","answer":123}]
```

`123` es ilustrativo, no la respuesta de referencia. Puntúa sin ejecutar texto del modelo:

```bash
laboratorio score runs/mi-evaluacion/referencias.json runs/mi-evaluacion/respuestas.json
```

- Las respuestas ausentes permanecen en el denominador y el estado es `INCOMPLETE`.
- `COMPLETE` significa que hubo respuesta para cada caso, **no que sean correctas**.
- El código de salida 0 significa evaluación ejecutada, **no aprobación ni exactitud del modelo**. Inspecciona `accuracy`, `coverage`, `missing`, `by_domain` y `rows`.
- Se rechazan IDs duplicados/desconocidos, campos extra, claves JSON duplicadas y números no finitos. Las respuestas nunca se ejecutan.
- Los hashes identifican entradas, no autentican su origen. `authorizes_actions` siempre es falso.
- Cambiar la semilla no crea un conjunto reservado: el generador y las referencias son públicos. Estas tareas no miden inteligencia general ni eficacia científica.

## Pronósticos y series

```bash
laboratorio forecast-score pronosticos.json resoluciones.json --now 2026-09-19T12:00:00Z
laboratorio backtest observaciones.json --min-train 4 --horizon 1 --seasonal-period 2
```

Un pronóstico requiere exactamente `id`, `question`, `probability`, `issued_at`, `resolve_at`, `resolution_rule`. Una resolución requiere `id`, `outcome` booleano, `resolved_at`, `evidence_url`. Timestamps UTC `YYYY-MM-DDTHH:MM:SSZ`.

Las observaciones son una lista `[{"date":"2026-01-01","value":10}, ...]` con fechas estrictamente ascendentes y equiespaciadas. El horizonte se mide en observaciones, no días.

Brier se calcula únicamente para resoluciones; sin ellas devuelve `null`, nunca un error cero aparente. El baseline binario es p=0.5. Las URLs no se consultan ni se autentican; las fechas declaradas no demuestran registro prospectivo. El backtest compara última observación y baseline estacional sin usar datos posteriores al origen. **No predice pandemias ni valida una cura.**

## Control local ficticio

```bash
laboratorio demo-control
```

Crea una base SQLite temporal y prueba: intent alterado rechazado, replay con el mismo recibo sin duplicar efectos y rechazo tras revocación. La salida declara `synthetic_data:true`, `human_approval_performed:false`, `external_effects:false`, `C1_T02_verified:false`.

La biblioteca `LocalAuthority` liga intent, actor declarado, versión y aprobación dentro de transacciones. **Sus APIs administrativas, reloj, identidad y base de datos deben estar protegidos fuera del módulo.** Pasar un string `authenticated_principal` no autentica a nadie. No expongas estas funciones directamente a un modelo o a internet. Revocar no deshace efectos ya realizados; recuperar un recibo anterior no es una nueva ejecución.

## Runner de inferencia (experimental, sólo desde las fuentes)

`tools/probar_modelo_local.py` supervisa `tools/inferencia_mlx.py`. Para usar un modelo real se necesitan Apple Silicon/MLX, pesos locales aprobados dentro de `weights/` y un manifiesto local `artifacts/modelo-local.json` con `repo`, `revision`, `path` y `files` (SHA-256 por archivo). Esos artefactos **no se publican ni descargan automáticamente**. Esta recuperación verificó el runner con workers falsos; no revalidó los pesos, la inferencia MLX ni entrenamiento.

Una vez validados esos requisitos, el comando operativo es:

```bash
.venv/bin/python tools/probar_modelo_local.py --out runs/nueva-corrida --timeout 60 --per-family 1
```

La salida debe ser nueva y estar dentro de `runs/`; no se admiten symlinks de salida. `--timeout` acepta 30–600 segundos; `LAB_BUILD_DEADLINE` puede acortar el plazo. Se usan reloj civil y monotónico. El código de salida 0 exige worker terminado, todas las respuestas presentes y sin errores de formato; no exige que las respuestas sean correctas.

- SIGTERM/SIGINT y timeout limpian el grupo creado por el runner con TERM, gracia finita, KILL si hace falta y recolección del hijo. No hay `pkill` global.
- Entradas JSON regulares de hasta 2 MB; rechazo de FIFO, symlinks de entrada y UTF-8 inválido. Logs stdout/stderr limitados conjuntamente a 2 MB.
- `state.json` registra `RUNNING`, `FINISHED`, `FAILED`, `TIMEOUT` o `INTERRUPTED`. Es autoritativo sólo cuando el cierre se persistió correctamente. Ante `RUNNING` sin proceso vivo, tratar como corrida incompleta y revisar logs; nunca como PASS.
- Escrituras atómicas por archivo y un reintento de persistencia terminal. No hay transacción atómica entre los dos informes, ni garantía de persistir ante disco averiado, SIGKILL o caída del equipo.
- Los límites son operativos: no son cuotas de disco/memoria del OS ni separación contra candidatos adversarios. Un descendiente que escape del grupo tampoco queda contenido por esta técnica.

## Estado y contribuciones

Consulta `ESTADO.md` para evidencia y pendientes; `PROGRAMA.md` y `RECUPERACION.md` registran la tanda de desarrollo. Los commits son checkpoints reales, no certificaciones de seguridad. No se alteran fechas ni se generan commits vacíos.

Este repositorio no incluye workflows de Actions, Pages, Codespaces, entrenamiento remoto ni aprovisionamiento de pago. Las pruebas se ejecutan localmente. No se garantiza facturación global de una cuenta GitHub ni el precio futuro de terceros. En un repo privado la visibilidad del gráfico depende de la opción personal de mostrar contribuciones privadas.

No se versionan `.env`, credenciales, pesos, datos privados, bases SQLite ni `runs/`. Los informes de investigación y los scripts heredados de investigación/descarga permanecen locales hasta una revisión específica; no son dependencias del núcleo instalable. Sólo se incluyen los dos scripts de inferencia/supervisión descritos arriba. El wheel distribuye el núcleo; el sdist también incluye herramientas y pruebas, pero nunca pesos ni resultados privados.

## Antes de producción

Faltan, entre otros: autenticación y autorización externas, aislamiento OS y separación real de candidato/evaluador, interfaz operativa, observabilidad protegida, despliegue y recuperación verificados, pruebas de carga, evaluación reservada y validación humana/científica. No hay certificación enterprise, censo mundial de agentes, entrenamiento demostrado ni garantía de evitar catástrofes.
