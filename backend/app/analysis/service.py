from app.schemas import CompanyProfile, Event, Insight, Role, Source


async def generate_insight(
    company: CompanyProfile,
    role: Role,
    event: Event,
    request_id: str,
) -> Insight:
    """Генерация детерминированной синтетической карточки инсайта.
    
    Модуль не производит внешних вызовов, не читает файлы/БД,
    не использует LLM и опирается исключительно на переданные аргументы.
    """
    # 1. Факты
    region_display = company.region if company.region else "Регион не указан"
    facts = [
        f"Событие: {event.title}",
        f"Ключевая информация: {event.text}",
        f"Профиль компании: {company.display_name} (отрасль: {company.industry_name}, регион: {region_display})",
    ]

    # 2. Проекция на компанию (company_relevance)
    relevance_items = [
        f"Событие оказывает влияние на компанию «{company.display_name}» в отрасли «{company.industry_name}»."
    ]
    if company.has_credit is True:
        relevance_items.append("У компании присутствуют кредитные обязательства, требующие контроля ставок и лимитов.")
    elif company.has_credit is False:
        relevance_items.append("Активные кредитные продукты в профиле компании отсутствуют.")

    if company.has_deposit is True:
        relevance_items.append("Компания использует депозитные инструменты для размещения ликвидности.")
    elif company.has_deposit is False:
        relevance_items.append("Депозитные продукты в профиле компании отсутствуют.")

    company_relevance = " ".join(relevance_items)

    # 3. Риски
    risks: list[str] = []
    if company.has_credit is True:
        risks.append("Риск изменения стоимости обслуживания заёмного капитала и кредитных линий.")
    if company.has_deposit is True:
        risks.append("Риск снижения доходности размещения свободных денежных средств и депозитов при изменении рыночных условий.")
    if company.has_credit is False and company.has_deposit is False:
        risks.append("Прямые риски по кредитам и депозитам отсутствуют в связи с отсутствием открытых банковских продуктов.")

    if role == "ceo":
        risks.append("Стратегический риск замедления инвестиционных проектов компании при изменении макроэкономических факторов.")
    else:  # cfo
        risks.append("Операционный риск нарушения финансовых ковенантов и увеличения процентных расходов казначейства.")

    # 4. Возможности
    opportunities: list[str] = []
    if company.has_deposit is True:
        opportunities.append("Оптимизация условий размещения ликвидности и фиксация доходности по депозитам.")
    if company.has_credit is True:
        opportunities.append("Возможность своевременного рефинансирования или реструктуризации кредитного портфеля.")
    if company.has_credit is False and company.has_deposit is False:
        opportunities.append("Возможность привлечения первичного банковского финансирования на льготных отраслевых условиях.")

    if role == "ceo":
        opportunities.append("Использование макроэкономической стабильности для масштабирования бизнеса и инвестиций.")
    else:  # cfo
        opportunities.append("Повышение эффективности управления денежными потоками и оптимизация рабочего капитала.")

    # 5. Рекомендуемые действия (акценты: cfo -> проверка условий договоров; ceo -> планы финансирования)
    actions: list[str] = []
    if role == "cfo":
        actions.append("Провести проверку условий действующих договоров, процентных ставок и графика выплат.")
        if company.has_credit is True:
            actions.append("Проверить кредитные договоры на предмет ковенантов и условий пересмотра ставок.")
        if company.has_deposit is True:
            actions.append("Проверить условия размещения ликвидности и актуализировать депозитный портфель.")
        if company.has_credit is False and company.has_deposit is False:
            actions.append("Оценить потребность казначейства в открытии базовых кредитно-депозитных линий.")
    else:  # ceo
        actions.append("Актуализировать стратегические планы финансирования и инвестпрограмму компании.")
        if company.has_credit is True:
            actions.append("Согласовать долгосрочные планы финансирования инвестпроектов с учётом кредитной нагрузки.")
        if company.has_deposit is True:
            actions.append("Определить планы финансирования новых направлений за счёт свободной ликвидности.")
        if company.has_credit is False and company.has_deposit is False:
            actions.append("Сформировать среднесрочные планы финансирования развития компании.")

    # 6. Факторы неопределенности (null-значения)
    uncertainty: list[str] = []
    if company.has_credit is None:
        uncertainty.append("Неизвестен статус наличия кредитных продуктов (has_credit=null).")
    if company.has_deposit is None:
        uncertainty.append("Неизвестен статус наличия депозитных продуктов (has_deposit=null).")
    if company.region is None:
        uncertainty.append("Регион присутствия компании не указан (region=null).")

    # 7. Источники
    sources = [
        Source(
            source_id=event.event_id,
            kind="synthetic_fixture",
            title=event.title,
        )
    ]

    # 8. Заключение модели (обязательное указание на отсутствие LLM)
    model_conclusion = (
        "Синтетический анализ по правилам бизнес-логики без вызова LLM. "
        "Аналитический вывод сформирован детерминированным модулем SPR1-03."
    )

    title = f"Аналитический обзор: {event.title} для {company.display_name} ({role.upper()})"

    return Insight(
        schema_version="0.1.0",
        request_id=request_id,
        company_id=company.company_id,
        event_id=event.event_id,
        role=role,
        status="completed",
        is_mock=True,
        title=title,
        facts=facts,
        company_relevance=company_relevance,
        risks=risks,
        opportunities=opportunities,
        actions=actions,
        bank_position=None,
        model_conclusion=model_conclusion,
        sources=sources,
        uncertainty=uncertainty,
    )
