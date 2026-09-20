# Importador offline de evidencia

Este módulo copia archivos UTF-8 explícitos a un directorio local privado nuevo.
No visita las URL, descarga, invoca APIs, ejecuta contenido ni interpreta instrucciones
incluidas en las fuentes. No busca archivos recorriendo directorios de investigación.
`source_kind` y `captured_at` son declaraciones del operador; no acreditan permisos,
procedencia, fecha real de captura ni autorización para acciones externas.

## CLI

Con el paquete instalado en el entorno Python activo:

```sh
python -m laboratorio.evidence_import import --spec /ruta/spec.json --out /ruta/bundle-nuevo
python -m laboratorio.evidence_import show /ruta/bundle-nuevo
python -m laboratorio.evidence_import verify /ruta/bundle-nuevo
```

`--spec`, `--out` y el directorio de consulta admiten rutas absolutas o relativas
al directorio de trabajo, sin componentes `.` ni `..`. Los padres deben existir
y no ser enlaces simbólicos. En sistemas donde `/tmp` es un enlace, se debe usar
su ruta física. El importador no resuelve enlaces automáticamente.

Éxito: JSON en stdout y código 0. Error: JSON genérico en stderr y código 2,
sin contenido ni rutas locales. No se implementa exportación adicional.

## Especificación exacta

```json
{
  "sources": [
    {
      "id": "ejemplo-1",
      "title": "Ejemplo sintético",
      "url": "https://example.org/articulo",
      "captured_at": "2026-09-18T12:00:00Z",
      "source_kind": "synthetic",
      "path": "/ruta/fisica/explicita/articulo.txt"
    }
  ]
}
```

Todos los campos mostrados son obligatorios; cualquier campo adicional se rechaza,
incluidos hashes proporcionados por la entrada. Reglas:

- JSON UTF-8 sin BOM, claves duplicadas, NaN, Infinity ni números desbordados.
  Máximo 65.536 bytes (64 KiB), profundidad 12; los objetos tienen como máximo
  128 claves y las cadenas, como techo general, 4.096 caracteres.
- `sources`: entre 1 y 16 entradas, con identificadores únicos.
- `id`: 1–64 caracteres ASCII alfanuméricos, guion o guion bajo;
  comienza por carácter alfanumérico.
- `title`: 1–256 caracteres, no vacío ni formado sólo por espacios.
- `url`: máximo 2.048 caracteres, HTTP(S) absoluta con host IDNA (etiquetas DNS validadas),
  IPv4 o IPv6 entre corchetes y puerto válido cuando se especifica; sin userinfo, espacios, controles ni barras invertidas.
  Se rechazan parámetros reconocibles de credenciales en query y fragmento,
  incluso con codificación porcentual habitual. También se rechaza DEL codificado,
  autoridades con caracteres inválidos y texto sobrante después de un IPv6.
- `captured_at`: fecha válida UTC exacta `YYYY-MM-DDTHH:MM:SSZ`, declarada
  por quien prepara la especificación. Puede ser diferente de `imported_at`,
  registrado con el reloj UTC local durante la importación.
- `source_kind`: exactamente `public`, `synthetic` o `authorized`.
- `path`: ruta absoluta a un archivo regular local, máximo 4.096 caracteres,
  sin componentes `.` o `..`. No se admiten enlaces simbólicos en ningún
  componente, enlaces duros, FIFO, dispositivos ni directorios como fuentes.
  Se excluyen nombres habituales de archivos de credenciales.
- Cada fuente: máximo 1.048.576 bytes (1 MiB). Total: máximo 16.777.216 bytes
  (16 MiB). Se validan UTF-8 y límites antes de crear el destino.

Los metadatos no admiten controles, rutas locales reconocibles ni patrones de
secretos. El filtro reconoce rutas después de delimitadores como `=`, `(`,
comillas o `:`, incluidas rutas Windows y `~/…`; aparta referencias HTTP(S)
para no confundir sus rutas de URL con archivos locales. También se inspeccionan los bytes de cada snapshot: claves privadas
PEM, claves AWS, tokens con prefijos habituales de OpenAI/GitHub y asignaciones
como `api_key=...`, `password=...` o `token=...` de longitud reconocible,
incluidas claves entre comillas en JSON, y credenciales `Bearer` reconocibles.
Es una heurística: puede rechazar datos inocuos y omitir secretos. No es un
detector perfecto ni una herramienta para anonimizar documentos. Quien importa
debe aportar únicamente datos públicos, sintéticos o autorizados y revisar que
no contengan secretos. El manifiesto no conserva `path`; los snapshots conservan
los bytes originales, por lo que pueden contener referencias locales escritas
dentro del propio documento. Las fuentes originales nunca se escriben.

## Persistencia e integridad

