"""Глобальные обработчики ошибок, CORS, лимит тела и журналирование."""

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.errors import error_response
from app.errors import ApiError
from app.schemas import SCHEMA_VERSION

logger = logging.getLogger("app.api")

MAX_BODY_BYTES = 64 * 1024
# Загрузка файла компании (CSV/PDF) — единственный адрес с большим телом запроса.
UPLOAD_MAX_BYTES = 5 * 1024 * 1024 + 1024
UPLOAD_PATH = re.compile(r"^/api/v1/companies/[^/]+/extra/files$")


# Заголовки безопасности всех ответов API (SPR3-04). Ответы JSON дополнительно запрещают любую загрузку
# ресурсов (CSP); документация /docs и PDF банка без CSP — им нужны свои скрипты и встроенный просмотр.
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]
JSON_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")


def _with_security_headers(headers: list) -> list:
    out = [*headers, *SECURITY_HEADERS, (b"x-api-version", SCHEMA_VERSION.encode())]
    if any(k.lower() == b"content-type" and v.startswith(b"application/json") for k, v in headers):
        out.append(JSON_CSP)
    return out


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


class RequestContextMiddleware:
    """Создает request_id и отклоняет тела больше лимита.

    Проверяется и Content-Length, и фактический поток (chunked без длины).
    Тело буферизуется не более лимита и передается приложению повторно.
    """

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_holder = {"status": None}

        async def send_logged(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                # Версия контракта и заголовки безопасности — в каждом ответе.
                message["headers"] = _with_security_headers(list(message.get("headers", [])))
            await send(message)

        try:
            await self._handle(scope, receive, send_logged, request_id)
        finally:
            # Только метаданные: без тел запросов, профилей и заголовков.
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id,
                scope.get("method"),
                scope.get("path"),
                status_holder["status"],
                (time.perf_counter() - started) * 1000,
            )

    async def _handle(self, scope, receive, send, request_id):
        headers = dict(scope.get("headers") or [])
        limit = UPLOAD_MAX_BYTES if UPLOAD_PATH.match(scope.get("path", "")) else self.max_bytes
        length = headers.get(b"content-length")
        if length is not None and length.isdigit() and int(length) > limit:
            await error_response("REQUEST_TOO_LARGE", request_id)(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        more = scope.get("method") in ("POST", "PUT", "PATCH")
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > limit:
                await error_response("REQUEST_TOO_LARGE", request_id)(scope, receive, send)
                return
            chunks.append(chunk)
            more = message.get("more_body", False)

        if not chunks:
            await self.app(scope, receive, send)
            return

        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _openapi_without_422(app: FastAPI):
    """FastAPI объявляет 422 автоматически, но API отвечает 400 INVALID_REQUEST."""
    original = app.openapi

    def openapi():
        if app.openapi_schema is None:
            schema = original()
            for ops in schema.get("paths", {}).values():
                for op in ops.values():
                    op.get("responses", {}).pop("422", None)
            schemas = schema.get("components", {}).get("schemas", {})
            schemas.pop("HTTPValidationError", None)
            schemas.pop("ValidationError", None)
            app.openapi_schema = schema
        return app.openapi_schema

    return openapi


def configure_api(app: FastAPI) -> None:
    app.openapi = _openapi_without_422(app)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        return error_response("INVALID_REQUEST", request.state.request_id)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.code, request.state.request_id, exc.message, exc.headers)

    # Последний добавленный middleware — внешний. CORS снаружи,
    # чтобы ответ 413 из RequestContextMiddleware тоже получил CORS-заголовки.
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.frontend_origins(),
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_credentials=True,
        allow_headers=["Content-Type"],
        expose_headers=["X-API-Version"],
    )
