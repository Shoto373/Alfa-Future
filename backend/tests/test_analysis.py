import pytest
from app.analysis.service import generate_insight
from app.schemas import CompanyProfile, Event, Insight, Source


@pytest.fixture
def demo_event() -> Event:
    return Event(
        event_id="demo_event_001",
        title="Сохранение стоимости заимствований и ключевой ставки",
        text="Банк России сохранил ключевую ставку на текущем уровне.",
        is_synthetic=True,
    )


@pytest.fixture
def demo_company_1() -> CompanyProfile:
    # credit = True, deposit = False
    return CompanyProfile(
        company_id="demo_company_001",
        display_name="Демо ПАО Северная Промышленность",
        industry_name="Машиностроение",
        region="Северо-Западный ФО",
        has_credit=True,
        has_deposit=False,
        is_synthetic=True,
    )


@pytest.fixture
def demo_company_2() -> CompanyProfile:
    # credit = False, deposit = True
    return CompanyProfile(
        company_id="demo_company_002",
        display_name="Демо ООО Южный Ритейл",
        industry_name="Розничная торговля",
        region="Южный ФО",
        has_credit=False,
        has_deposit=True,
        is_synthetic=True,
    )


@pytest.mark.asyncio
async def test_insight_contract_schema_and_immutability(demo_company_1, demo_event):
    """Проверка строгого соответствия контракту Insight и неизменности идентификаторов."""
    request_id = "test_req_001"
    insight = await generate_insight(demo_company_1, "cfo", demo_event, request_id)

    assert isinstance(insight, Insight)
    assert insight.schema_version == "0.1.0"
    assert insight.request_id == request_id
    assert insight.company_id == demo_company_1.company_id
    assert insight.event_id == demo_event.event_id
    assert insight.role == "cfo"
    assert insight.status == "completed"
    assert insight.is_mock is True
    assert insight.bank_position is None

    # Проверка обязательного указания на отсутствие LLM
    assert "LLM" in insight.model_conclusion or "без вызова LLM" in insight.model_conclusion

    # Проверка источников
    assert len(insight.sources) == 1
    assert insight.sources[0].source_id == demo_event.event_id
    assert insight.sources[0].kind == "synthetic_fixture"
    assert insight.sources[0].title == demo_event.title


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["ceo", "cfo"])
async def test_matrix_two_companies_two_roles(demo_company_1, demo_company_2, demo_event, role):
    """Матрица: 2 компании x 2 роли (демонстрация различий по кредитным/депозитным признакам)."""
    # Компания 1: кредит True, депозит False
    insight_1 = await generate_insight(demo_company_1, role, demo_event, f"req_c1_{role}")
    # Компания 2: кредит False, депозит True
    insight_2 = await generate_insight(demo_company_2, role, demo_event, f"req_c2_{role}")

    # Проверка, что результаты различны
    assert insight_1.company_relevance != insight_2.company_relevance
    assert demo_company_1.industry_name in insight_1.company_relevance
    assert demo_company_2.industry_name in insight_2.company_relevance

    # Компания 1 должна содержать кредитные упоминания
    assert any("кредит" in r.lower() for r in insight_1.risks)
    # Компания 2 не имеет кредита, но имеет депозит
    assert any("депозит" in o.lower() for o in insight_2.opportunities)


@pytest.mark.asyncio
async def test_role_differences_cfo_vs_ceo(demo_company_1, demo_event):
    """Для CFO акцент на проверке условий договоров, для CEO — на планах финансирования."""
    insight_cfo = await generate_insight(demo_company_1, "cfo", demo_event, "req_cfo")
    insight_ceo = await generate_insight(demo_company_1, "ceo", demo_event, "req_ceo")

    assert insight_cfo.role == "cfo"
    assert insight_ceo.role == "ceo"

    # CFO действия акцентируют договоры
    cfo_actions_text = " ".join(insight_cfo.actions).lower()
    assert "договор" in cfo_actions_text or "условий" in cfo_actions_text

    # CEO действия акцентируют планы финансирования
    ceo_actions_text = " ".join(insight_ceo.actions).lower()
    assert "план" in ceo_actions_text or "финансирован" in ceo_actions_text


@pytest.mark.asyncio
async def test_both_products_true(demo_event):
    """При обоих true учитываются и кредитные, и депозитные риски и возможности."""
    company_both_true = CompanyProfile(
        company_id="comp_both_true",
        display_name="Тест Обе Продуктовые Линии",
        industry_name="Энергетика",
        region="Центральный ФО",
        has_credit=True,
        has_deposit=True,
        is_synthetic=True,
    )

    insight = await generate_insight(company_both_true, "cfo", demo_event, "req_both_true")

    # Учитываются оба
    assert any("кредит" in r.lower() for r in insight.risks)
    assert any("депозит" in r.lower() for r in insight.risks)
    assert any("депозит" in o.lower() for o in insight.opportunities)
    assert any("кредит" in o.lower() for o in insight.opportunities)
    assert len(insight.uncertainty) == 0


@pytest.mark.asyncio
async def test_both_products_false(demo_event):
    """При обоих false не утверждается наличие продуктов."""
    company_both_false = CompanyProfile(
        company_id="comp_both_false",
        display_name="Тест Без Продуктов",
        industry_name="ИТ",
        region="Москва",
        has_credit=False,
        has_deposit=False,
        is_synthetic=True,
    )

    insight = await generate_insight(company_both_false, "ceo", demo_event, "req_both_false")

    # Не утверждается наличие активных продуктов
    assert "активные кредитные продукты в профиле компании отсутствуют" in insight.company_relevance.lower()
    assert "депозитные продукты в профиле компании отсутствуют" in insight.company_relevance.lower()
    # Нет неопределенности (значения явно False, а не null)
    assert len(insight.uncertainty) == 0


@pytest.mark.asyncio
async def test_null_fields_mark_uncertainty(demo_event):
    """null означает неизвестное (а не false) и обязательно фиксируется в uncertainty."""
    company_with_nulls = CompanyProfile(
        company_id="comp_nulls",
        display_name="Тест С Неизвестными Данными",
        industry_name="Строительство",
        region=None,
        has_credit=None,
        has_deposit=None,
        is_synthetic=True,
    )

    insight = await generate_insight(company_with_nulls, "cfo", demo_event, "req_nulls")

    # Неизвестные поля должны быть в uncertainty
    uncertainty_text = " ".join(insight.uncertainty).lower()
    assert "has_credit=null" in uncertainty_text or "кредит" in uncertainty_text
    assert "has_deposit=null" in uncertainty_text or "депозит" in uncertainty_text
    assert "region=null" in uncertainty_text or "регион" in uncertainty_text
    assert len(insight.uncertainty) == 3
