"""«Коридор банка» для сценариев (SPR4-02): диапазон прогнозов Альфа-Банка из опубликованных тезисов.

Прогнозы — forecast_values тезисов базы знаний (только актуальные, не stale): ключевая ставка и курс доллара
на горизонт. Коридор — от минимального до максимального прогноза по ближайшему горизонту, с id тезисов.
"""

from app.knowledge import kb

METRICS = {"key_rate": ("key_rate", "%", "Прогноз ключевой ставки Альфа-Банка"),
           "fx": ("usd_rub", "руб./$", "Прогноз курса доллара Альфа-Банка")}


def corridor(scenario: str) -> dict | None:
    if scenario not in METRICS:
        return None
    metric, unit, label = METRICS[scenario]
    points: dict[str, list[tuple[float, str]]] = {}
    for t in kb.all_theses():
        if t.get("stale"):
            continue
        for key, value in (t.get("forecast_values") or {}).items():
            name, horizon = key.split(":", 1)
            if name == metric:
                points.setdefault(horizon, []).append((float(value), t["id"]))
    if not points:
        return None
    horizon = min(points)
    values = points[horizon]
    when = f"конец {horizon[:4]}" if horizon.endswith("-12-31") else horizon
    return {"label": f"{label} на {when}", "horizon": horizon, "unit": unit, "low": min(v for v, _ in values),
            "high": max(v for v, _ in values), "sources": sorted({f"bank:{tid}" for _, tid in values})}
