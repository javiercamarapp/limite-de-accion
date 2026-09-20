# Forecast ledger local

Incremento offline para registrar declaraciones binarias y puntuar sus resultados
con `score_binary_forecasts` de `forecasts.py`, sin modificar ese cálculo.
Sólo admite archivos locales explícitos, sintéticos o cuyo uso esté autorizado.
La autorización y procedencia corresponden al operador: el programa no las
certifica. No descarga evidencia, ejecuta texto, invoca modelos ni usa servicios.

## Comandos

Con el paquete instalado en el entorno Python activo (`uv sync --locked --extra dev` en el repositorio):

```sh
python -m laboratorio.forecast_ledger init ./mi-ledger
python -m laboratorio.forecast_ledger add ./mi-ledger ./forecast.json
python -m laboratorio.forecast_ledger show ./mi-ledger
python -m laboratorio.forecast_ledger resolve ./mi-ledger ./resolution.json
python -m laboratorio.forecast_ledger score ./mi-ledger
```

`forecast.json` contiene exactamente un objeto con estos seis campos:

```json
{"id":"demo1","question":"¿Ocurrió el evento sintético?","probability":0.8,"issued_at":"2026-01-01T00:00:00Z","resolve_at":"2026-02-01T00:00:00Z","resolution_rule":"El registro sintético declara el evento al cierre."}
```

`resolution.json` contiene exactamente estos cuatro campos:

```json
{"id":"demo1","outcome":false,"resolved_at":"2026-02-01T00:00:00Z","evidence_url":"https://example.org/synthetic"}
```

Son ejemplos retrospectivos: introducirlos después del cierre no demuestra
predicción prospectiva. `evidence_url` sólo es una declaración; nunca se visita.
No introduzcas secretos en preguntas, reglas o URLs: `show` devuelve el contenido
registrado. Los errores no incluyen rutas, argumentos ni contenido del archivo.

La salida correcta es JSON en stdout y código 0. Un error devuelve código 2 y un
mensaje genérico en stderr, sin JSON de éxito en stdout. `recorded:true` confirma
el registro local, no la veracidad del resultado. No existe opción de reloj en
la CLI, ni comandos de edición o borrado.

## API Python

```python
from laboratorio.forecast_ledger import Ledger

ledger = Ledger("./mi-ledger")
ledger.init()                      # destino nuevo; falla si ya existe
ledger.add("./forecast.json")      # una declaración, sin modificarla
ledger.resolve("./resolution.json")
view = Ledger("./mi-ledger").show()  # reapertura sin inicializar ni escribir
score = ledger.score()
```

Los métodos devuelven diccionarios. Entradas, almacenamiento o reloj inválidos
producen `ValueError` con un mensaje genérico. `Ledger(path, clock=callable)`
permite exclusivamente a fixtures Python inyectar explícitamente un reloj que
retorne UTC canónico; sus resultados son sintéticos, no fechas reales probadas.
En uso normal se toma `datetime.now(timezone.utc)` con resolución de un segundo.

`show` devuelve `forecasts` con `forecast`, `registered_at` y `status`;
`resolutions` con `resolution` y su propio `registered_at`; además de `as_of`,
`clock_regressed`, `evidence_verified:false` y `prospective_validation:false`.
Los estados son `pending`, `overdue` (plazo alcanzado sin resultado) y `resolved`.
El objeto `forecast` conserva exactamente los seis campos del núcleo; la fecha
de registro se almacena aparte, nunca reemplaza `issued_at`.

`score` devuelve `resolved`, `pending` (incluye vencidos), `overdue`, `brier`,
`baseline_brier`, `as_of`, `clock_regressed` y los dos indicadores falsos.
Sólo puntúa resoluciones. Sin resueltos, ambas métricas son `null`. Con resultados,
la referencia constante p=0.5 tiene Brier 0.25, calculado por el núcleo existente.
Para p=0.8, resultado verdadero produce aproximadamente 0.04 y falso 0.64.
Un resultado falso no se convierte en ausencia de resultado ni en éxito.

## Fechas, validación e inmutabilidad

Se exige UTC exacto `YYYY-MM-DDTHH:MM:SSZ`, calendario válido,
`issued_at < resolve_at`, `issued_at <= registro`, y para resoluciones
`resolve_at <= resolved_at <= registro`. Se rechazan IDs duplicados,
resoluciones desconocidas, repetidas o tempranas, campos extra o ausentes,
probabilidades booleanas/no finitas y resultados distintos de `bool`.
Los límites de IDs (64 caracteres ASCII) y textos (4096 caracteres),
probabilidad [0,1] y URL HTTP(S) sin credenciales son los del núcleo.

