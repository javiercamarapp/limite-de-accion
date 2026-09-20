# Verificación integrada — 20 de septiembre de 2026 (UTC)

## Alcance

Código publicado hasta `83171eb`, con cinco incrementos sustantivos:

| Commit | Incremento |
|---|---|
| `7605312` | Endurecimiento CLI, recuperación por muerte real del proceso y operador persistente |
| `6d739dc` | Registro versionado de experimentos y ancla opcional guardada aparte |
| `6d8243a` | Historial de pronósticos y puntuación de resultados declarados |
| `c154011` | Importador offline de evidencia con snapshots y hashes reales |
| `83171eb` | Consola JSON/texto de los cuatro almacenes, sólo lectura |

Es un laboratorio local experimental. Completar esta cola no completa el producto enterprise.

## Verificado por el coordinador

- **688 pruebas, cero fallos/errores/skips** en la suite integrada del host macOS.
- **688 pruebas, cero fallos/errores/skips** desde el sdist extraído en una ruta nueva y un entorno Python 3.12 limpio: `uv sync --locked --offline --extra dev`; `python -m pytest -q`.
- **688 pruebas, cero fallos/errores/skips** desde un clon nuevo de `main` público, con dependencias del coordinador y origen de módulos verificado. El entorno de dependencias de este tercer recorrido no era otro entorno limpio.
- `uv build --offline`: wheel y sdist construidos. Módulos nuevos y licencia MIT presentes; sin `runs/`, pesos ni artefactos privados en el wheel inspeccionado.
- Wheel instalado en otro entorno limpio con versiones de dependencias de `uv.lock`; importación comprobada desde `site-packages`, no desde el checkout.
- Recorrido del wheel instalado, con CLI reales y servicio Unix propio: reserva no aprobada rechazada; aprobación **sintética explícita**; un cambio exacto de horario, título conservado y versión 1; redispatch y reconciliación sin segundo efecto; aprobación revocada rechazada. Servicio cerrado mediante SIGINT, exit 0 y sockets propios eliminados.
- En ese mismo recorrido: importación/verificación de evidencia sintética; pronóstico retrospectivo pendiente con Brier `null`, luego Brier 0.64 frente a referencia 0.25; registro de hashes reales de entrada/resultado/código y comprobación con ancla exportada.
- Consola de los cuatro almacenes: 1 `CONFIRMED`, 2 `REJECTED`, presupuesto consumido 3/3; hashes, bytes y mtimes de los almacenes sin cambios por la consulta. Todos los indicadores de autenticación, evidencia externa, validación prospectiva, C1-T02, despacho autorizado y completitud enterprise siguen en `false`.

El harness integral y sus resultados se conservan localmente en `runs/continuo-20260919/integration/`; no se incluyen en las distribuciones. Las regresiones y los comandos de cada módulo sí son públicos.

## Revisiones independientes

Cada incremento pasó revisión en un clon separado. Los fallos AF_UNIX de los sandboxes se separaron de defectos del código: no se relajaron las pruebas ni se atribuyó al revisor la ejecución del host.

Se reprodujeron y corrigieron, entre otros:

- Limpieza del operador que omitía recursos tras el primer error y perdía errores tardíos de trabajadores.
- Comparación `true == 1` en configuración experimental, tipos de ruta sin error controlado y secretos reconocibles en claves de configuración.
- Rutas privadas embebidas en títulos, hosts inválidos, sustituciones observables de directorios y limpieza insegura del manifiesto de evidencia.
- Expresiones SQLite que asignaban memoria antes de los límites, esquemas no canónicos y JSON de intents/recibos fuera de contrato aceptados por la consola.

Las revisiones de cierre no dejaron objeciones bloqueantes en esos alcances. La revisión documental final contrastó XML, distribución y orígenes, y señaló dos pasajes históricos que parecían vigentes y un manifiesto de hashes anterior a la corrección del operador: se aclararon los pasajes y se identificó ese manifiesto como checkpoint previo, conservándolo sin reescribirlo. El código del operador coincide con el clon de cierre revisado. No son certificaciones del producto completo ni autorizaciones para acciones externas.

El presupuesto original quedó agotado en **24/24 ejecuciones**, sin renovación. Se detuvo la tanda; no se dejó un bucle autónomo activo ni se marcó producto completo.

## Fallos de verificación conservados

- La primera instalación offline del wheel falló por caché incompleta de dependencias, incluso con versiones fijadas. La instalación normal de esas dependencias públicas resolvió el requisito. No se descargaron modelos ni se llamaron APIs de IA.
- El primer harness integral asumió erróneamente que un intent incluía `title`. Falló su aserción con `KeyError`, cerró el servicio y se preservó el recorrido. Se corrigió el harness para comprobar que el título original se conserva y se repitió en otro directorio nuevo; no se modificó producto para acomodar la prueba.
- El escáner detectó cuatro cadenas de credenciales **sintéticas de pruebas** antes de publicar evidencia. Se conservaron los mismos valores runtime mediante composición de literales y se repitieron pruebas y escaneo; no se añadió una exclusión del escáner.

## Reproducir

```sh
uv sync --locked --extra dev
uv run --locked python -m pytest -q
uv build --offline
uv run --locked laboratorio demo-durable-control --out runs/mi-prueba-nueva
uv run --locked python -m laboratorio.operations_status --format text
```

La última orden sin rutas muestra `NOT_CONFIGURED`, no un sistema listo. Para el recorrido de almacenes use:

- [Operador](OPERATOR-CLI.es.md)
- [Experimentos](EXPERIMENT-REGISTRY.es.md)
- [Pronósticos](FORECAST-LEDGER.es.md)
- [Evidencia](EVIDENCE-IMPORT.es.md)
- [Estado](OPERATIONS-STATUS.es.md)

## Lo no demostrado

No se volvió a ejecutar en Linux esta suite de 688 pruebas: las 402 pruebas Linux anteriores pertenecen a otro checkpoint. No hay topología productiva con identidades adversariales separadas, C1-T02, VM dedicada, autenticación humana/H1, interfaz gráfica, despliegue ni monitorización productiva. El importador no es un observatorio web automático. Los pronósticos son declarados/retrospectivos; no existe validación prospectiva nueva ni mejora general o adaptación de modelos acreditada. No se confunde GitHub actualizado con producto completo.
