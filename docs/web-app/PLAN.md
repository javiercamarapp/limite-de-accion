# Aplicación local completa — alcance aprobado el 20-sep-2026

## Meta y límites
Aplicación gráfica local, en español, con flujos reales de evaluación, experimentos, pronósticos, evidencia y demostración de control; persistencia, errores visibles, pruebas de navegador y arranque con un comando. El usuario aprobó expresamente este alcance y ejecución en bucle.

Sin despliegue público, pagos, dependencias de frontend remotas, entrenamiento ni sustitución HTTP de los canales de autoridad Unix. La interfaz consulta un operador opcional configurado al arrancar, pero no ofrece aprobar/despachar efectos sobre él. Sólo puede ejecutar demostraciones sintéticas nuevas y aisladas. CSRF no equivale a autenticación humana.

Nueva tanda independiente: inicio 2026-09-20T01:56:49Z, deadline 04:56:49Z, máximo 12 ejecuciones Codex, una activa, hasta 10min cada una. Máximo tres ciclos de revisión. No reiniciar ni alterar los contadores/STOP de la tanda anterior. Los costes internos de suscripción no están medidos. Publicación manual autorizada, sólo después de revisión/pruebas.

## APIs existentes permitidas
- evaluation.make_cases/public_cases/evaluate — src/laboratorio/evaluation.py.
- experiment_registry.initialize/append/export_registry/verify_export/check_files y lectores limitados — src/laboratorio/experiment_registry.py.
- forecast_ledger.Ledger.init/add/resolve/show/score — src/laboratorio/forecast_ledger.py.
- evidence_import.import_bundle/verify_bundle — src/laboratorio/evidence_import.py.
- operations_status.collect_status — src/laboratorio/operations_status.py.
- control_demo.run_demo — src/laboratorio/control_demo.py (sólo fixtures sintéticos).
- cleanup — tools/probar_modelo_local.py, exclusivamente grupos propios de agentes.

## Arquitectura fijada
Python stdlib HTTP ligado exclusivamente a 127.0.0.1; HTML/CSS/JS sin bundler ni CDN dentro del paquete. Workspace privado y acotado, bloqueo exclusivo de proceso, jobs con IDs generados internamente, sin rutas suministradas por HTTP. Misma UID sigue siendo de confianza. Control sensible mantiene Unix/kernel identity; no backend externo ni cuentas nuevas.

## Pasos
1. Backend de aplicación + contrato HTTP + regresiones, sin modificar el core.
2. Frontend accesible y responsive conectado a esas APIs.
3. Auditoría adversarial de rutas, CSRF/Origin/Host, límites, persistencia y datos no confiables.
4. Probar TODOS los flujos en Chromium real, móvil y desktop, errores y recarga; corregir.
5. Suite completa sin skips, wheel/sdist y arranque instalado, revisión de entrega y GitHub.
6. Dejar instancia local propia arrancada y comunicar URL, comando de parada y límites.

## Terminación observable
Navegador crea evaluación real, encuentra el experimento correspondiente y verifica sus hashes; crea/resuelve un pronóstico retrospectivo sintético; importa/verifica evidencia; ejecuta demo Unix; ve resultados persistentes al recargar. Los errores de inputs y almacenes incompletos no se convierten en éxito. Ninguna interfaz declara humano autenticado, evidencia externa verificada o enterprise completo. No se entrega una maqueta ni sólo consola.