Se crea el destino con modo 0700 y archivos con modo 0600, sujetos a restricciones
adicionales de la umask. La creación falla si el destino ya existe. Se conserva
el descriptor del padre durante toda la publicación; el directorio nuevo se abre
relativo a ese descriptor, con `O_NOFOLLOW`, sin recorrer de nuevo la ruta desde
la raíz. Se cotejan dispositivo/inodo mediante `stat(..., follow_symlinks=False)`
y `fstat`, y se exige un directorio vacío antes de escribir. Las comprobaciones
del ancla se repiten antes de cada escritura/publicación y al terminar; también
se rechazan ancestros observados como symlinks. Una sustitución detectada antes
de escribir no recibe snapshots, manifiesto ni marcador de fallo.
Cada fuente se guarda como `source-NN.txt`; `manifest.json` contiene únicamente:

```text
{
  "manifest": {
    "schema_version": "evidence-bundle.v1",
    "imported_at": "...Z",
    "evidence_verified": false,
    "sources": [{id, title, url, captured_at, source_kind,
                 snapshot, size, sha256}, ...]
  },
  "sha256": "hash SHA-256 del objeto manifest canónico"
}
```

`size` es un entero de bytes, nunca booleano. Cada `sha256` de fuente se calcula
sobre sus bytes reales. El hash del manifiesto cubre también los metadatos; su
representación canónica usa `json.dumps(sort_keys=True, separators=(',', ':'),
ensure_ascii=True, allow_nan=False)` codificado en UTF-8. Máximo 64 KiB para el
archivo de manifiesto. Los nombres de snapshot son relativos, fijos y validados;
el bundle puede moverse a otra ruta sin depender de sus fuentes originales.

La escritura usa creación exclusiva, bucles de escritura y `fsync`. El manifiesto
se publica mediante un enlace atómico que falla si ya existe el nombre final,
seguido de eliminación del temporal y sincronización de directorios. No usa
reemplazo de archivos existentes. El enlace temporal no forma parte de un bundle
completo: mientras exista, los lectores rechazan el estado parcial.

Se falla toda la importación si falta una fuente o alguna entrada es inválida:
antes de escribir, esto no crea el destino. Un error de E/S posterior puede dejar
un directorio parcial, snapshots, `.manifest.pending` o un manifiesto completo;
no se emite éxito ni `PASS`. La ruta de error no borra recursos: en particular,
nunca hace `stat` seguido de `unlink` del manifiesto publicado. Intenta crear
`.failed` con `O_EXCL`, sincronizando archivo y directorio mediante el descriptor
retenido. Los lectores rechazan ese marcador, incluso cuando los snapshots y el
manifiesto están completos y sus hashes coinciden. Si el marcador ya existe,
no se sobrescribe; si su creación o sincronización falla, se informa
`IMPORT_FAILED_UNCERTAIN`, sin afirmar persistencia ni éxito. El marcador queda
en el directorio retenido, no en un reemplazo que aparezca en su nombre anterior.
No se reintenta sobre ese directorio: se debe revisar el parcial y usar otro
destino nuevo. Las consultas no crean, reparan ni eliminan nada.

`show` y `verify` validan el esquema, vuelven a leer y hashear todos los snapshots
y rechazan faltantes, modificaciones, enlaces, temporales y archivos adicionales.
La enumeración usa `scandir`: admite como máximo 17 entradas y se interrumpe al
observar la 18, sin materializar un `listdir` ilimitado. Antes de devolver éxito,
la importación ejecuta las mismas comprobaciones de contenido mediante el fd
retenido, coteja el informe con el esperado y vuelve a comprobar el ancla.
El informe de éxito dice `integrity: "MATCH"`, `evidence_verified: false` y
`authenticity_verified: false`. Integridad significa coherencia de esos bytes
con el manifiesto durante la lectura. No significa autenticidad, veracidad,
licencia válida ni consulta de las URL. La misma UID puede modificar documentos
y recalcular todos los hashes; no existe firma, anclaje externo, prueba de fecha
ni aislamiento frente a ese actor. Tampoco se garantiza una vista atómica frente
a escritores concurrentes hostiles. Una misma UID maliciosa aún puede sustituir
nombres entre observaciones, incluso entre `mkdir` y el primer `stat`, alterar
archivos tras la última lectura, retirar el marcador o interferir con el temporal
durante la publicación normal. Conservar descriptores y comprobar identidades
reduce las carreras observables; no constituye aislamiento total de TOCTOU.
Disco lleno, errores persistentes, terminación abrupta o pérdida de energía pueden
impedir registrar o hacer durable el fallo: un proceso terminado no ejecuta el
manejador que crea `.failed`. Estas condiciones extremas no están certificadas.
No se declara estado de modelo ni C1-T02.

## API pública para una interfaz de consulta

