# Recuperación — 2026-09-19

## Responsabilidad
Esta sesión retoma únicamente `~/Proyectos/limite-de-accion`, desde la sesión pi `01a0ba25-cabc-7153-849e-063661676d3a`. VEXA y Bio Humanidad pertenecen a otras sesiones; no modificarlos. Traspaso Bio en el temporal del SO: `RETOMAR-BIO-HUMANIDAD.md`.

## Estado inicial observado
- Rama `feat/laboratorio-local`, sin commits, código previo no versionado preservado.
- No se observaron procesos del laboratorio activos al recuperar.
- `.venv/bin/python -m pytest -q`: **55 passed in 0.14s**.
- El comando antiguo `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`: **0 tests, exit 5**. Las pruebas son de pytest; no es evidencia de éxito.
- `PYTHONPATH=src .venv/bin/python -m laboratorio demo-control`: exit 0; tres comprobaciones verdaderas; `C1_T02_verified:false`.
- `.venv/bin/python -m laboratorio --help`: exit 1, `No module named laboratorio`.

## Tanda recuperada
Se mantiene el deadline original: **2026-09-19T19:17:19Z**. Sin renovación automática. Máximo seis incrementos en esta recuperación, una tarea de construcción activa, como máximo un revisor separado de lectura. No compras, servicios pagados nuevos, despliegue, entrenamiento o descargas grandes. Durante la recuperación el usuario autorizó commits y contribuciones reales en GitHub sin activar cobros; se habilita push al nuevo repositorio privado propio, con Actions desactivado, sin modificar los repositorios de otras sesiones.

Métrica: criterios pendientes de uso local que pasan un comando reproducible, sin degradar los 55 tests de entrada. Expectativas de pruebas existentes protegidas; sólo añadir regresiones. Trabajar sobre archivos propios con copia previa para reversión; nunca `reset --hard` ni limpieza de cambios heredados.

1. Distribución instalable y CLI reproducible fuera del directorio fuente.
2. Pruebas de integración de los subcomandos y errores sin efectos externos.
3. Robustez del supervisor de inferencia frente a interrupción/crash si el tiempo permite; no ejecutar modelos hasta tener presupuesto de proceso y recursos.
4. Documentación de uso, estado factual y límites del paquete.
5. Revisión de contexto limpio y regresión final.

Parar una dependencia ante permisos, seguridad o recursos no verificados; continuar las independientes. Agotamiento tras dos intentos sin evidencia nueva o al vencer el reloj. El presupuesto no mide consumo monetario de la suscripción existente; no se garantiza costo cero de inferencia del asistente.

## Pendientes mayores que no se pueden declarar resueltos
Supervisor OS/aislamiento externo C1-T02, autenticación administrativa real, interfaz operativa y control de acceso, entrenamiento validado, observatorio público integrado, evaluación reservada y validación científica. Los resultados históricos del modelo local son pruebas de humo públicas, no inteligencia general ni contención de una superinteligencia. El timeout importando MLX/transformers de la sesión anterior requiere diagnóstico antes de intentar entrenamiento.

## Historial de vueltas
- Recuperación: baseline y demo verificados; error de runner documental e instalación reproducidos. Evidencia temporal `/tmp/limite-recuperacion-{tests,pytest,install}.txt`, `/tmp/limite-recuperacion-demo.json`.
- Incremento 1: wheel y entrypoint instalables, nueve pruebas CLI adicionales. `uv build` y smoke desde `/tmp` exit 0. `uv lock --offline` exit 0. 64 pruebas pasan. Commit `42d568a`.
- Auditoría 1: revisor de contexto limpio encontró falso acierto por resta int/float (`1e20` frente a `100000000000000000001`). Coordinador reprodujo igualdad False y correct=1. El revisor no pudo correr pytest por limitación de su sandbox; no se atribuye verde ajeno.
- Incremento 2: agente constructor cambió sólo la comparación a Fraction y añadió suite de precisión. Informó rojo 21 fallos / 71 aciertos y verde 92 pruebas nuevas. Coordinador releyó diff/pruebas, repitió repro (correct=0) y suite: **156 passed**. Commit `2f6b066`.
- GitHub: primeros dos commits enviados sin force a `main` de `javiercamarapp/limite-de-accion`, privado; Actions desactivado antes del primer push. Correo existente asociado a `javiercamarapp` comprobado mediante API de un commit previo. No cambios globales de identidad o facturación.
- Incremento 3: agente limitado a `tools/probar_modelo_local.py` y `tests/test_model_watchdog.py`, workers falsos. Agotó sus 240 segundos y fue detenido (exit -15); dejó cambios, sin informe final. No se declara verificado por haber terminado el proceso.
- Tanda anterior cerró por presupuesto/pausa, no por completar el paquete. El usuario volvió a ordenar «continúa el loop». Nueva tanda explícita iniciada 19:46 UTC: máximo 30 minutos, **deadline 20:16:00Z**, seis incrementos, un constructor a la vez y revisiones secuenciales. No más de dos agentes nuevos de 240s por unidad, sin reintentos automáticos. Sin APIs nuevas, servicios de pago, modelos reales ni entrenamiento. Guardias y pruebas de entrada se mantienen; no reiniciar este reloj automáticamente.
- Al retomar no se observaron procesos del runner/inferencia/constructor. Se revisaron los archivos del incremento 3 y se ejecutó suite completa: 169 passed.
- Auditoría 2: señales durante persistencia, lectura/logs ilimitados, fallo terminal dejando RUNNING y omisión de tools en sdist. Agente de revisión separado, sólo lectura; dos reproducciones en memoria y 93 pruebas numéricas/reloj. Tests de procesos impedidos por su sandbox, declarados no ejecutados.
- Incremento 4: constructor limitado al runner y tests nuevos implementó límites de lectura/logs y cierre reconciliado; coordinador corrigió empaquetado. El agente reportó 184 verdes, pero la ejecución del coordinador detectó un FAILED intermitente en timeout. Se mantuvo publicación detenida.
- Corrección adicional: sondeo killpg(0) devolvía EPERM en macOS mientras waitpid aún no anunciaba salida. Reproducción original falló 30/80 veces; primer ajuste aún fallaba 28/80. Segundo ajuste espera brevemente para confirmar salida antes de aceptar EPERM en un sondeo; no silencia señales denegadas de un proceso vivo. Prueba repetida final: **80/80 sin fallos**, cinco regresiones adicionales. Suite final **189 passed in 5.99s**.
- Distribución: primer intento offline de entorno limpio detectó build dependency editables ausente en caché. Instalación normal de dependencias públicas resolvió el requisito sin cambiar el entorno MLX original. `uv sync --locked --extra dev` en entorno temporal y demo instalada exit 0.
- Paquete fuente real extraído bajo Python 3.12: **189 passed in 6.83s**; wheel reconstruido e instalado desde ese sdist, demo fuera del repo exit 0 y caso numérico defectuoso devuelve correct=0. Se inspeccionaron miembros de tar/zip: sin pesos, runs, .env ni investigación local. Evidencia temporal `limite-sdist-check-u7fj_bq1/{tests.log,build.log,install.log,demo.json,precision.log}` en el temporal del SO.
- Commit `6758a59` publicado en main: supervisor y regresiones; escaneo de secretos de ese lote exit 0. Documentación y estado factual preparados para commit propio. No se ejecutaron modelos reales ni se activó bucle de producto adversarial.
