"""Точка входа образа backend: ROLE=api (по умолчанию) — HTTP API, ROLE=worker — фоновый воркер.

Один образ для обоих процессов; роль задается переменной окружения в compose.
"""

import logging
import os
import sys

import uvicorn

from app.worker.runner import Worker


def main() -> int:
    role = os.environ.get("ROLE", "api")
    if role == "worker":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        worker = Worker()
        worker.handle_signals()
        worker.run()
        return 0
    if role == "api":
        uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
        return 0
    print(f"Неизвестная роль ROLE={role}: api или worker", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
