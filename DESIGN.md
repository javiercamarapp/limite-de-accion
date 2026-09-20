# Límite de Acción — aplicación local

Alcance local aprobado; estas elecciones visuales son defaults reversibles del implementador, no una investigación de competidores ni una certificación de seguridad.

## Dirección
Consola editorial de investigación: precisa, sobria y cálida. Jerarquía clara, navegación lateral oscura, superficies claras, tipografía de sistema sin descargas. No landing comercial ni hero genérico. Nada de métricas inventadas o actividad simulada.

## Tokens
- Fondo #f5f6f8; superficie #ffffff; texto #18222f; secundario #526174; borde #dce2e8.
- Sidebar #131e2b; texto #f1f5f9; acento teal #087f75, hover #05655e.
- Éxito #176b46, aviso #946200, error #b73232, información #285ca0; siempre texto/icono además de color.
- UI: ui-sans-serif, system-ui; títulos 28/22/18px, texto 15px, etiquetas 12px. Datos y JSON ui-monospace. Números tabulares.
- Espacio base 4px: 8/12/16/24/32. Radios 6px para inputs, 10px para superficies.
- Sidebar 224px desktop; contenido hasta 1440px. Móvil: navegación replegable, formularios una columna, tablas con scroll propio, sin overflow de página.
- Movimiento funcional 120–180ms, respeta prefers-reduced-motion. Sin fuentes remotas, trackers ni iconos externos.

## Navegación y estados
Resumen · Evaluaciones · Experimentos · Pronósticos · Evidencia · Control.
Cada sección con título, explicación breve, acción principal real, estado vacío útil y error accionable. Campos con labels, foco visible, diálogo con escape/foco restaurado, botones bloqueados durante envío, avisos aria-live. No insertar contenido de usuario con innerHTML.

## Semántica
«Local / experimental» visible pero no alarma persistente que tape el trabajo. AVAILABLE es legibilidad; CONFIRMED es estado registrado. Mostrar límites en contexto y sección Control. Sin mensajes de autenticación, aislamiento o evidencia verificada que el backend no soporte. Ejemplos sólo mediante acción explícita y etiquetados sintéticos.
