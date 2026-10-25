"""Цепочка поставок компании: отрасли поставщиков и покупателей, чьи события касаются самой компании.

Единый источник правил для профиля (экспозиции), ранжирования (признак supply_chain) и агента (риски и действия).
Работает только с агрегатами по собственным платежам клиента: отрасль, доля оборота, число контрагентов.
Идентификаторы, названия, суммы и регионы конкретных контрагентов сюда не попадают.

Доля отрасли считается от ИЗВЕСТНОЙ части оборота: у части контрагентов отрасль неизвестна (они вне выборки
кейса), и в реальных данных таких около половины. Неизвестная часть не должна ни занижать долю известных
отраслей до порога, ни создавать ложную уверенность: итоговый вес умножается на уверенность по доле известной части.
"""

MIN_SHARE = 0.15       # отрасль учитывается, если на нее приходится не меньше этой доли известной части платежей
STRONG_SHARE = 0.30    # «большая» доля известной части: такие новости должны конкурировать с новостями своей отрасли
CONF_OFF = 0.1         # известна меньшая доля оборота — сигнал отключен
CONF_LOW = 0.3         # ниже — сильно ослаблен
CONF_FULL = 0.7        # от этой доли известной части — уверенность полная

SIDES = ("suppliers", "customers")
SIDE_WORD = {"suppliers": "поставщиков", "customers": "покупателей"}
SIDE_PAYMENTS = {"suppliers": "платежей поставщикам", "customers": "поступлений от покупателей"}


def known_confidence(known_share: float | None) -> float:
    """Уверенность в сигнале по доле оборота с известной отраслью: 0 (<10%), 0,15–0,5 (10–30%), 0,5–1 (30–70%), 1."""
    if known_share is None or known_share < CONF_OFF:
        return 0.0
    if known_share < CONF_LOW:
        return round(0.15 + 0.35 * (known_share - CONF_OFF) / (CONF_LOW - CONF_OFF), 4)
    if known_share < CONF_FULL:
        return round(0.5 + 0.5 * (known_share - CONF_LOW) / (CONF_FULL - CONF_LOW), 4)
    return 1.0


def side_view(d: dict | None) -> dict:
    """Известная часть платежей стороны: {known_share, items: [{sector, share_known, share_total}]}.

    Читает и новую форму профиля (known_share, share_known), и прежнюю (доля от всего оборота, «unknown» среди отраслей)."""
    d = d or {}
    rows = [r for r in d.get("by_sector") or [] if r["sector"] != "unknown"]
    known = d.get("known_share")
    if known is None:
        known = sum(r["share"] for r in rows)
    items = []
    for r in rows:
        share_known = r.get("share_known")
        if share_known is None:
            share_known = r["share"] / known if known else 0.0
        items.append({"sector": r["sector"], "share_known": share_known, "share_total": r["share"]})
    return {"known_share": known or 0.0, "items": items}


def links(c: dict) -> list[dict]:
    """Отрасли контрагентов, которые учитываются как связь с компанией, по обеим сторонам.

    Отрасль самой компании не считается (ее закрывает признак «ваша отрасль»); порог — от известной части платежей."""
    out = []
    for side in SIDES:
        view = side_view(c.get(side))
        confidence = known_confidence(view["known_share"])
        if confidence <= 0:
            continue
        for item in view["items"]:
            if item["sector"] in ("unknown", c["sector"]) or item["share_known"] < MIN_SHARE:
                continue
            out.append({"side": side, "sector": item["sector"], "share": item["share_known"],
                        "share_total": item["share_total"], "known_share": view["known_share"],
                        "confidence": confidence, "strong": item["share_known"] >= STRONG_SHARE})
    return out


def pct(x: float) -> int:
    return round(x * 100)


def share_text(link: dict) -> str:
    """«30% известной части платежей поставщикам» (+ оговорка, если известна не вся часть)."""
    text = f"{pct(link['share'])}% известной части {SIDE_PAYMENTS[link['side']]}"
    if link["known_share"] < CONF_FULL:
        text += f" (отрасль известна у {pct(link['known_share'])}% оборота)"
    return text
