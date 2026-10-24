"""Скрипт проверки запущенного сервиса: недоступный сервис — провал с кодом 1, а не тихий успех."""

import socket

from app import smoke


def test_smoke_fails_when_service_is_down(monkeypatch, capsys):
    with socket.socket() as s:  # свободный порт, на котором никто не слушает
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    monkeypatch.setattr("sys.argv", ["smoke", "--base-url", f"http://127.0.0.1:{port}"])
    for name in ("SMOKE_EMAIL", "SMOKE_OPERATOR_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    assert smoke.main() == 1
    assert "FAIL" in capsys.readouterr().out
