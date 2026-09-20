# Aplicación local — Límite de Acción 0.2

Interfaz gráfica en español conectada al laboratorio. No es una maqueta, un servicio público ni una consola de autorización humana.

## Abrir

Desde el repositorio, con Python3.12 y uv:

```bash
uv sync --locked --extra dev
uv run --locked limite-app
```

Abre **http://127.0.0.1:8765**. Los datos quedan en `runs/app/`, fuera de Git. Detén el servidor con **Ctrl+C**; vuelve a ejecutar el mismo comando para retomar. También funciona `python -m laboratorio.web_app` con el paquete instalado.

```bash
uv run --locked limite-app --workspace runs/mi-laboratorio --port 8766
# Sólo lectura de un operador ya existente, configurado por CLI:
uv run --locked limite-app --operator-root runs/operador
```

No admite `0.0.0.0` ni escucha en interfaces externas. Un workspace sólo puede abrirse con un servidor a la vez. Un puerto ocupado, permisos inseguros o un workspace inválido impiden arrancar; no se reparan ni borran archivos automáticamente. Usa rutas locales cortas bajo padres confiables: la demo Unix rechaza `/tmp` compartido y rutas de socket demasiado largas. No cambies esos controles para forzar la demo.

## Recorrido desde cero

1. **Evaluaciones:** genera un catálogo; carga el ejemplo sintético o aporta dos arrays JSON propios/autorizados. Escribe un nombre y pulsa «Ejecutar y guardar evaluación». Faltantes, respuestas incorrectas, cobertura y exactitud salen del evaluador real. El ejemplo intencionalmente falla una respuesta y omite otra: no es una ejecución de IA.
2. **Experimentos:** la evaluación crea su registro de entradas, respuestas, resultado y código. «Verificar» comprueba hashes; exporta el registro con su cabecera. Integridad no acredita autenticidad externa ni que el registro no se haya sustituido entero.
3. **Pronósticos:** registra pregunta, probabilidad, fechas y regla — admite varias líneas. Resuelve un ID pendiente con resultado y URL declarada. Brier sólo puntúa resoluciones. El ejemplo histórico es retrospectivo y sintético; no prueba prospectividad.
4. **Evidencia:** carga un archivo UTF-8 o pega contenido que puedas aportar; declara título, URL, tipo y fecha. Importa, verifica y exporta. No se visita la URL ni se ejecuta el texto. MATCH no demuestra veracidad, licencia ni captura auténtica.
5. **Control:** ejecuta la demo sintética: Unix/SQLite reales, pérdida de respuesta simulada, `UNKNOWN → CONFIRMED` sin repetir el efecto y rechazo tras revocación. Aprobación, reloj y evento son ficticios, bajo el mismo UID. El operador opcional es sólo lectura: no hay aprobar/despachar autoridad real por HTTP.
6. **Resumen:** muestra registros almacenados, actividad de la página, pendientes y advertencias. Los totales incluyen directorios parciales; no son conteos de pruebas aprobadas. Usa Anterior/Siguiente para recorrer el historial, sin cargar todo en memoria.

La aplicación **evalúa respuestas aportadas**; no invoca MLX, un modelo remoto ni entrenamiento desde el navegador. Los scripts de inferencia opcionales siguen siendo un flujo CLI independiente.

## Datos y descargas

Casos y respuestas deben ser arrays JSON según [la guía del laboratorio](../USAGE.es.md). La aplicación transmite su texto crudo: rechaza duplicados/no finitos y conserva enteros mayores que la precisión de JavaScript. No transforma `100000000000000000001` en `100000000000000000000` antes de evaluar.

Las descargas son JSON con envelope HTTP `{"ok":true,"result":...}`. En una evaluación, `result.cases` y `result.responses` conservan las entradas verificadas. Para reutilizarlas extrae esos arrays con una herramienta que preserve enteros; no subas el envelope completo como si fuera un array de casos. No se reinterpretan números al descargar en el navegador.

Persistencia: directorio privado0700, archivos0600, un lock por workspace y comprobación de archivos/identidades. No hay borrado desde la interfaz. Para respaldar, detén el servidor y copia **el workspace completo**; incluye evidencia, registros y manifiestos. No edites artefactos mientras el servidor está activo. No es una base multiusuario ni una garantía de durabilidad ante fallo eléctrico.

## Límites y errores

- Body HTTP≤2MB; un documento≤1MiB UTF-8; hasta100 trabajos por tipo.
- Hasta20 trabajos por página; presupuesto previo de lecturas y estado JSON≤4MiB. Un registro inválido/excesivo se señala, no se presenta como éxito.
- Hasta100 pronósticos, sujetos a cupo agregado de vista de1MiB. Antes de admitir uno se reserva espacio para su resolución; un rechazo413 no escribe el pronóstico. URL de resolución≤2048bytes UTF-8. Resolver pendientes puede liberar cupo reservado; no se elimina el historial.
- El almacenamiento del ledger tiene límites separados de cantidad/tamaño antes de lectura. Si no puede consultarse, la UI dice «historial no disponible», nunca «no hay pronósticos».
- Nombres/metadata con secretos reconocibles o rutas privadas se rechazan heurísticamente. **No es un detector completo de información sensible:** no aportes credenciales ni datos de terceros sin permiso.
- «Servicio conectado» sólo confirma comunicación con este proceso, no la vida del operador ni la autenticidad de una persona. Al desconectarse aparece un error; recuperar conexión no reenvía operaciones.

Host/Origin estrictos, tokenCSRF de proceso, CSP y assets locales reducen riesgos web. **El token no autentica humanos**. Procesos del mismo UID siguen dentro de confianza; no compartas este servicio mediante proxy, túnel, LAN o publicación pública.

## Verificar

```bash
uv run --locked python -m pytest -q
# Con Chromium instalado en Playwright; crea una carpeta NUEVA:
mkdir -p runs
uv run --with playwright python tools/test_web_browser.py \
  --python "$PWD/.venv/bin/python" --out runs/browser-qa-nuevo
```

La segunda prueba abre y cierra sus propios servidores/Chromium, conserva reportes y capturas y sólo usa datos sintéticos. También sirve contra un wheel: cambia `--python` por el Python de esa instalación limpia. Playwright es una dependencia de pruebas, no del producto. La suite normal no se salta tests silenciosamente por carecer de navegador.

[Contrato HTTP](API.md) · [Diseño y alcance](PLAN.md) · [Verificación](VERIFICACION.md)
