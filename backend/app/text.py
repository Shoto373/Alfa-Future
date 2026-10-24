"""Очистка недоверенного текста (новости, материалы, вопросы) от строк-инструкций для модели.

Базовый слой: пользуются хранилище новостей (при приеме) и агент (границы доказательств, самопроверка).
"""
import re

INSTRUCTION = re.compile(r"игнориру\w*\s+(?:все\s+)?(?:предыдущ|инструкц)|system\s*(?:prompt|:)|"
                         r"(?:раскрой|покажи|выведи)\s+(?:ключ|парол|системн)|"
                         r"(?:ignore|disregard)\s+(?:all|previous)|ты\s+теперь|"
                         r"(?:объяви|напиши|ответь)\s*[:：]", re.I)


def safe_text(text: str) -> str:
    return " ".join(part.strip() for part in re.split(r"(?<=[.!?])\s+|[\r\n]+", text)
                    if part.strip() and not INSTRUCTION.search(part))
