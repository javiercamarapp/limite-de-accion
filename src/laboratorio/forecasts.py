"""Evaluación local retrospectiva con stdlib, sin E/S ni efectos externos.

Se admiten listas de hasta 10 000 diccionarios de campos exactos, textos
de hasta 4096 caracteres e identificadores ASCII C1 de hasta 64 caracteres.
Los timestamps son UTC canónicos YYYY-MM-DDTHH:MM:SSZ. Validar estos datos
declarados no autentica su origen ni implementa el bucle autónomo C1.
"""

from datetime import date, datetime
from math import fsum, isfinite
import re
from urllib.parse import urlsplit


_MAX_ITEMS = 10_000
_FORECAST_FIELDS = frozenset(
    ("id", "question", "probability", "issued_at", "resolve_at", "resolution_rule")
)
_RESOLUTION_FIELDS = frozenset(("id", "outcome", "resolved_at", "evidence_url"))
_OBSERVATION_FIELDS = frozenset(("date", "value"))


def _records(value, name):
    if type(value) is not list or len(value) > _MAX_ITEMS:
        raise ValueError(f"{name}: se requiere una lista de hasta {_MAX_ITEMS} elementos")


def _fields(value, expected):
    if type(value) is not dict or len(value) != len(expected) or value.keys() != expected:
        raise ValueError("Registro con campos ausentes, extra o estructura inválida")


def _text(value, name, limit=4096):
    if type(value) is not str or not 1 <= len(value) <= limit or not value.strip():
        raise ValueError(f"{name}: texto vacío, inválido o demasiado largo")
    return value


def _identifier(value):
    _text(value, "id", 64)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) is None:
        raise ValueError("id inválido")
    return value


def _timestamp(value):
    _text(value, "timestamp", 20)
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value) is None:
        raise ValueError("Se requiere timestamp UTC canónico con sufijo Z")
    # fromisoformat comprueba el calendario y conserva una zona UTC consciente.
    return datetime.fromisoformat(value)


def _number(value):
    if type(value) not in (int, float):
        raise ValueError("Se requiere int o float finito, sin bool")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("Número fuera del rango representable") from exc
    if not isfinite(result):
        raise ValueError("Se requiere un número finito")
    return result


def _evidence_url(value):
    _text(value, "evidence_url")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("URL con espacios o caracteres de control")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None):
        raise ValueError("Se requiere URL HTTP(S) absoluta sin credenciales")
    # Acceder al puerto detecta puertos malformados; nunca se consulta la URL.
    if parsed.port is not None and parsed.port == 0:
        raise ValueError("Puerto inválido")


def score_binary_forecasts(forecasts, resolutions, now):
    """Calcula Brier sólo para resoluciones, con referencia constante p=0.5.

    Los pendientes, incluso vencidos, no cuentan como éxito ni como error cero;
    sin resoluciones ambas métricas son None. Exige issue < resolve y issue <=
    now; para cada resolución, resolve <= resolved <= now. Comprueba únicamente
    fechas declaradas: no demuestra registro prospectivo ni ausencia de
    backdating real. No consulta URLs ni verifica resultados o evidencia.
    Entradas inválidas producen ValueError; no se modifican los argumentos.
    """
    _records(forecasts, "forecasts")
    _records(resolutions, "resolutions")
    current = _timestamp(now)
    indexed = {}
    for forecast in forecasts:
        _fields(forecast, _FORECAST_FIELDS)
        identifier = _identifier(forecast["id"])
        if identifier in indexed:
            raise ValueError("Pronóstico duplicado")
        _text(forecast["question"], "question")
        _text(forecast["resolution_rule"], "resolution_rule")
        probability = _number(forecast["probability"])
        if not 0 <= probability <= 1:
            raise ValueError("Probabilidad fuera de [0, 1]")
        issued = _timestamp(forecast["issued_at"])
        resolve = _timestamp(forecast["resolve_at"])
        if not issued < resolve or issued > current:
            raise ValueError("Cronología del pronóstico inválida")
        indexed[identifier] = (probability, resolve)

    seen = set()
    errors = []
    for resolution in resolutions:
        _fields(resolution, _RESOLUTION_FIELDS)
        identifier = _identifier(resolution["id"])
        if identifier not in indexed or identifier in seen:
            raise ValueError("Resolución desconocida o duplicada")
        if type(resolution["outcome"]) is not bool:
            raise ValueError("outcome debe ser bool")
        probability, resolve = indexed[identifier]
        resolved = _timestamp(resolution["resolved_at"])
        if not resolve <= resolved <= current:
            raise ValueError("Cronología de la resolución inválida")
        _evidence_url(resolution["evidence_url"])
        seen.add(identifier)
        errors.append((probability - int(resolution["outcome"])) ** 2)

    return {
        "resolved": len(seen),
        "pending": len(indexed) - len(seen),
        "brier": fsum(errors) / len(errors) if errors else None,
        "baseline_brier": 0.25 if errors else None,
        "evidence_verified": False,
    }


