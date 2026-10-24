"""Таксономия тем новостей и словари для классификации на правилах.

Ключи тем общие для новостей, базы знаний банка и чувствительности секторов.
Словари — основы слов (стемы) в нижнем регистре; совпадение ищется по началу слова.
С SPR4-00 словари — данные: backend/config/sectors/topics.yaml и language.yaml (или версия, опубликованная
аналитиком). Здесь — те же объекты из app.domain_config.runtime: смена версии видна без перезапуска.
"""

from app.domain_config import loader, runtime
from app.domain_config.runtime import (ACTORS, BANK_OF_RUSSIA, CENTRAL_BANK_WORDS, COUNTRY_STEMS, DIRECTION_STEMS,
                                       FOREIGN_CENTRAL_BANKS, FOREIGN_CURRENCY, FOREIGN_DIRECTION, RUBLE_DIRECTION,
                                       SANCTIONS_DIRECTION, SECTOR_STEMS, TOPIC_MEANINGS, TOPICS)

if not runtime.signature():
    loader.load_files()

__all__ = ["ACTORS", "BANK_OF_RUSSIA", "CENTRAL_BANK_WORDS", "COUNTRY_STEMS", "FOREIGN_CENTRAL_BANKS", "DIRECTION_STEMS", "FOREIGN_CURRENCY", "FOREIGN_DIRECTION", "RUBLE_DIRECTION",
           "SANCTIONS_DIRECTION", "SECTOR_STEMS", "TOPIC_MEANINGS", "TOPICS"]
