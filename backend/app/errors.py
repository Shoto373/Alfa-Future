"""Исключения сервиса. Базовый слой: ими пользуются и данные (учетные записи), и агент, и API.

ApiError — ошибка с кодом контракта API; HTTP-статус берется из STATUS, текст и формат ответа —
в app/api/errors.py.
"""


STATUS = {
    "INVALID_REQUEST": 400,
    "COMPANY_NOT_FOUND": 404,
    "NEWS_NOT_FOUND": 404,
    "INSIGHT_NOT_FOUND": 404,
    "DOCUMENT_NOT_FOUND": 404,
    "FILE_NOT_FOUND": 404,
    "FETCH_FAILED": 422,
    "REQUEST_TOO_LARGE": 413,
    "DATA_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
    "INVALID_ANALYSIS_RESULT": 500,
    "ANALYSIS_UNAVAILABLE": 503,
    "ANALYSIS_TIMEOUT": 504,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "INVALID_CREDENTIALS": 401,
    "EMAIL_TAKEN": 409,
    "COMPANY_CLAIMED": 409,
    "TOO_MANY_COMPANIES": 409,
    "MEMBER_NOT_FOUND": 404,
    "LEAD_NOT_FOUND": 404,
    "MEMBER_EXISTS": 409,
    "LAST_ADMIN": 409,
    "TOO_MANY_ATTEMPTS": 429,
    "RATE_LIMITED": 429,
    "TOO_MANY_REQUESTS": 429,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None, headers: dict[str, str] | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.headers = headers or {}  # например, Retry-After у 429
        self.status_code = STATUS[code]


class AnalysisUnavailable(Exception):
    """Сервис анализа (или LLM) временно недоступен."""


class InvalidAnalysisResult(Exception):
    """Результат анализа не прошел проверку контракта или самопроверку."""
