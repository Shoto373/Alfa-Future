"""Фоновый воркер и очередь задач (SPR3-01): два воркера не берут одну задачу, упавшая задача повторяется,
после 5 попыток — dead-letter, задача упавшего воркера возвращается, плановая не дублируется, остановка
по сигналу корректна, API отвечает без воркера, кэш новостей подгружает только изменения."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app import database
from app.models import Job, News
from app.news import store
from app.worker import queue, runner, schedule, tasks


def _job(job_id: int) -> Job:
    with database.session() as db:
        job = db.get(Job, job_id)
        db.expunge(job)
        return job


def test_two_workers_never_take_the_same_job(raw_client):
    ids = {queue.enqueue("llm_sweep") for _ in range(20)}
    with ThreadPoolExecutor(8) as pool:
        taken = [j for j in pool.map(lambda n: queue.claim(f"w{n % 2}"), range(40)) if j]
    assert sorted(j["id"] for j in taken) == sorted(ids), "каждая задача взята ровно один раз"


def test_preview_is_taken_before_queued_cycles(raw_client):
    for _ in range(3):
        queue.enqueue("llm_sweep")
    preview = queue.enqueue("domain_config_preview", {"id": "p"}, max_attempts=1)
    assert queue.claim("w")["id"] == preview, "превью ждет оператор — оно идет раньше плановых задач"


def test_failed_job_is_retried_with_backoff_then_dead(raw_client, monkeypatch):
    job_id = queue.enqueue("broken", max_attempts=3)
    for attempt in range(1, 4):
        with database.session() as db:  # задержка повтора истекла
            db.execute(update(Job).where(Job.id == job_id).values(run_at=datetime.now(timezone.utc)))
        job = queue.claim("w")
        assert job["id"] == job_id and job["attempts"] == attempt
        status = queue.fail(job_id, "RuntimeError: шлюз недоступен")
        saved = _job(job_id)
        if attempt < 3:
            assert status == "queued" and saved.run_at > datetime.now(timezone.utc), "повтор — с задержкой"
            assert queue.claim("w") is None, "до истечения задержки задачу не берут"
        else:
            assert status == "dead" and "шлюз" in saved.error, "после max_attempts — dead-letter с ошибкой"


def test_job_of_crashed_worker_is_taken_again(raw_client):
    job_id = queue.enqueue("llm_sweep")
    assert queue.claim("crashed")["id"] == job_id
    assert queue.claim("other") is None, "аренда еще действует"
    with database.session() as db:
        db.execute(update(Job).where(Job.id == job_id).values(locked_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
    again = queue.claim("other")
    assert again["id"] == job_id and again["attempts"] == 2


def test_scheduled_job_is_queued_once_per_interval(raw_client, monkeypatch):
    monkeypatch.setenv("RSS_REFRESH_MINUTES", "15")
    now = 1_800_000_000.0
    first = schedule.tick(now)
    assert "news_cycle" in first and "llm_sweep" in first
    assert schedule.tick(now + 5) == [], "тот же интервал — повторно не ставится (два воркера, перезапуск)"
    assert "llm_sweep" in schedule.tick(now + 5 * 60)


def test_worker_runs_jobs_and_records_outcome(raw_client, monkeypatch):
    calls = []
    monkeypatch.setitem(tasks.HANDLERS, "ok", lambda payload: calls.append(payload) or {"done": True})
    monkeypatch.setitem(tasks.HANDLERS, "boom", lambda payload: (_ for _ in ()).throw(RuntimeError("сбой")))
    ok, boom = queue.enqueue("ok", {"n": 1}), queue.enqueue("boom")
    worker = runner.Worker("test-worker")
    assert worker.run_one() and worker.run_one() and not worker.run_one()
    assert calls == [{"n": 1}] and _job(ok).status == "done"
    assert _job(boom).status == "queued" and "сбой" in _job(boom).error, "упавшая задача вернулась в очередь"


def test_worker_stops_gracefully_and_returns_untouched_job(raw_client):
    job_id = queue.enqueue("llm_sweep")
    worker = runner.Worker("stopping")
    worker.stop.set()
    assert worker.run_one() is False
    saved = _job(job_id)
    assert saved.status == "queued" and saved.attempts == 0, "задача не начата — попытка не потрачена"
    worker.run(warm=False)  # стоп уже выставлен: цикл сразу завершается
    assert runner.status()["id"] == "stopping"


def test_api_answers_without_worker(client, company):
    meta = client.get("/api/v1/meta").json()
    assert meta["worker"]["alive"] is False and "queue" in meta["worker"]
    assert client.get("/api/v1/feed", params={"company_id": company["company_id"]}).status_code == 200


def test_news_cache_loads_only_changed_records(raw_client, monkeypatch):
    items = store.all_items()
    changed = items[0]
    reads = []
    real = store._read_all
    monkeypatch.setattr(store, "_read_all", lambda db: reads.append(1) or real(db))
    with database.session() as db:  # другой процесс изменил запись и поднял ревизию
        record = db.get(News, changed["news_id"])
        record.payload = {**record.payload, "title": "Изменено другим процессом"}
        store._bump(db)
    store._state.checked = 0  # не ждать интервала перепроверки
    assert store.get(changed["news_id"])["title"] == "Изменено другим процессом"
    assert len(store.all_items()) == len(items)
    assert reads == [], "весь набор новостей не перечитывается"


def test_news_added_by_another_api_instance_is_found_at_once(raw_client):
    """Добавили новость через другой экземпляр API — запрос по ее id сразу ее находит (без ожидания перепроверки)."""
    store.all_items()  # копия в памяти свежая, плановая перепроверка еще не наступила
    item = store.make_item("Другой экземпляр добавил новость о ставке", "Банк России сохранил ключевую ставку.", "Тест")
    with database.session() as db:
        db.add(News(news_id=item["news_id"], published_at=datetime.fromisoformat(item["published_at"]),
                    kind=item["kind"], payload=item))
        store._bump(db)
    assert store.get(item["news_id"])["title"] == item["title"]
