"""Оповещения команде в Telegram (тот же бот, что у мониторинга): ежедневный отчет и пороги бюджета AI.

Без TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID ничего не отправляется. Сбой Telegram не влияет на сервис.
"""

import logging
import threading

import httpx

from app import config

logger = logging.getLogger("app.notify")


def send(text: str) -> bool:
    """Отправляет сообщение (HTML). True — отправлено."""
    token, chat = config.telegram_settings()
    if not token or not chat:
        return False
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=15,
                          data={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
        return resp.status_code == 200
    except httpx.HTTPError:
        logger.warning("telegram unavailable")
        return False


def send_async(text: str) -> None:
    """Не задерживает вызов модели, в котором пересечен порог бюджета."""
    threading.Thread(target=send, args=(text,), daemon=True, name="notify").start()