Cada mutación compara el reloj local con la última fecha registrada. Un retroceso
bloquea escrituras; jamás se usa la fecha declarada para retrofechar el registro.
Las consultas siguen disponibles ante retroceso, informan `clock_regressed:true`
y usan `as_of=max(reloj local, último registro)` para evaluar estados coherentes.
Igualdad dentro del mismo segundo está permitida.

Fechas y estados son metadatos locales, no firmas, sellos de tiempo, ni prueba de
validación prospectiva. El reloj del sistema puede estar mal. El propietario del
filesystem puede manipular archivos o eliminar el final del historial; no hay
ancla externa capaz de autenticarlo. Un resultado declarado puede ser falso.
Siempre se conserva `evidence_verified:false` y `prospective_validation:false`,
incluso si el alta ocurrió antes del plazo.

## Persistencia, seguridad y límites

El destino es un directorio privado (0700), con manifiestos numerados consecutivos
`00000000.json`, etc. (0600). El primero registra versión 1 e inicialización;
los siguientes son altas o resoluciones, con `kind`, `registered_at` y `payload`.
Cada lectura valida estructura, continuidad, cronología y semántica del historial.
No hay SQLite: se rechazan rutas con `:`, incluidas URI y `:memory:`.

Las rutas se recorren mediante descriptores y `O_NOFOLLOW`, incluidos los padres.
Se rechazan `..`, symlinks, FIFO, directorios como inputs y archivos con múltiples
hardlinks. Usa rutas físicas: aliases como `/tmp` que sean symlinks se rechazan.
Los inputs y manifiestos deben ser archivos regulares UTF-8 con JSON estricto;
se rechazan claves repetidas, NaN/Infinity y sustitutos Unicode sin pareja.
Sólo se admiten estos archivos explícitos: no hay búsqueda recursiva de datos.

Límites fijos:

- 32 KiB por input y por manifiesto serializado (incluye metadatos).
- 1000 pronósticos y una resolución por pronóstico: hasta 2001 manifiestos.
- 16 MiB acumulados de manifiestos. Se comprueba tamaño antes de leer, con
  lecturas acotadas al presupuesto restante más un byte de detección.
- La enumeración aborta al detectar la entrada 2002; archivos extra o huecos
  invalidan el directorio. No se recorren subdirectorios.

Cada mutación usa un bloqueo exclusivo del directorio; las consultas usan uno
compartido y descriptores de sólo lectura. La contención falla inmediatamente,
sin esperar indefinidamente; el operador puede reintentar. `show` y `score` no
crean destinos, locks auxiliares, archivos vacíos ni manifiestos.

Se prepara y sincroniza un archivo temporal, se publica con hardlink atómico
sin reemplazo, se elimina el temporal y se sincroniza el directorio. Errores de
validación no escriben. Un fallo antes de publicar conserva todos los manifiestos
anteriores y limpia el temporal. Los fallos posteriores a publicar/fsync pueden
significar que el registro ya existe: consultar antes de reintentar.

Una caída del proceso puede dejar un temporal o una inicialización incompleta:
se rechaza el almacén en vez de ignorar datos desconocidos o reparar en silencio.
No se implementa recuperación automática. La atomicidad corresponde a cada
manifiesto; la creación inicial del directorio y su primer manifiesto son pasos
separados. Conservar el directorio completo permite examinar una interrupción.
Se requiere filesystem local POSIX con `flock`, `openat`, hardlinks y `fsync`;
no se garantizan semánticas sobre NFS ni protección ante escritores externos que
ignoren bloqueos. Las garantías de durabilidad dependen del filesystem/dispositivo.

## Verificación acotada

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src" \
  python -m pytest -q -p no:cacheprovider \
  tests/test_forecast_ledger.py tests/test_forecasts.py
```

Los subprocess de estas pruebas fijan explícitamente `PYTHONPATH` al `src` del
repositorio y verifican la procedencia del módulo. No necesitan `conftest`, plugins,
red ni instalaciones, y no contienen skips. Cubren CLI real, reapertura,
Brier, pendientes, duplicados sin mutación, reloj, fechas, corrupción, archivos
especiales, límites de lectura, publicación fallida y contención del bloqueo.

La suite general del repositorio también contiene pruebas de AF_UNIX. Su bloqueo
por el sandbox no valida ni invalida este ledger: el coordinador debe ejecutar
el baseline de host fuera del sandbox. Este incremento no acredita C1-T02,
validación prospectiva ni un producto completo.
