# Ejecución continua autorizada — actualización 2026-09-20 UTC

## Punto de reanudación vigente

- `main` público contiene los cinco incrementos revisados hasta `83171eb`; [verificación de los seis contratos locales](docs/VERIFICATION-20260920.es.md). No confundirlos con entrega enterprise.
- Supervisor original **detenido**, STOP conservado. Continuación supervisada sin reiniciar presupuesto: historial original en `runs/continuo-20260919/state.json`, ejecuciones adicionales en `runs/continuo-20260919/integration/budget.json`. Presupuesto conjunto **agotado: 24/24** después de la auditoría final. No lanzar más agentes ni relanzar el supervisor bajo esta tanda; el deadline original era 04:30:39 UTC y no renueva el contador. No queda un bucle autónomo corriendo.
- Los cambios publicados pasaron revisión técnica separada y ejecución completa del host; restricciones del sandbox no se transformaron en defectos ni en aprobaciones ficticias. Publicación manual autorizada, no auto-push del supervisor.
- Próxima tanda de producto: definir y verificar una topología separada de operador/candidato/evaluador, autenticación humana/H1 y C1-T02; interfaz gráfica y operación/despliegue; observatorio con fuentes reales y evaluación reservada/prospectiva. No activar permisos, servicios pagados, descargas grandes o entrenamiento por inferencia de estos pendientes.
- Preservar `artifacts/`, `investigacion-modelos/`, herramientas heredadas, clones candidatos y evidencias. No reset, force-push, limpieza general ni modificación de otros proyectos.

Las secciones siguientes documentan autorizaciones históricas, no procesos actualmente vivos ni nuevos presupuestos.

## Nueva autorización después de 21:47 UTC

El usuario volvió a pedir dejar un bucle real hasta terminar. La tanda de90min y sus cuatro agentes ya son historia. Rige ahora la sección inicial de `PROGRAMA.md`: máximo6h desde arranque/24ejecuciones, un agente activo, estado durable en `runs/continuo-20260919/state.json`. Tres revisiones iniciales del supervisor consumen parte de ese presupuesto.

Modo conservador: construcción, revisión y verificación continuas en clones aislados `.lNN`/`.vNN`; commits **locales**, sin push automático pendiente de compuerta final. No se atribuye aprobación al último informe del revisor: sus hallazgos se corrigieron y verificaron con regresiones; se conserva explícita la falta de reaprobación final. Esto permite continuar trabajo reversible sin publicar un control pendiente.

Para detener: `touch runs/continuo-20260919/STOP`. Para observar: `.venv/bin/python -m json.tool runs/continuo-20260919/state.json`. Si no existe estado o el PID ya terminó, no afirmar que continúa. No borrar estado/STOP ni relanzar automáticamente; preservar evidencia y presupuesto.

## Tanda anterior (histórico)

El usuario corrigió explícitamente la parada prematura y volvió a pedir construir todo de punta a punta; autorizó además hacer público el repositorio con licencia MIT. Un checkpoint verificado NO termina el encargo completo. Se sigue con el siguiente entregable elegible; sólo detener dependencias por gate real o ejecución por límite de seguridad/presupuesto.

## Presupuesto externo
Inicio 20:17 UTC, deadline fijo **2026-09-19T21:47:00Z**, 90 minutos. Hasta ocho incrementos sustantivos, máximo un constructor simultáneo y un revisor separado; máximo cuatro agentes nuevos en total, ocho minutos por agente, una ejecución por unidad sin reinicios automáticos. Sin compras, nuevas APIs pagadas, entrenamiento masivo o cambios administrativos del host/Docker compartido. Suscripción de construcción existente, no coste monetario medido. Verificaciones Python locales y Docker sólo con procesos inocuos y recursos acotados. No convertir presupuesto agotado en éxito ni renovar el reloj sin instrucción del usuario.

## Estado de partida
Main remoto `6adff1d`; MIT publicado, repo público confirmado por API anónima, reportes privados habilitados y Actions desactivado. Baseline local 189 pruebas. No tocar VEXA ni Bio Humanidad. Trabajo previo sin versionar en artifacts/, investigacion-modelos/ y cuatro scripts de construcción/investigación/descarga: preservado, excluido de publicación.

## Contrato de la siguiente frontera
Se releyeron los capítulos 06 y 14 del blueprint original. Aunque el alcance del laboratorio se amplió, C1 conserva sus invariantes: sockets Unix, identidad del par del OS, roles/usuarios separados, ninguna identidad administrativa o rol concedidos por JSON, calendario ficticio inicializado fuera de la ejecución. No agregar endpoints web ni convertir tokens bajo el mismo UID en supuesto aislamiento canónico. Publicación fue autorizada posteriormente y no activa efectos externos.

