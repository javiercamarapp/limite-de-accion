# Programa acotado — laboratorio y control

## Tanda web posterior — 20-sep-2026 UTC

La autorización «sí hazlo en loop» abrió una tanda independiente de3horas/hasta12agentes secuenciales, sin cambiar STOP/budget originales. Implementación local0.2: seis vistas conectadas,732tests+22subtests en fuente/sdist y aceptación Chromium desde wheel instalado. Se utilizaron8ejecuciones: construcción, correcciones, tres revisiones y validación independiente de casos conocidos. [Contrato de la tanda](docs/web-app/PLAN.md) y [evidencia](docs/web-app/VERIFICACION.md). El proceso de UI no debe confundirse con un bucle autónomo.

## Estado de la tanda CLI anterior — histórico

La cola de seis incrementos locales está integrada y publicada hasta `83171eb`, con revisiones por componente y 688 pruebas sin skips. La auditoría documental final se ejecutó como llamada **24/24**; sus precisiones históricas se corrigieron. La tanda queda **detenida por presupuesto de agentes agotado**, no como producto enterprise terminado. El supervisor de la sección siguiente quedó `STOPPED`: no se borraron STOP/estado ni se reinició su reloj. El coordinador continuó en primer plano, separando verificación real del host de restricciones AF_UNIX del sandbox, sin relajar tests.

Se mantiene el presupuesto ORIGINAL: máximo 24 ejecuciones, una simultánea, deadline `2026-09-20T04:30:39Z`; las 9 iniciales más ejecuciones posteriores se cuentan en `runs/continuo-20260919/integration/budget.json`. No renovar automáticamente. La publicación MANUAL de incrementos revisados está autorizada por el usuario y se ha realizado; esto no habilita la publicación automática del supervisor.

Métrica alcanzada de la cola: seis contratos locales integrados, sin regresiones observadas; no cantidad de commits artificiales. Hay cinco commits sustantivos de código para esos seis contratos. Las tareas productivas pendientes requieren otra tanda y, donde corresponda, permisos/infraestructura/datos que esta ejecución no acredita. El agotamiento de cola o de presupuesto nunca marca `enterprise_complete=true`. Evidencia y límites: [verificación integrada](docs/VERIFICATION-20260920.es.md).

Lo siguiente conserva la política e historia de arranque, no acredita un proceso todavía activo.

## Autorización vigente: bucle en segundo plano, 19-sep-2026

El usuario volvió a ordenar «dejalo en bucle hasta terminar». Se prepara ejecución real, no una promesa de continuar después de responder. Esta sección sustituye los presupuestos históricos inferiores para esta nueva tanda.

- Supervisor local: `runs/continuo-20260919/loop.py`; política fija y rúbrica en `runs/continuo-20260919/policy.md`.
- Hasta **6 horas desde su arranque y 24 ejecuciones Codex**, incluyendo 3 auditorías iniciales; un agente simultáneo, 15 minutos por ejecución y dos intentos por tarea. Las llamadas internas y el coste monetario de la suscripción no están medidos. Sin nuevas APIs pagadas, entrenamiento, compras, Docker/usuarios del host ni procesos de agentes anidados.
- Cola: endurecimiento/recuperación CLI, comandos operativos persistentes, registro de experimentos, historial de pronósticos, importación de evidencia e interfaz de estado local. Las dependencias bloqueadas no impiden continuar las otras tareas.
- Cada incremento pasa revisión limpia, prueba específica ejecutada, suite completa conservando identidades y sin skips, build y escaneo. Pruebas/autoridad/evaluadores existentes protegidos. Candidatos rechazados se conservan aislados; sin resets ni limpieza del trabajo heredado.
- **Publicación automática deshabilitada.** Tras tres auditorías del supervisor, se corrigieron los hallazgos y se probaron regresiones, pero no se declara una aprobación final ajena inexistente. Se conserva trabajo revisado en commits de clones locales; la publicación tiene una compuerta posterior separada. El checkout original y main remoto no se sustituyen desde el bucle.
- Estado/heartbeat/PID/deadline/best commit: `runs/continuo-20260919/state.json`, creado sólo al arrancar. No reiniciar si existe; no resetear presupuestos. STOP cooperativo: crear `runs/continuo-20260919/STOP`.
- Agotar cola/presupuesto o bloquearse NO significa producto completo. C1-T02, VM dedicada, contención adversarial, H1 y evaluación/adaptación reservada mantienen sus gates.

Lo que sigue documenta fases históricas y no autoriza reiniciar sus relojes.

## Estado
PREPARACION_SUPERVISADA. El usuario autorizó construir y pidió ambos módulos. No existe todavía un supervisor externo verificado: no se activa una corrida de código candidato autónoma ni se presume cumplido C1-T02. Los investigadores de web son procesos de lectura separados, acotados y sin acciones de producto.

