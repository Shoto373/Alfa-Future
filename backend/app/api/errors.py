"""Ошибки HTTP API в формате контракта {"error": {...}}."""

from fastapi.responses import JSONResponse

from app.errors import STATUS  # коды и ApiError — в базовом слое app/errors.py
from app.schemas import ErrorDetail, ErrorResponse

MESSAGES = {
    "INVALID_REQUEST": "Некорректный запрос",
    "COMPANY_NOT_FOUND": "Компания не найдена",
    "NEWS_NOT_FOUND": "Новость не найдена",
    "INSIGHT_NOT_FOUND": "Карточка анализа не найдена",
    "DOCUMENT_NOT_FOUND": "Документ не найден",
    "FILE_NOT_FOUND": "Файл не найден",
    "FETCH_FAILED": "Не удалось загрузить материал по ссылке",
    "REQUEST_TOO_LARGE": "Тело запроса превышает допустимый размер",
    "DATA_UNAVAILABLE": "Данные о компаниях недоступны",
    "INTERNAL_ERROR": "Внутренняя ошибка сервиса",
    "INVALID_ANALYSIS_RESULT": "Модуль анализа вернул некорректный результат",
    "ANALYSIS_UNAVAILABLE": "Анализ временно недоступен",
    "ANALYSIS_TIMEOUT": "Превышено время ожидания анализа",
    "UNAUTHORIZED": "Требуется вход в систему",
    "FORBIDDEN": "Недостаточно прав",
    "INVALID_CREDENTIALS": "Неверный email или пароль",
    "EMAIL_TAKEN": "Пользователь с таким email уже зарегистрирован",
    "COMPANY_CLAIMED": "У компании уже есть администратор",
    "TOO_MANY_COMPANIES": "Нельзя управлять более чем 5 компаниями",
    "MEMBER_NOT_FOUND": "Участник не найден",
    "LEAD_NOT_FOUND": "Заявка не найдена",
    "MEMBER_EXISTS": "Участник с таким email уже добавлен в компанию",
    "LAST_ADMIN": "Нельзя убрать последнего администратора компании",
    "TOO_MANY_ATTEMPTS": "Слишком много неудачных попыток входа, повторите позже",
    "RATE_LIMITED": "Слишком много запросов к AI за час, повторите позже",
    "TOO_MANY_REQUESTS": "Слишком много запросов, повторите через минуту",
}


def error_response(code: str, request_id: str, message: str | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    status = STATUS[code]
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message or MESSAGES[code],
            request_id=request_id,
            retryable=status in (503, 504),
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)
