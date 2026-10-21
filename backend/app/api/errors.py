"""Ошибки HTTP API в формате контракта {"error": {...}}."""

from fastapi.responses import JSONResponse

from app.schemas import ErrorDetail, ErrorResponse

MESSAGES = {
    "INVALID_REQUEST": "Некорректный запрос",
    "COMPANY_NOT_FOUND": "Компания не найдена",
    "NEWS_NOT_FOUND": "Новость не найдена",
    "INSIGHT_NOT_FOUND": "Карточка анализа не найдена",
    "DOCUMENT_NOT_FOUND": "Документ не найден",
    "FETCH_FAILED": "Не удалось загрузить материал по ссылке",
    "REQUEST_TOO_LARGE": "Тело запроса превышает допустимый размер",
    "DATA_UNAVAILABLE": "Данные о компаниях недоступны",
    "INTERNAL_ERROR": "Внутренняя ошибка сервиса",
    "INVALID_ANALYSIS_RESULT": "Модуль анализа вернул некорректный результат",
    "ANALYSIS_UNAVAILABLE": "Анализ временно недоступен",
    "ANALYSIS_TIMEOUT": "Превышено время ожидания анализа",
}

STATUS = {
    "INVALID_REQUEST": 400,
    "COMPANY_NOT_FOUND": 404,
    "NEWS_NOT_FOUND": 404,
    "INSIGHT_NOT_FOUND": 404,
    "DOCUMENT_NOT_FOUND": 404,
    "FETCH_FAILED": 422,
    "REQUEST_TOO_LARGE": 413,
    "DATA_UNAVAILABLE": 503,
    "INTERNAL_ERROR": 500,
    "INVALID_ANALYSIS_RESULT": 500,
    "ANALYSIS_UNAVAILABLE": 503,
    "ANALYSIS_TIMEOUT": 504,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(code)
        self.code = code
        self.message = message
        self.status_code = STATUS[code]


def error_response(code: str, request_id: str, message: str | None = None) -> JSONResponse:
    status = STATUS[code]
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message or MESSAGES[code],
            request_id=request_id,
            retryable=status in (503, 504),
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump())