```python
from laboratorio.evidence_import import (
    EvidenceImportError, import_bundle, show_bundle, verify_bundle,
)

# Única operación de escritura; requiere una solicitud de importación explícita.
informe = import_bundle(spec_path, out_path)

# Para un futuro operations_status: sólo lectura, sin reparación ni importación.
try:
    informe = show_bundle(bundle_path)  # verify_bundle tiene el mismo contrato
except EvidenceImportError:
    estado = "NO_DISPONIBLE_O_INVALIDO"
else:
    estado = informe["integrity"]      # "MATCH", nunca prueba externa
    fuentes = informe["manifest"]["sources"]
    assert informe["evidence_verified"] is False
```

Las tres funciones aceptan `str` o `Path` y retornan un diccionario serializable
con `manifest`, `sha256`, `integrity`, `evidence_verified` y
`authenticity_verified`. Las dos últimas propiedades son siempre `False`.
Los errores operativos y de validación se convierten en `EvidenceImportError`
(subclase de `ValueError`) con mensajes genéricos; no se retornan informes de éxito
parcial. La interfaz debe presentar metadatos como texto no confiable, no abrir
URL automáticamente y no tratar `source_kind` como permiso para otra acción.
La consulta lee hasta 16 MiB y no devuelve el contenido de los snapshots.

## Comprobación local

```sh
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -B -m pytest -p no:cacheprovider tests/test_evidence_import.py -q
```

Las pruebas usan archivos reales y procesos CLI que importan desde el `src` del
clon. Cubren reapertura, portabilidad, lectura sin reparación, alteración y
faltantes, metadatos forjados, límites, enlaces/FIFO, secretos, contenido con
instrucciones y fallos de publicación/sincronización. No contienen skips.


## Registro histórico de la segunda construcción — 2026-09-19

Las rutas `.l05`, `.v25` y `.evidence-*` de esta sección identifican artefactos privados de revisión, no archivos distribuidos. Para reproducir las regresiones utilice la suite pública anterior; el intérprete `../.venv/bin/python` mencionado abajo pertenecía al entorno de auditoría.

Se leyeron la revisión independiente y `AUDIT.es.md`/`repros.py` de `.v25` sin
modificar ni ejecutar sus artefactos. Cambios de fuentes limitados al módulo,
su archivo de pruebas y este documento; las 64 pruebas previas se conservaron
sin editar. No se usaron Git, red, Docker, agentes ni instalaciones.

| Hallazgo | Corrección y regresión local |
| --- | --- |
| `archivo=/Users/alice/private/customer.csv` | Rechazo por contexto; cinco casos de delimitadores/rutas y controles positivos con URLs. |
| `https://exa\|mple.org/x` | Validación IDNA/IP, etiquetas y autoridad IPv6; controles HTTP, IPv4, IPv6 e IDNA válidos. |
| Sustitución de directorio | Apertura relativa al padre retenido, identidad antes de escritura, relectura final y comprobación del ancla. Renombrados reales del destino, padre y ancestro; alteración de snapshot y archivo extra. |
| Limpieza `stat→unlink` | Se elimina el borrado del manifiesto en errores. Regresión de reemplazo entre `stat` y `unlink`, marcador exclusivo y rechazo de manifiestos completos tras fallos tardíos. |

Evidencia ejecutada con `../.venv/bin/python -B`, `PYTHONPATH=src`,
`PYTHONDONTWRITEBYTECODE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` y
`-p no:cacheprovider`:

- Primera pasada válida, antes de corregir fuentes: **19 failed, 72 passed**;
  las 64 originales pasaron. Fixtures reales: `.evidence-second-red/`.
  Un intento previo tuvo errores de preparación porque no existía `runs/`;
  no se contó como evidencia roja.
- Primera corrección: **91 passed** en 4,58 s (`.evidence-second-green/`).
- Casos adicionales: **1 failed, 99 passed**; el fallo reprodujo un ancestro
  sustituido por symlink (`.evidence-second-edge-red/`).
- Tras corregir ese caso: **100 passed, cero skips**, 4,39 s;
  fixtures preservados en `.evidence-second-final/`.
- Para comprobar específicamente el defecto de limpieza, se reprodujo sólo el
  bloque anterior de publicación/cleanup en memoria, sin revertir archivos:
  **1 failed, 99 deselected**. El reemplazo desapareció realmente antes de la
  aserción `manifest.json.exists()` (`.evidence-second-cleanup-red/`). La misma
  regresión pasa con la implementación actual.

Comando de la suite final (usar un destino nuevo para preservar fixtures previos):

```sh
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../.venv/bin/python -B -m pytest -p no:cacheprovider tests/test_evidence_import.py -q --basetemp=.evidence-import-check
```

Se mantienen las seis regresiones originales de fallo de `fsync`; dos pruebas
adicionales exigen manifiesto completo conservado y `.failed` explícito en fases
5 y 6. También se comprueban incertidumbre por fallo persistente, colisión del
marcador sin sobrescritura y enumeración limitada sobre 100 extras reales.
Estos resultados son específicos de este clon y esta suite: no se ejecutó ni
se atribuye aquí la suite de 580 del host. No certifican aislamiento de misma UID,
durabilidad frente a pérdida de energía ni detección exhaustiva de secretos.
