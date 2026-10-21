"""Ошибки HTTP API в формате контракта {"error": {...}}."""

from fastapi.responses import JSONResponse

from app.schemas import ErrorDetail, ErrorResponse

MESSAGES = {
    "INVALID_REQUEST": "Некорректный запрос",
    "COMPANY_NOT_FOUND": "Компания не найдена",
    "EVENT_NOT_FOUND": "Событие не найдено",
    "REQUEST_TOO_LARGE": "Тело запроса превышает допустимый размер",
    "INTERNAL_ERROR": "Внутренняя ошибка сервиса",
    "INVALID_ANALYSIS_RESULT": "Модуль анализа вернул некорректный результат",
    "ANALYSIS_UNAVAILABLE": "Анализ временно недоступен",
    "ANALYSIS_TIMEOUT": "Превышено время ожидания анализа",
}

STATUS = {
    "INVALID_REQUEST": 400,
    "COMPANY_NOT_FOUND": 404,
    "EVENT_NOT_FOUND": 404,
    "REQUEST_TOO_LARGE": 413,
    "INTERNAL_ERROR": 500,
    "INVALID_ANALYSIS_RESULT": 500,
    "ANALYSIS_UNAVAILABLE": 503,
    "ANALYSIS_TIMEOUT": 504,
}


class ApiError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.status_code = STATUS[code]


def error_response(code: str, request_id: str) -> JSONResponse:
    status = STATUS[code]
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=MESSAGES[code],
            request_id=request_id,
            retryable=status in (503, 504),
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump())
