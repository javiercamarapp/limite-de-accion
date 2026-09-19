# Operador local Unix/SQLite

`python -m laboratorio.operator_cli` opera exclusivamente un calendario sintético
local mediante las bibliotecas existentes. No ejecuta modelos ni abre red TCP.
No es aprobación de producto, contención C1-T02 ni autenticación humana.

## Configuración y arranque

Desde la raíz del proyecto, con el entorno Python ya disponible:

```sh
export PYTHONPATH="$PWD/src"
OPERATOR_ROOT="$PWD/operator-session"
python -m laboratorio.operator_cli prepare-fixture --root "$OPERATOR_ROOT" \
  --deadline 2027-01-01T00:00:00Z --max-operations 2 \
  --admin-uid "$(id -u)" --dispatcher-uid "$(id -u)" --principal operator_agent
python -m laboratorio.operator_cli serve --root "$OPERATOR_ROOT"
```

El plazo debe estar en el futuro. `serve` permanece en primer plano; use otra
terminal para los siguientes comandos y Ctrl-C para cerrar. Sus dos hilos son
propios y se cierran y esperan al terminar. Un fallo de limpieza no omite los demás recursos; errores tardíos del receptor se revisan después del cierre y no devuelven éxito. Cada espera de hilo tiene un límite de tres segundos; si queda alguno activo, se informa cierre no confirmado y no se cierra su conexión mientras esté en uso. No hay daemon ni reinicio automático.
El proceso debe ejecutarse bajo el UID configurado. Esta versión rechaza UIDs
que difieran del UID efectivo: no cambia usuarios, ownership ni permisos del host.
Una integración con identidades distintas necesita configuración externa y una
revisión separada; no se considera implementada aquí.

Los dos sockets (`a.sock` administrativo y `d.sock` de despacho) usan los roles y
principal de `config.json`, archivo preparado por el operador confiable. El
receptor obtiene el UID par del kernel. Con el mismo UID un proceso puede usar
ambos sockets y modificar archivos: **no hay separación de roles frente a ese
proceso**. El campo heredado `human_uid_N` del receptor sólo identifica un UID,
no demuestra que intervino una persona. Ningún JSON de propuesta puede asignar
el principal del canal ni su rol.

`prepare-fixture` exige un directorio inexistente bajo padres existentes,
confiables y sin symlinks (no use `/tmp`). Crea SQLite privado, un evento ficticio,
`intent.json` y finalmente `config.json`. No crea aprobaciones. Nunca sustituye
una sesión existente. Un fallo parcial deja artefactos para diagnóstico; no se
reciclan ni eliminan automáticamente. No hay comando para reiniciar presupuesto.
El directorio de estado debe ser propio y privado (0700).

## Operaciones explícitas

En la segunda terminal, defina los mismos `PYTHONPATH` y `OPERATOR_ROOT`:

```sh
python -m laboratorio.operator_cli register --root "$OPERATOR_ROOT" \
  --intent "$OPERATOR_ROOT/intent.json"
python -m laboratorio.operator_cli query --root "$OPERATOR_ROOT"
```

El registro entrega un identificador y el snapshot muestra su digest. Aprobar
requiere una acción administrativa explícita y el digest de la solicitud
original recibido por un canal confiable. No copie automáticamente el digest de
una propuesta no confiable: esta CLI no establece ese canal ni verifica humanos.
Para este ejercicio sintético el operador puede comparar el fixture con su
solicitud original antes de introducir el digest.

```sh
python -m laboratorio.operator_cli approve --root "$OPERATOR_ROOT" \
  --intent "$OPERATOR_ROOT/intent.json" \
  --original-digest 'C1.intent.v1:sha256:DIGEST_ORIGINAL_DE_64_HEXADECIMALES' \
  --expires-at 2026-12-31T23:00:00Z
```

El marcador de digest debe sustituirse por el valor real; el literal se rechaza.
Copie el `result` de aprobación en `APPROVAL_ID`. Registrar/reservar/despachar no
invocan aprobación y un token inventado no autoriza un efecto.

