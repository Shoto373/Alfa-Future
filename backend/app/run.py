"""Точка входа образа backend: ROLE=api (по умолчанию) — HTTP API, ROLE=worker — фоновый воркер.

Один образ для обоих процессов; роль задается переменной окружения в compose.
"""

import os
import sys

import uvicorn

from app import observability
from app.worker.runner import Worker


def main() -> int:
    role = os.environ.get("ROLE", "api")
    if role == "worker":
        observability.configure_logging()
        worker = Worker()
        worker.handle_signals()
        worker.run()
        return 0
    if role == "api":
        # Логи uvicorn — тем же JSON-форматом через корневой логгер; журнал доступа пишет сам API (с request_id).
        observability.configure_logging()
        # WEB_CONCURRENCY — процессов API в контейнере: Python исполняет код в одном потоке, и под нагрузкой
        # экземпляр упирается в одно ядро. Каждый процесс держит свою копию новостей и embedding-модели (~0,5 ГБ).
        uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_config=None,
                    access_log=False, workers=int(os.environ.get("WEB_CONCURRENCY", "1")))
        return 0
    print(f"Неизвестная роль ROLE={role}: api или worker", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