## Entregables y verificación
1. **Identidad y receptor Unix:** módulo de transporte local con validación estricta de mensajes, tamaño/timeout, identidad del par obtenida del OS, asignación externa de UID a rol/principal y rechazo de rol/principal inyectado. Canales administrativos y de despacho separados. Inicializar fixtures fuera del servicio, sin endpoint genérico de edición. Pruebas sobre sockets reales en el host para identidad local; separar de pruebas entre UIDs aún pendientes.
2. **Preflight de aislamiento:** no reutilizar imágenes privadas de otros proyectos. Preparar sólo imagen pública mínima fijada y probes inocuos en un contenedor dedicado, sin red, socket Docker ni montajes privados, con usuario no privilegiado, raíz de sólo lectura y límites. Verificar intentos de escritura y separación de canales/UIDs. Un contenedor en la VM compartida NO acredita VM dedicada, ni C1-T02 completo; registrar gate exacto.
3. **Controlador durable:** intenciones registradas antes de despacho, operation_id estable, ausencia de reintento automático tras incertidumbre y consulta/reconciliación sólo lectura. Extender sólo tras interfaz del receptor fijada y pruebas del contrato; no exponer el despacho al solicitante.
4. **CLI operativa y recorrido completo:** inicializar fixture, proponer, inspeccionar, aprobar externamente, despachar, consultar, revocar y recuperar con identidades separadas. Aprobaciones de fixture se etiquetan como sintéticas, nunca como revisión humana realizada.
5. **Laboratorio:** conservar evaluación/pronóstico; priorizar procedencia y reservas verificables antes de adaptación. Investigación/modelos reales sólo con licencias, memoria y plazo establecidos; no nuevo entrenamiento ni grandes descargas implícitas.
6. **Auditar, corregir y publicar:** leer diffs, reproducir objeciones, no debilitar pruebas, correr suite y recorrido, escanear secretos, commits reales a main sin force. Actualizar README/ESTADO sin tachar gates no verificados. CI permanece desactivado.

## Ownership de archivos
Coordinador: planes, docs, integración CLI, pruebas de recorrido y harness Docker. Agente constructor asignado explícitamente: módulos nuevos de identidad/receptor Unix y sus pruebas nuevas; no modificar authority.py, tests existentes ni políticas. Revisor: sólo lectura y temporales, nunca permisos/evaluadores productivos.

## Checkpoint 21:09 UTC

Cuatro agentes nuevos consumidos: constructor Unix, constructor controlador, auditor de sólo lectura y constructor de correcciones. **No lanzar más agentes bajo esta tanda.** El auditor encontró dos fallos; se corrigieron con regresiones y se repitieron pruebas fuera del sandbox. Suite integrada401/401; preflight24/24 y cleanup verificados. Demo Unix/SQLite con UNKNOWN→CONFIRMED sin reenvío y revocación: PASS. La demo host usa mismo UID; no completa el entregable4 con identidades separadas y revisión humana real. Falta distribución/commit de estos cambios y siguientes verificaciones independientes elegibles hasta el deadline fijo.

## Checkpoint 21:32 UTC

Código/auditoría/regresiones en `8e9f652`; distribución limpia y demos instaladas verificadas. Suite final402 sin skips en macOS y Linuxaarch64; Linux requirió un workspace ejecutable para dependencias nativas, sin cambiar pruebas ni perfil noexec del preflight. Dos humos MLX acotados con pesos ya verificados: base0/5 cobertura4/5, typed3/5 cobertura5/5, misma referencia pública; no entrenamiento ni mejora general probada. No hay trabajadores de modelo pendientes.

Presupuesto de agentes agotado4/4; no abrir implementación de seguridad nueva que necesite otra revisión bajo esta tanda. Quedan publicación/verificación remota y recuperación documental dentro del reloj original. Entregable4 sigue parcial: demo host tiene mismoUID; no es operador humano externo ni topología completa. T02 adversarial, VM dedicada y H1 permanecen bloqueados; el laboratorio ampliado NO está terminado por completar esta tanda.

## Criterios que NO se sustituyen por relato
Aislamiento adversarial/VM dedicada, autenticación de una persona real, revisión humana H1, aceptación upstream, resultados científicos, observación mundial o garantía de contención. Fallar un gate no bloquea preparación local independiente, pero impide afirmar que se completó ese gate o ejecutar candidatos adversarios.
