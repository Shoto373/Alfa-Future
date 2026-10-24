"""Сводки и алерты (SPR4-04): расписание и тихие часы, антиспам и склейка сюжетов, журнал доставки,
письмо без данных компании в теме, отписка в один клик, сообщения в приложении."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import pytest
from sqlalchemy import select

from app import database, ranking
from app.models import Delivery
from app.notifications import delivery, rules, service, settings

API = "/api/v1/notifications"


def _settings(**kw) -> dict:
    return {**settings.DEFAULTS, **kw}


def test_quiet_hours_overnight_and_timezone():
    s = _settings(quiet_from="22:00", quiet_to="08:00", timezone="Europe/Moscow")
    at = lambda h, m=0: datetime(2026, 10, 24, h, m, tzinfo=timezone.utc)  # noqa: E731 — Москва = UTC+3
    assert rules.quiet(s, at(20))          # 23:00 МСК
    assert rules.quiet(s, at(4, 59))       # 07:59 МСК
    assert not rules.quiet(s, at(5))       # 08:00 МСК
    assert not rules.quiet(_settings(quiet_from="00:00", quiet_to="00:00"), at(1)), "одинаковые границы — тихих часов нет"
    assert rules.quiet(_settings(timezone="Asia/Vladivostok"), at(13)), "23:00 во Владивостоке"


def test_digest_window_in_user_time():
    s = _settings(digest_time="08:30")
    at = lambda h, m=0: datetime(2026, 10, 24, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert rules.digest_key("u", "c", at(5, 29), s) is None, "08:29 МСК — рано"
    assert rules.digest_key("u", "c", at(5, 30), s) == "digest:u:c:2026-10-24"
    assert rules.digest_key("u", "c", at(17), s) is None, "20:00 — утренняя сводка уже не нужна"
    assert rules.digest_key("u", "c", at(6), _settings(digest=False)) is None


def _moment(user_id: str, company_id: str, **changes) -> datetime:
    """Через час после самого важного события ленты; время сводки — это же время (по Москве), тихих часов нет."""
    top = ranking.company_feed(company_id, "cfo")[0]
    now = datetime.fromisoformat(top["news"]["published_at"]) + timedelta(hours=1)
    digest_time = f"{rules.local(now, settings.DEFAULTS):%H:%M}"
    settings.save(user_id, company_id, {"digest_time": digest_time, "quiet_from": "00:00", "quiet_to": "00:00", **changes})
    return now


def _user(client) -> str:
    return client.get("/api/v1/auth/me").json()["user_id"]


def _rows(**match) -> list[Delivery]:
    with database.session() as db:
        q = select(Delivery)
        for k, v in match.items():
            q = q.where(getattr(Delivery, k) == v)
        return list(db.scalars(q.order_by(Delivery.id)))


def test_tick_digest_once_alerts_limited_and_merged(client, company):
    cid = company["company_id"]
    now = _moment(_user(client), cid, threshold=50, alerts_per_day=2)
    first = service.tick(now)
    assert first["digest"] == 2, "сводка в приложении и письмом"
    digest = _rows(kind="digest", channel="inapp")[0]
    assert rules.DIGEST_MIN <= len(digest.payload["items"]) <= rules.DIGEST_MAX
    assert {"headline", "news_id", "score"} <= set(digest.payload["items"][0])
    alerts = _rows(kind="alert", channel="inapp")
    assert 1 <= len(alerts) <= 2, "не больше alerts_per_day"
    assert len({a.payload["story_id"] for a in alerts}) == len(alerts), "один алерт на сюжет"
    again = service.tick(now + timedelta(minutes=5))
    assert again == {"digest": 0, "alert": 0}, "повторный тик не дублирует сводку и не превышает лимит"
    assert all(r.status == "queued" for r in _rows(channel="email")), "письма ждут задачу доставки"


def test_quiet_hours_hold_alerts(client, company):
    cid = company["company_id"]
    now = _moment(_user(client), cid, threshold=50, digest=False)
    settings.save(_user(client), cid, {"quiet_from": "00:00", "quiet_to": "23:59"})
    assert service.tick(now) == {"digest": 0, "alert": 0}
    settings.save(_user(client), cid, {"quiet_from": "00:00", "quiet_to": "00:00"})
    assert service.tick(now)["alert"] >= 1, "после тихих часов алерт уходит"


class FakeSMTP:
    sent: list[EmailMessage] = []
    fail = False

    def __init__(self, host, port, timeout):
        assert host == "mail.test"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError("connection refused")
        FakeSMTP.sent.append(msg)


def test_email_without_company_in_subject_and_retry(client, company, monkeypatch):
    cid = company["company_id"]
    service.tick(_moment(_user(client), cid))
    email = _rows(kind="digest", channel="email")[0]
    assert delivery.deliver(email.id) == "skipped", "без SMTP_HOST письмо не отправляется"
    with database.session() as db:
        db.get(Delivery, email.id).status = "queued"
    monkeypatch.setenv("SMTP_HOST", "mail.test")
    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], True
    with pytest.raises(OSError):
        delivery.deliver(email.id)
    assert _rows(id=email.id)[0].status == "failed", "сбой почты — в журнале, задача повторится"
    FakeSMTP.fail = False
    assert delivery.deliver(email.id) == "sent" and delivery.deliver(email.id) == "sent", "второй раз не шлет"
    assert len(FakeSMTP.sent) == 1
    msg = FakeSMTP.sent[0]
    assert company["display_name"] not in msg["Subject"] and "сводка" in msg["Subject"]
    assert "/notifications/unsubscribe?token=" in msg["List-Unsubscribe"] and msg["List-Unsubscribe-Post"]
    assert "?from=digest&d=" in msg.get_content()
    row = _rows(id=email.id)[0]
    assert row.attempts == 3 and row.sent_at is not None


def test_api_settings_inbox_opened_and_unsubscribe(client, company, raw_client):
    cid = company["company_id"]
    got = client.get(f"{API}/settings", params={"company_id": cid}).json()
    assert got["digest_time"] == "08:30" and got["timezone"] == "Europe/Moscow" and "unsubscribe_token" not in got
    saved = client.put(f"{API}/settings", params={"company_id": cid},
                       json={"threshold": 85, "channels": {"telegram": True}, "topics": ["key_rate"]}).json()
    assert saved["threshold"] == 85 and saved["channels"] == {"inapp": True, "email": True, "telegram": True}
    assert client.put(f"{API}/settings", params={"company_id": cid}, json={"timezone": "Mars/Base"}).status_code == 400
    assert client.put(f"{API}/settings", params={"company_id": cid}, json={"digest_time": "25:00"}).status_code == 400
    client.put(f"{API}/settings", params={"company_id": cid}, json={"topics": []})

    sent = client.post(f"{API}/test-digest", params={"company_id": cid}).json()
    assert sent["created"] >= 1 and "inapp" in sent["channels"]
    inbox = client.get(API, params={"company_id": cid}).json()
    assert inbox["unread"] == 1 and inbox["items"][0]["items"][0]["href"].startswith("/pulse/n/")
    item_id = inbox["items"][0]["id"]
    assert client.post(f"{API}/{item_id}/opened").json() == {"ok": True}
    assert client.get(API, params={"company_id": cid}).json()["unread"] == 0
    assert _rows(id=item_id)[0].opened_at is not None
    client.post(f"{API}/test-digest", params={"company_id": cid})
    assert client.post(f"{API}/read", json={"company_id": cid}).json()["updated"] == 1

    user_id = client.get("/api/v1/auth/me").json()["user_id"]
    token = settings.get(user_id, cid)["unsubscribe_token"]
    assert raw_client.post(f"{API}/unsubscribe", params={"token": token}).json() == {"ok": True}
    after = settings.get(user_id, cid)
    assert after["channels"]["email"] is False and after["channels"]["inapp"] is True, "отписка выключает только почту"
    assert raw_client.get(f"{API}/unsubscribe", params={"token": "x" * 20}).status_code == 404


def test_cannot_open_someone_elses_delivery(client, company, new_client):
    from tests.conftest import register

    client.post(f"{API}/test-digest", params={"company_id": company["company_id"]})
    item_id = client.get(API, params={"company_id": company["company_id"]}).json()["items"][0]["id"]
    stranger = new_client()
    register(stranger, "stranger@example.com")
    assert stranger.post(f"{API}/{item_id}/opened").json() == {"ok": False}
    assert _rows(id=item_id)[0].opened_at is None
