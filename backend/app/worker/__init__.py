"""Фоновый воркер (SPR3-01): все фоновые задачи — отдельный процесс, API их не запускает.

    python -m app.worker        # или ROLE=worker python -m app.run

Очередь — таблица jobs в PostgreSQL (queue.py), расписание плановых задач — schedule.py, сами задачи —
tasks.py. Остановка по SIGTERM/SIGINT: новая задача не берется, текущая доделывается.
"""