def rolling_naive_backtest(observations, min_train=4, horizon=1, seasonal_period=2):
    """Evalúa retrospectivamente última observación y estacional ingenuo.

    Fechas YYYY-MM-DD estrictas, únicas, ascendentes y equiespaciadas en días;
    valores int/float finitos, sin bool. Parámetros enteros entre 1 y 10 000,
    min_train >= seasonal_period y horizon <= seasonal_period. Cada fila usa
    sólo el prefijo anterior al origen y evalúa un objetivo a horizon
    observaciones, no días. No selecciona modelos ni verifica procedencia:
    esto no es validación prospectiva ni evidencia de capacidad predictiva
    sobre pandemias. Errores no representables como float finito se rechazan
    con ValueError. No modifica entradas ni realiza E/S.
    """
    _records(observations, "observations")
    for parameter in (min_train, horizon, seasonal_period):
        if type(parameter) is not int or not 1 <= parameter <= _MAX_ITEMS:
            raise ValueError("Parámetro entero fuera de rango")
    if min_train < seasonal_period or horizon > seasonal_period:
        raise ValueError("Ventana de entrenamiento u horizonte inválido")
    if len(observations) < min_train + horizon:
        raise ValueError("Historial insuficiente")

    dates = []
    values = []
    step = None
    for observation in observations:
        _fields(observation, _OBSERVATION_FIELDS)
        raw_date = _text(observation["date"], "date", 10)
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date) is None:
            raise ValueError("Fecha ISO inválida")
        parsed_date = date.fromisoformat(raw_date)
        if dates:
            delta = (parsed_date - dates[-1]).days
            if delta <= 0 or (step is not None and delta != step):
                raise ValueError("Fechas no ascendentes, duplicadas o paso irregular")
            step = delta
        dates.append(parsed_date)
        values.append(_number(observation["value"]))

    rows = []
    for train_size in range(min_train, len(values) - horizon + 1):
        target = train_size + horizon - 1
        last_prediction = values[train_size - 1]
        seasonal_prediction = values[target - seasonal_period]
        last_error = abs(values[target] - last_prediction)
        seasonal_error = abs(values[target] - seasonal_prediction)
        if not isfinite(last_error) or not isfinite(seasonal_error):
            raise ValueError("Error absoluto fuera del rango finito")
        rows.append({
            "origin_date": dates[train_size - 1].isoformat(),
            "target_date": dates[target].isoformat(),
            "actual": values[target],
            "last_value_prediction": last_prediction,
            "seasonal_prediction": seasonal_prediction,
            "last_value_absolute_error": last_error,
            "seasonal_absolute_error": seasonal_error,
        })
    n = len(rows)
    # Dividir antes de sumar evita desbordar la suma de errores finitos.
    try:
        last_mae = fsum(row["last_value_absolute_error"] / n for row in rows)
        seasonal_mae = fsum(row["seasonal_absolute_error"] / n for row in rows)
    except OverflowError as exc:
        raise ValueError("MAE fuera del rango representable") from exc
    return {
        "n": n,
        "last_value_mae": last_mae,
        "seasonal_mae": seasonal_mae,
        "rows": rows,
        "prospective_validation": False,
        "horizon_units": "observations",
    }
