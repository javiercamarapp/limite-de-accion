# Registro local de experimentos

`python -m laboratorio.experiment_registry` conserva manifiestos versionados de entradas, resultados, código y configuración. No ejecuta artefactos ni modelos y no abre red. Un hash demuestra integridad respecto a ciertos bytes, no autenticidad, permiso, calidad científica ni aislamiento.

## Flujo

Use rutas absolutas físicas (sin symlinks ni componentes `.`/`..`); los archivos que proporcione deben ser sintéticos o estar autorizados por su propietario.

```sh
python -m laboratorio.experiment_registry init /ruta/fisica/nueva/registro
python -m laboratorio.experiment_registry append /ruta/fisica/nueva/registro --spec /ruta/fisica/spec.json
python -m laboratorio.experiment_registry show /ruta/fisica/nueva/registro
python -m laboratorio.experiment_registry check /ruta/fisica/nueva/registro --spec /ruta/fisica/spec.json
python -m laboratorio.experiment_registry export /ruta/fisica/nueva/registro --out /ruta/fisica/export-nuevo.json
python -m laboratorio.experiment_registry verify /ruta/fisica/export-nuevo.json --expected-head SHA256_GUARDADO_APARTE
```

`init` exige directorio nuevo. `export` exige archivo nuevo. Cada append publica una versión numerada mediante escritura sincronizada y enlace atómico sin sustituir destinos. Guarda el SHA256 devuelto **fuera** del registro si necesita detectar eliminación de versiones finales: una cadena truncada puede ser internamente coherente. `verify` sin `--expected-head` verifica sólo coherencia interna, no completitud contra una copia anterior. El argumento requiere 64 caracteres hexadecimales reales, no el marcador del ejemplo.

## Especificación

```json
{
  "experiment_id": "ejemplo_01",
  "source": "synthetic",
  "configuration": {"profile": "base", "seed": 17},
  "inputs": [{"name": "cases", "path": "/ruta/fisica/cases.json"}],
  "results": [{"name": "answers", "path": "/ruta/fisica/answers.json"}],
  "code": [{"name": "worker", "path": "/ruta/fisica/worker.py"}]
}
```

No se aceptan hashes declarados como sustitutos de archivos: se leen los bytes reales y se calcula SHA256. No se conservan contenidos ni rutas absolutas de artefactos en manifiestos, sólo nombres, tamaños, hashes y estados. `source: authorized` es una declaración del operador, no una autorización comprobada por el programa.

Estados de artefactos: `AVAILABLE`, `MISSING` e `INVALID`. Si faltan resultados, la versión no se presenta como completa. `check` compara los archivos actuales con la última versión: `MATCH`, `CHANGED`, `MISSING` o `INVALID`. Nunca autoriza ejecutar ni reenviar acciones.

Límites: 16 artefactos, 2 MB por archivo, 64 KB por manifiesto, 256 versiones y profundidad JSON limitada. Inputs/code deben estar presentes en la especificación; archivos ausentes quedan registrados como ausentes. Se rechazan JSON ambiguos/no finitos y archivos especiales/symlinks/hardlinks; claves o patrones reconocibles de secretos se excluyen. Este filtro es heurístico: no garantiza detectar todo secreto ni autoriza introducir información privada.

La cadena no impide que un proceso del mismo UID manipule los archivos y recalcule hashes. No ofrece firma, timestamp externo, revisión humana ni evaluación reservada. Un staging residual o una secuencia de versiones inesperada exige recuperación del operador; no se borra automáticamente. No se admite descartar un fallo para fabricar una versión aprobada.

## Pruebas

```sh
python -m pytest -q tests/test_experiment_registry.py
```

Incluyen hashes reales, cambios de archivos, estados ausentes/invalidos, publicación sin reemplazo, entradas especiales, límites y truncamiento frente a un head guardado aparte. Los casos son sintéticos; no se entrena ningún modelo.
