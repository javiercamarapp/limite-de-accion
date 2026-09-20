# Verificación de la aplicación local 0.2 — 2026-09-20 UTC

## Evidencia actual

- Host macOS, Python3.12: **732 pruebas +22 subtests**, cero fallos, errores o skips. `pytest` presenta732; XML cuenta754 al incluir subtests. Se mantiene íntegra la base anterior de688 pruebas.
- Chromium real: evaluación8/10, rechazo de JSON duplicado/no finito, precisión exacta de enteros en formulario/cálculo/descarga, registro experimental MATCH, pronóstico multilínea y Brier0.49, importación/verificación/exportación UTF8, demoUnix con un efecto ficticio y revocación, desconexión/reconexión, escritorio y móvil375/320px, navegación accesible,21registros paginados y persistencia tras parar/reabrir el proceso.
- El script público reproducible es `tools/test_web_browser.py`. Sólo crea datos sintéticos;17registros adicionales se preparan explícitamente porAPI para comprobar páginas, no se atribuyen a clics humanos.
- Sdist extraído físicamente en una ruta corta, con entorno Python nuevo: **732 pruebas +22 subtests**, sin fallos ni skips. Wheel instalado por separado con dependencias bloqueadas: el script Chromium distribuido completó el mismo recorrido y el reinicio del servidor. Se comprobaron assets, entrypoint, orígenes instalados y ausencia de datos privados en el wheel.
- Clon público de esta versión: pendiente de publicación; no se infiere de los otros entornos.

Evidencia local excluida de Git: `runs/web-20260920/integration/`, `runs/browser-source-final/`. La captura distribuida sólo contiene fixtures sintéticos.

## Revisión y correcciones

Tres revisiones técnicas independientes, sin autoridad para publicar ni modificar permisos:

1. Detectó JSON normalizado/redondeado porJavaScript, lecturas incompatibles en exportaciones, igualdad Python que aceptaba boolcomoentero y reglas multilínea rechazadas. Corregidos con pruebas rojo→verde; la segunda revisión reprodujo los cuatro cierres.
2. Detectó acumulación de100 trabajos:794MB leídos y198MBJSON sin advertencia. Se implementaron paginación y presupuestos antes de leer. La tercera revisión recorrió100/100 trabajos; su fixture máximo porpágina leyó7.94MB y emitió1.98MB.
3. Detectó admisión de pronósticos que luego excedían la vista:63registros desaparecían de la consulta y84persistidos impedían resolver. El coordinador corrigió el diseño de admisión: proyección antes de escribir, reserva porpendiente, límites independientes de almacenamiento/vista y mensaje explícito de historial no disponible. Regresión conservada: **3fallos +1PASS antes →4PASS después**; incluye84registros válidos heredados y100cortos resueltos. Esta corrección ocurrió después del tercer informe. Un ejecutor independiente de aceptación —no una cuarta revisión arquitectónica— repitió31tests+22subtests, el repro original y34tests auxiliares:62largos admitidos, el siguiente rechazado antes de escribir,84heredados visibles y resueltos conHTTP200,100cortos resolubles y persistencia. Confirmó los SHA-256 entre fuente/sdist/wheel y no modificó94archivos protegidos. Cerró esos casos, no declaró seguridad global.

El core de evaluación, autoridad y control no se modificó para acomodar elfrontend. La UI no obtiene autoridad de roles declarados porJSON.

## Intentos fallidos conservados

- Primer harness Chromium consultó botones antes de terminar la navegación; se corrigió la espera del breadcrumb, no el producto.
- Un harness intentó ejecutar la demo bajo `/tmp`, rechazado por los padres no confiables del controlUnix. Se trasladó el fixture a una ruta privada, sin debilitar la frontera.
- El harness público usó inicialmente `token` en lugar del contrato `csrf_token`; obtuvo403. Se corrigió el consumidor.
- La primera extracción del sdist quedó en un directorio anidado demasiado largo para AF_UNIX. Se repitió el mismo archivo comprimido en una ruta física corta, sin modificar pruebas ni sustituir sockets.
- Dos fixturesDOM deNode no incluían el enlace accesible y `scrollTo` recién añadidos. Se actualizó su entorno simulado, conservando todas las aserciones. El navegador real ya cubría el comportamiento.

## Qué no demuestra

Sólo se verificó la nueva aplicación en macOS/Chromium; no se atribuyen los402tests históricos deLinux a esta versión. No se ejecutó un modelo nuevo, entrenamiento, una evaluación reservada/prospectiva ni un servicioAI pagado. No acredita verdad de evidencia, autenticación humana, C1-T02, separación adversarial deUIDs, durabilidad ante fallo eléctrico ni producción pública. La demo simula pérdida de respuesta; las pruebasSIGKILL reales permanecen en la baseCLI.
