from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Role = Literal["ceo", "cfo"]


class CompanyProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str = Field(..., min_length=1, description="Уникальный идентификатор компании")
    display_name: str = Field(..., min_length=1, description="Наименование компании")
    industry_name: str = Field(..., min_length=1, description="Отрасль компании")
    region: str | None = Field(default=None, description="Регион присутствия (null если неизвестно)")
    has_credit: bool | None = Field(default=None, description="Наличие кредитных продуктов (null если неизвестно)")
    has_deposit: bool | None = Field(default=None, description="Наличие депозитных продуктов (null если неизвестно)")
    is_synthetic: Literal[True] = Field(default=True, description="Флаг синтетических данных")


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1, description="Уникальный идентификатор события")
    title: str = Field(..., min_length=1, description="Заголовок события")
    text: str = Field(..., min_length=1, description="Текст события")
    is_synthetic: Literal[True] = Field(default=True, description="Флаг синтетического события")


class InsightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: str = Field(..., min_length=1, description="Идентификатор компании")
    role: Role = Field(..., description="Роль лица, принимающего решения")
    event_id: str = Field(..., min_length=1, description="Идентификатор события")


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, description="Идентификатор источника")
    kind: Literal["synthetic_fixture"] = Field(default="synthetic_fixture", description="Тип источника")
    title: str = Field(..., min_length=1, description="Название источника")


class Insight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.1.0"] = Field(default="0.1.0", description="Версия схемы")
    request_id: str = Field(..., min_length=1, description="Идентификатор запроса")
    company_id: str = Field(..., min_length=1, description="Идентификатор компании")
    event_id: str = Field(..., min_length=1, description="Идентификатор события")
    role: Role = Field(..., description="Роль пользователя (ceo или cfo)")
    status: Literal["completed"] = Field(default="completed", description="Статус формирования инсайта")
    is_mock: Literal[True] = Field(default=True, description="Флаг синтетической/тестовой карточки")
    title: str = Field(..., min_length=1, description="Заголовок инсайта")
    facts: list[str] = Field(default_factory=list, description="Ключевые факты")
    company_relevance: str = Field(..., min_length=1, description="Проекция на компанию")
    risks: list[str] = Field(default_factory=list, description="Выявленные риски")
    opportunities: list[str] = Field(default_factory=list, description="Возможности для компании")
    actions: list[str] = Field(default_factory=list, description="Рекомендуемые действия")
    bank_position: None = Field(default=None, description="Позиция банка (в спринте 1 всегда null)")
    model_conclusion: str = Field(..., min_length=1, description="Заключение (сообщает об отсутствии вызова LLM)")
    sources: list[Source] = Field(default_factory=list, description="Источники")
    uncertainty: list[str] = Field(default_factory=list, description="Факторы неопределенности")


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    retryable: bool = Field(default=False)


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
