# Hallazgos

## Preflight 2026-09-20
- Core actual: 688 pruebas, revisiones y origen instalado acreditados en docs/VERIFICATION-20260920.es.md. No modificar evaluadores/autoridad/controlador para acomodar web.
- Playwright y Chromium disponibles: `uv run --offline --with playwright python ...` abrió Chromium 151.0.7922.34, cerrándolo después. No requiere descarga ni dependencia de producto.
- Node26 disponible para validar sintaxis JS; no hace falta npm/framework/CDN para esta aplicación.
- AF_UNIX de macOS limita longitud de path; demos usarán temporales cortos privados. Sandbox de agentes puede negar bind, las pruebas de red/locales se repiten en host sin relajar expectativas.
- User aprobó aplicación local, no despliegue de pago ni certificación enterprise. HTTP del frontend no sustituye la autoridad Unix.
