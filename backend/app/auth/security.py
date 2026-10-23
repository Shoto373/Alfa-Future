"""Пароли (scrypt с параметрами в записи), токены сессий и сроки блокировки входа."""

import hashlib
import hmac
import secrets

# Текущие параметры scrypt. У записи хранятся свои: пароль со старыми параметрами проверяется ими
# и при успешном входе перехэшируется текущими (store.rehash_if_needed).
SCRYPT_PARAMS = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}
LEGACY_PARAMS = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}  # записи JSON-хранилища без параметров
MAX_FAILS = 5
FAIL_WINDOW_SECONDS = 15 * 60


def _derive(password: str, salt: bytes, params: dict) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, maxmem=64 * 1024 * 1024, **params)


def hash_password(password: str) -> tuple[str, str, dict]:
    salt = secrets.token_bytes(16)
    params = dict(SCRYPT_PARAMS)
    return salt.hex(), _derive(password, salt, params).hex(), params


def verify_password(password: str, salt_hex: str, hash_hex: str, params: dict | None = None) -> bool:
    return hmac.compare_digest(_derive(password, bytes.fromhex(salt_hex), params or LEGACY_PARAMS), bytes.fromhex(hash_hex))


def needs_rehash(params: dict | None) -> bool:
    return (params or LEGACY_PARAMS) != SCRYPT_PARAMS


# Хэш для несуществующего email: вход занимает столько же времени, и наличие почты не раскрывается.
_DUMMY_SALT, _DUMMY_HASH, _DUMMY_PARAMS = hash_password("dummy-password-for-timing")


def verify_dummy(password: str) -> None:
    verify_password(password, _DUMMY_SALT, _DUMMY_HASH, _DUMMY_PARAMS)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """В хранилище лежит только SHA-256 токена: утечка базы не дает готовых сессий."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