```sh
python -m laboratorio.operator_cli reserve --root "$OPERATOR_ROOT" \
  --intent-id fixture_intent --approval-id "$APPROVAL_ID" --operation-id operation_one
python -m laboratorio.operator_cli dispatch --root "$OPERATOR_ROOT" --operation-id operation_one
python -m laboratorio.operator_cli query --root "$OPERATOR_ROOT" --operation-id operation_one
python -m laboratorio.operator_cli receipt --root "$OPERATOR_ROOT" --operation-id operation_one
python -m laboratorio.operator_cli event --root "$OPERATOR_ROOT" \
  --calendar-id fixture_calendar --event-id fixture_event
python -m laboratorio.operator_cli reconcile --root "$OPERATOR_ROOT" --operation-id operation_one
python -m laboratorio.operator_cli revoke --root "$OPERATOR_ROOT"
```

`revoke` invalida aprobaciones anteriores; no deshace efectos confirmados.
`reserve` cuenta incluso operaciones posteriormente rechazadas. Todos los
comandos reabren el mismo estado: plazo y presupuesto deben coincidir con los
persistidos. Cambiar esos valores en `config.json` se rechaza. El reloj UTC del
host es configuración confiable; su retroceso bloquea mutaciones durablemente.
No se afirma timestamp externo confiable ni resistencia a un operador que
reescriba o elimine sus propios archivos.

## Consultas, incertidumbre y errores

`query` abre SQLite con `mode=ro`, sin construir `DurableController`, sin recuperar
`DISPATCHING`, sin observar reloj ni crear estado ausente. Usa una transacción de
lectura consistente. `event` y `receipt` sólo consultan el receptor existente y
no abren el controlador. Una respuesta de recibo `null` no prueba ausencia de
efecto. `reconcile` es una operación explícita que puede persistir confirmación.

Abrir un controlador para mutar recupera `DISPATCHING` como `UNKNOWN`, según la
biblioteca existente. Fallo de transporte deja incertidumbre; no hay reintentos.
Volver a despachar `UNKNOWN` no envía otra operación. Sólo un recibo exacto puede
confirmar reconciliación. Abrir simultáneamente varios controladores puede
adelantar esa recuperación aun con un envío vivo: no se detecta muerte de proceso.

Salida correcta: JSON con `ok: true`, `result` y límites explícitos. Esto indica
que el comando terminó, no que un efecto esté confirmado: revise `status`.
Errores de entrada/almacenamiento/transporte: código de salida 2 y JSON en stderr
con `INVALID_OR_UNAVAILABLE`, `effect_confirmed: false` y
`retry_authorized: false`. El error no demuestra ausencia de efecto. Errores de
sintaxis de argumentos usan los diagnósticos normales de argparse, también código 2.

Entradas JSON: UTF-8 estricto, máximo 65536 bytes, sin claves duplicadas ni números
no finitos; el Intent conserva exactamente su contrato existente. Se rechazan
archivos especiales, enlaces simbólicos/duros y padres no confiables. Archivos
SQLite y sidecars existentes deben ser regulares propios. Se usa el journal
normal de SQLite; una base cambiada externamente a modo WAL se rechaza antes
de conectarse, porque incluso una conexión `ro` podría crear WAL/SHM. Al
reabrir el servicio se rechazan tablas de autoridad ausentes o estado truncado
en lugar de reinicializarlo. No se limpian archivos
ajenos ni sockets preexistentes. Después de muerte abrupta pueden quedar sockets:
el operador debe diagnosticar el proceso y los artefactos; no hay borrado automático.
Estas verificaciones no aíslan un proceso hostil que comparta UID.

## Verificación

```sh
python -m pytest -q tests/test_operator_cli.py
python -m pytest -q
```

Las pruebas integradas abren sockets Unix reales y SQLite persistente, usando
subprocesos CLI benignos esperados y cerrados por cada prueba. Verifican rechazo
sin aprobación, efecto único, revocación, reconciliación por recibo, consultas
sin escrituras, presupuesto y reloj al reabrir, entradas inválidas y cleanup.
La prueba de reconciliación prepara un estado interrumpido alrededor de un efecto
real; no es una prueba de muerte de proceso. Las pruebas no omiten el rechazo
`EPERM` del sandbox ni lo sustituyen por un receptor simulado. Ese rechazo requiere
verificación posterior del host; no permite declarar aprobada la tarea.