## Meta de esta tanda
Primer incremento ejecutable de laboratorio local: contratos de datos estrictos, banco de ejercicios benignos con referencias deterministas, evaluación de archivos de respuesta (sin ejecutar respuestas), registro trazable y puntuación de pronósticos ya resueltos. Investigación contrastada de modelos, adaptación, simulación y observación pública. Mantener explícitos los gates de integración, entrenamiento y aislamiento que sigan pendientes.

## Métrica y guardias
Métrica: criterios de cada incremento satisfechos mediante pruebas repetibles; no maximizar sólo cantidad de tests.
Comando verificado para el paquete actual: `.venv/bin/python -m pytest -q`. Las pruebas son pytest: `unittest discover` no las recoge (0 tests, exit 5 observado en recuperación).
Guardias: sin evaluaciones/exec de texto de modelos; sin tráfico o cuentas de producto; ningún score autoriza acciones; sin entrenamiento clínico no validado; todos los candidatos/forecasts mantienen procedencia y resultados faltantes no son PASS.
No confundir pruebas unitarias de herramientas confiables en preparación con prueba de aislamiento ante un candidato adversario.

## Archivos y reversibilidad
Trabajo únicamente en este repositorio nuevo, rama feat/laboratorio-local. Originales del Escritorio sólo lectura. No borrar trabajo ajeno ni alterar ramas/configuraciones globales.
Cada incremento usa commit/checkpoint local después de verificar; corrección rechazada se conserva como evidencia y se revierte sólo sobre sus archivos propios, sin reset destructivo. Originalmente no push ni publicación. En recuperación del 19-sep el usuario autorizó commits y actividad real en GitHub: sólo push al repositorio privado propio `javiercamarapp/limite-de-accion`, sin Actions ni servicios de pago; no publicar datos, pesos, logs ni credenciales.
Catálogos de expectativas se fijan antes de implementar comportamiento. Nuevas pruebas se agregan con motivación; no se cambian para ocultar un fallo. La protección del evaluador frente a candidatos requiere identidades/entorno externo: pendientes de preflight, no simple chmod o prompt.

## Bucle de construcción actual
1. Seleccionar incremento elegible, definir contrato y prueba.
2. Observar fallo real del comportamiento ausente.
3. Implementar mínimo; ejecutar pruebas y comprobaciones de regresión.
4. Conservar sólo cambio verificado; registrar estado parcial y límites.
5. Solicitar revisión de contexto limpio antes de dar por bueno código crítico.
6. Si un gate falta, parar esa dependencia y avanzar partes independientes.

## Presupuesto
Máximo hasta19:17:19UTC del19-sep-2026 (120min desde preflight), cuatro agentes simultáneos, treinta minutos por tarea y máximo tres reparaciones sin reiniciar reloj. La recuperación aplica un límite más conservador: una tarea de construcción activa y, como máximo, un revisor de lectura; hasta seis incrementos dentro del mismo deadline. Estado y criterios en `RECUPERACION.md`. Sin compras ni nuevas APIs pagadas. No entrenamiento masivo ni pesos grandes sin selección/licencia/recursos establecidos.

## Nueva tanda autorizada tras la pausa
El usuario pidió nuevamente continuar después de vencer el presupuesto anterior. Inicio de recuperación 2026-09-19T19:46Z, fin fijo **20:16:00Z** (máximo 30 minutos), hasta seis incrementos, un constructor activo y revisiones secuenciales; máximo dos agentes nuevos de 240s cada uno. Sin reintentos automáticos, entrenamiento, modelos reales ni servicios pagados nuevos. No se confunde esta autorización del usuario con renovación autónoma. Historial y evidencia en `RECUPERACION.md`.

## Continuación vigente y parada
El usuario corrigió expresamente cerrar al completar un incremento: un checkpoint no equivale a terminar el producto. Continúa con el siguiente entregable elegible. La autorización más reciente incluye repositorio público y MIT; presupuesto, fronteras y entregables vigentes están en `CONTINUACION.md` (20:17–21:47 UTC del 19-sep, 90 minutos, sin renovación automática).
Detener sólo dependencias afectadas por falta de permiso/aislamiento/datos o incertidumbre que invalide el experimento; detener la corrida por presupuesto agotado o dos intentos sin evidencia nueva sobre la misma reparación. Si hay tareas independientes elegibles y presupuesto, seguir. Nunca convertir presupuesto o checkpoint en éxito del paquete completo.

## Qué no constituye terminación del paquete completo
No basta un reporte, un benchmark, un modelo descargado o un entrenamiento que converge. Contención de superinteligencia futura, curas, censo mundial de agentes y predicción cierta del futuro no son resultados demostrados ni promesas del sistema.
