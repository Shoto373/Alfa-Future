"""Конвейер аналитики банка (SPR3-03): загрузка PDF → распознавание (записанные ответы) → черновики
с проверками → правка → публикация аналитиком. Неподтвержденный черновик не попадает в базу знаний."""

import pytest

from app import config, llm, llm_usage
from app.knowledge import ingest, kb
from app.worker import runner

DEMO = ingest.demo_pdf()  # синтетический демо-обзор (в репозитории — только картинки страниц)
API = "/api/v1/admin/kb"


@pytest.fixture
def operator(client, monkeypatch):
    monkeypatch.setenv("OPERATOR_EMAILS", "owner@example.com")  # сотрудник банка — владелец тестовой сессии
    return client


def _upload(c) -> str:
    r = c.post(f"{API}/documents", params={"name": "Демо_обзор.pdf"}, content=DEMO)
    assert r.status_code == 202, r.text
    return r.json()["doc_id"]


def _process() -> None:
    assert runner.Worker("kb-test").run_one(), "распознавание — задача воркера kb_ingest"


def _by_metric(doc: dict, start: str) -> dict:
    return next(d for d in doc["drafts"] if d["metric"].startswith(start))


def test_only_bank_staff_can_use_the_review_screen(client):
    assert client.get(f"{API}/documents").status_code == 403
    assert client.post(f"{API}/documents", params={"name": "x.pdf"}, content=DEMO).status_code == 403


def test_upload_recognize_and_automatic_checks(operator):
    doc_id = _upload(operator)
    again = operator.post(f"{API}/documents", params={"name": "копия.pdf"}, content=DEMO).json()
    assert again == {"doc_id": doc_id, "status": "queued", "created": False}, "тот же файл не распознается повторно"
    _process()
    doc = operator.get(f"{API}/documents/{doc_id}").json()
    assert doc["status"] == "ready" and doc["date"] == "2026-10-20" and "записанный ответ" in doc["model"]
    assert len(doc["drafts"]) == 11 and all(d["status"] == "draft" for d in doc["drafts"])
    inflation = _by_metric(doc, "инфляция")
    numbers = next(c for c in inflation["checks"] if c["name"] == "numbers")
    assert not numbers["ok"] and numbers["missing"] == ["6.5"], "ошибка распознавания числа поймана проверкой"
    rate = _by_metric(doc, "ключевая ставка на конец 2026")
    assert all(c["ok"] for c in rate["checks"]), rate["checks"]
    assert rate["supersedes_candidate"] == "rate-05", "прежний прогноз ставки — кандидат на замещение"
    image = operator.get(f"{API}/documents/{doc_id}/pages/1/image")
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"


def test_draft_is_not_bank_position_until_approved(operator):
    doc_id = _upload(operator)
    _process()
    rate = _by_metric(operator.get(f"{API}/documents/{doc_id}").json(), "ключевая ставка на конец 2026")
    assert not any(t["id"].startswith(doc_id) for t in kb.search("ключевая ставка прогноз", topics=["key_rate"], limit=50))

    r = operator.post(f"{API}/drafts/{rate['draft_id']}/approve", json={"supersedes": "rate-05"})
    assert r.status_code == 200, r.text
    thesis = r.json()["thesis"]
    assert thesis["id"] == f"{doc_id}-01" and thesis["forecast_values"] == {"key_rate:2026-12-31": 15.0}
    found = kb.search("ключевая ставка прогноз конец 2026", topics=["key_rate"], limit=50)
    assert thesis["id"] in {t["id"] for t in found}, "опубликованный тезис доступен агенту"
    old = kb.thesis("rate-05")
    assert old["stale"] and old["superseded_by"] == thesis["id"], "замещенный прогноз помечен stale со ссылкой"
    assert kb.document(doc_id)["ingested"] is True
    pdf = operator.get(f"/api/v1/analytics/{doc_id}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    again = operator.post(f"{API}/drafts/{rate['draft_id']}/approve", json={})
    assert again.status_code == 400, "проверенный черновик повторно не публикуется"


def test_edit_fixes_check_and_reject(operator):
    doc_id = _upload(operator)
    _process()
    doc = operator.get(f"{API}/documents/{doc_id}").json()
    inflation = _by_metric(doc, "инфляция")
    fixed = operator.patch(f"{API}/drafts/{inflation['draft_id']}", json={
        "value": "6,8%", "text": "Годовая инфляция на конец 2026 г. составит 6,8% (прежний прогноз 6,2%)."}).json()
    assert fixed["edited"] and all(c["ok"] for c in fixed["checks"] if c["name"] == "numbers")
    advice = _by_metric(doc, "рекомендация")
    rejected = operator.post(f"{API}/drafts/{advice['draft_id']}/reject", json={"reason": "Рекомендация, не тезис"}).json()
    assert rejected["status"] == "rejected" and rejected["reject_reason"] == "Рекомендация, не тезис"
    listing = operator.get(f"{API}/documents").json()["items"][0]
    assert listing["drafts"] == {"draft": 10, "approved": 0, "rejected": 1}


def test_duplicate_of_published_thesis_is_flagged(client):
    existing = kb.thesis("rate-01")
    checks = ingest.checks({"topic": "key_rate", "text": existing["text"], "quote": ""}, existing["text"], "2026-09-11")
    dup = next(c for c in checks if c["name"] == "duplicate")
    assert not dup["ok"] and dup["duplicate_of"] == "rate-01"


def test_not_a_pdf_and_missing_model(operator, monkeypatch, tmp_path):
    bad = operator.post(f"{API}/documents", params={"name": "x.pdf"}, content=b"hello")
    assert bad.status_code == 400
    monkeypatch.setenv("KB_RECORDED_DIR", str(tmp_path))  # записанных ответов нет
    doc_id = _upload(operator)
    _process()
    doc = operator.get(f"{API}/documents/{doc_id}").json()
    assert doc["status"] == "failed" and "недоступна" in doc["error"]


def test_recognition_has_its_own_budget_line(monkeypatch, tmp_path, client):
    monkeypatch.setenv("KB_RECORDED_DIR", str(tmp_path))
    monkeypatch.setenv("KB_INGEST_LLM_SHARE", "0.25")
    seen = {}

    def fake(system, user, model_kind="compose", max_tokens=2000, reasoning=None, images=None):
        seen.update(line=llm_usage._company.get(), kind=model_kind, images=len(images or []))
        return {"page_text": "Ставка 15,0%", "theses": []}, {"model": "qwen/qwen3-vl-30b-a3b-instruct", "tokens": 10,
                                                             "duration_ms": 1.0}

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", fake)
    answer = ingest.recognize({"page": 1, "text": "", "image": ("image/jpeg", b"\xff\xd8")})
    assert seen == {"line": config.KB_INGEST_LINE, "kind": "vision", "images": 1}
    assert answer["model"].startswith("qwen/qwen3-vl") and config.llm_line_share(config.KB_INGEST_LINE) == 0.25
    assert llm.is_allowed(config.llm_settings()["models"]["vision"]), "модель распознавания — из списка кейса"


def test_demo_review_button_uploads_synthetic_pdf(operator):
    r = operator.post(f"{API}/demo")
    assert r.status_code == 202 and r.json()["created"] is True
    again = operator.post(f"{API}/demo").json()
    assert again["created"] is False and again["doc_id"] == r.json()["doc_id"], "повторное нажатие не плодит документы"
    _process()
    doc = operator.get(f"{API}/documents/{r.json()['doc_id']}").json()
    assert doc["filename"] == ingest.DEMO_NAME and len(doc["drafts"]) == 11, "записанные ответы найдены по sha256"
