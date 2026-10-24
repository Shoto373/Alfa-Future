"""Отрасли (сектора) по ОКВЭД и их чувствительность к макрофакторам.

Сектор — укрупненная группа видов деятельности, с которой работают
классификатор новостей, ранжирование и агент. Чувствительность описывает,
как тема новости обычно влияет на сектор: знак (+1 выигрывает, -1 проигрывает,
0 — влияние неоднозначно) и короткое объяснение механизма.
С SPR4-00 — данные: backend/config/sectors/sectors.yaml (или версия, опубликованная аналитиком).
"""

from app.domain_config import loader, runtime
from app.domain_config.runtime import OKVED_PREFIXES, SECTOR_NAMES, SECTOR_SENSITIVITY, Sensitivity

if not runtime.signature():
    loader.load_files()

__all__ = ["SECTOR_NAMES", "SECTOR_SENSITIVITY", "Sensitivity", "sector_for_okved"]


def sector_for_okved(code: str | None) -> str:
    if not code:
        return "other"
    # Коды ОКВЭД иерархичны ("46.71.1" ⊂ "46.71" ⊂ "46"), поэтому берем самый длинный префикс.
    code = code.strip()
    matches = [p for p in OKVED_PREFIXES if code.startswith(p)]
    return OKVED_PREFIXES[max(matches, key=len)] if matches else "other"
