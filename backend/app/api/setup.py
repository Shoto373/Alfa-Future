"""Глобальные обработчики ошибок, CORS, лимит тела и журналирование."""

import asyncio
import json
import logging
import re
import time
import uuid
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app import config, observability
from app.domain_config import loader as domain_config
from app.api.errors import error_response
from app.errors import ApiError
from app.schemas import API_VERSION

logger = logging.getLogger("app.api")

MAX_BODY_BYTES = 64 * 1024
# Адреса с большим телом запроса: файл компании (CSV/PDF, 5 МБ) и PDF аналитики банка на распознавание (20 МБ).
UPLOAD_MAX_BYTES = 5 * 1024 * 1024 + 1024
UPLOAD_PATH = re.compile(r"^/api/v1/companies/[^/]+/extra/files$")
KB_UPLOAD_MAX_BYTES = 20 * 1024 * 1024 + 1024
KB_UPLOAD_PATH = re.compile(r"^/api/v1/admin/kb/documents$")


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
    out = [*headers, *SECURITY_HEADERS, (b"x-api-version", API_VERSION.encode())]
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
        ctx = observability.start_request(request_id)
        if domain_config.due():  # версия словарей, опубликованная аналитиком в другом процессе (SPR4-00)
            await asyncio.to_thread(_refresh_domain_config)
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        observability.set_company((query.get("company_id") or [None])[0])
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
            seconds = time.perf_counter() - started
            # Шаблон маршрута (/api/v1/insights/{insight_id}), а не путь: метки метрик не растут без предела.
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            status = status_holder["status"] or 500
            observability.observe_request(scope.get("method", ""), route, status, seconds)
            # Только метаданные: без тел запросов, профилей и заголовков; псевдоним пользователя и компания — из ctx.
            logger.info("request", extra={"request_id": request_id, "method": scope.get("method"), "path": scope.get("path"), "route": route,
                                          "status": status, "duration_ms": round(seconds * 1000, 1),
                                          **{k: ctx[k] for k in ("user", "company_id", "trace_id") if k in ctx}})

    async def _handle(self, scope, receive, send, request_id):
        headers = dict(scope.get("headers") or [])
        path = scope.get("path", "")
        limit = (UPLOAD_MAX_BYTES if UPLOAD_PATH.match(path) else KB_UPLOAD_MAX_BYTES if KB_UPLOAD_PATH.match(path)
                 else self.max_bytes)
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
        _company_from_body(body, headers)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def _refresh_domain_config() -> None:
    try:
        domain_config.refresh()
    except Exception:  # база недоступна — работаем на текущей версии  # noqa: BLE001
        logger.exception("domain config refresh failed")


def _company_from_body(body: bytes, headers: dict) -> None:
    """company_id из JSON-тела (разбор, вопросы) — в контекст запроса для логов."""
    if b"json" not in headers.get(b"content-type", b"") or len(body) > 64 * 1024:
        return
    try:
        data = json.loads(body)
    except ValueError:
        return
    if isinstance(data, dict) and isinstance(data.get("company_id"), str):
        observability.set_company(data["company_id"])


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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_credentials=True,
        allow_headers=["Content-Type"],
        expose_headers=["X-API-Version"],
    )
