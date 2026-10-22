"""Пароли (scrypt), токены сессий и ограничение числа неудачных входов."""

import hashlib
import hmac
import secrets
import threading
import time

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
SESSION_TTL = 7 * 24 * 3600
MAX_FAILS = 5
LOCK_SECONDS = 5 * 60


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    return salt.hex(), _derive(password, salt).hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    return hmac.compare_digest(_derive(password, bytes.fromhex(salt_hex)), bytes.fromhex(hash_hex))


# Хэш для несуществующего email: вход занимает столько же времени, и наличие почты не раскрывается.
_DUMMY_SALT, _DUMMY_HASH = hash_password("dummy-password-for-timing")


def verify_dummy(password: str) -> None:
    verify_password(password, _DUMMY_SALT, _DUMMY_HASH)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """В хранилище лежит только SHA-256 токена: утечка файла не дает готовых сессий."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginLimiter:
    """Счетчик неудач в памяти по паре email+IP: 5 ошибок — блокировка на 5 минут."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[tuple[str, str], list[float]] = {}  # ключ -> [число неудач, заблокирован до]

    def blocked(self, key: tuple[str, str]) -> bool:
        with self._lock:
            st = self._state.get(key)
            if not st or not st[1]:
                return False
            if st[1] <= time.time():
                del self._state[key]
                return False
            return True

    def fail(self, key: tuple[str, str]) -> None:
        with self._lock:
            if len(self._state) > 10000:  # защита памяти от перебора ключей
                now = time.time()
                self._state = {k: v for k, v in self._state.items() if v[1] > now}
            st = self._state.setdefault(key, [0, 0.0])
            st[0] += 1
            if st[0] >= MAX_FAILS:
                st[1] = time.time() + LOCK_SECONDS

    def reset(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._state.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._state.clear()


limiter = LoginLimiter()
