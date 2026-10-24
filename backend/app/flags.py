"""Фичефлаги и эксперименты (SPR4-07): раскатка по проценту пользователей и принудительно — для компаний пилота.

Пользователь попадает в процент по стабильному хэшу (ключ флага + id пользователя): тот же человек
всегда видит одно и то же, а разные флаги раскатываются независимо. Эксперимент — флаг с вариантами:
вариант тоже выбирается хэшем, первый вариант — контрольный. Значения по умолчанию — в FLAGS;
оператор меняет процент и список компаний пилота без деплоя (таблица feature_flags).
"""

import hashlib

from sqlalchemy import select

from app import config, database
from app.models import FeatureFlag

FLAGS: dict[str, dict] = {
    "insight_section_order": {"description": "A/B: порядок разделов разбора — «что делать» раньше последствий",
                              "percent": 100, "variants": ["default", "actions_first"]},
    "digest_format": {"description": "A/B: формат утренней сводки — 5 событий или 3 главных", "percent": 100,
                      "variants": ["list", "compact"]},
    "dialog": {"description": "Диалог с разбором (SPR4-05)", "percent": 100},
    "bank_offers": {"description": "Предложения банка по потребности и связь с менеджером (SPR4-06)", "percent": 100},
}


def _bucket(*parts: str) -> int:
    return int(hashlib.sha256(":".join(parts).encode()).hexdigest()[:8], 16) % 100


def settings() -> dict[str, dict]:
    """Действующие настройки: значения по умолчанию + изменения оператора + компании пилота из PILOT_COMPANIES."""
    with database.session() as db:
        overrides = {r.key: r.payload for r in db.scalars(select(FeatureFlag))}
    pilot = config.pilot_companies()
    out = {}
    for key, base in FLAGS.items():
        flag = {**base, "companies": [], **{k: v for k, v in overrides.get(key, {}).items() if k in ("percent", "companies")}}
        flag["companies"] = sorted(set(flag["companies"]) | pilot)
        out[key] = flag
    return out


def evaluate(user_id: str, company_id: str | None = None, current: dict[str, dict] | None = None) -> dict[str, dict]:
    """Флаги для пользователя: {ключ: {enabled, variant}}. Выключенный эксперимент — контрольный вариант."""
    out = {}
    for key, flag in (current or settings()).items():
        enabled = (company_id in flag["companies"]) or _bucket(key, user_id) < flag["percent"]
        variants = flag.get("variants")
        variant = None
        if variants:
            variant = variants[int(hashlib.sha256(f"{key}:variant:{user_id}".encode()).hexdigest()[:8], 16) % len(variants)] \
                if enabled else variants[0]
        out[key] = {"enabled": enabled, "variant": variant}
    return out


def variants(user_id: str, company_id: str | None = None) -> dict[str, str]:
    """Варианты экспериментов пользователя — записываются в каждое событие для отчета по вариантам."""
    return {k: v["variant"] for k, v in evaluate(user_id, company_id).items() if v["variant"]}


def save(key: str, percent: int | None, companies: list[str] | None) -> dict:
    if key not in FLAGS:
        raise KeyError(key)
    with database.session() as db:
        row = db.get(FeatureFlag, key)
        payload = dict(row.payload) if row else {}
        if percent is not None:
            payload["percent"] = percent
        if companies is not None:
            payload["companies"] = sorted(set(companies))
        if row is None:
            db.add(FeatureFlag(key=key, payload=payload))
        else:
            row.payload = payload
    return settings()[key]
