# Programa acotado — laboratorio y control

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

## Parada
Meta verificada del incremento, presupuesto agotado, misma reparación sin evidencia nueva dos veces, necesidad de permiso administrativo/externo, fallo de aislamiento o incertidumbre que invalide el experimento. Nunca renovar presupuesto solo ni convertir agotamiento en éxito.

## Qué no constituye terminación del paquete completo
No basta un reporte, un benchmark, un modelo descargado o un entrenamiento que converge. Contención de superinteligencia futura, curas, censo mundial de agentes y predicción cierta del futuro no son resultados demostrados ni promesas del sistema.
