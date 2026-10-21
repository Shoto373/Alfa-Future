"""Отрасли (сектора) по ОКВЭД и их чувствительность к макрофакторам.

Сектор — укрупненная группа видов деятельности, с которой работают
классификатор новостей, ранжирование и агент. Чувствительность описывает,
как тема новости обычно влияет на сектор: знак (+1 выигрывает, -1 проигрывает,
0 — влияние неоднозначно) и короткое объяснение механизма.
"""

from dataclasses import dataclass

SECTOR_NAMES = {
    "agriculture_food": "Сельское хозяйство и пищевая промышленность",
    "mining_oil_gas": "Добыча нефти и газа",
    "mining_metals": "Добыча металлических руд и драгметаллов",
    "oil_refining": "Нефтепереработка",
    "chemicals": "Химическая промышленность",
    "pharma": "Фармацевтика",
    "metallurgy": "Металлургия",
    "manufacturing": "Машиностроение и обрабатывающие производства",
    "auto": "Автомобильная отрасль",
    "energy_utilities": "Энергетика и ЖКХ",
    "construction": "Строительство",
    "trade_wholesale": "Оптовая торговля",
    "fuel_trade": "Торговля топливом",
    "retail": "Розничная торговля",
    "transport": "Транспорт и логистика",
    "hospitality": "Гостиницы и общепит",
    "it_telecom": "ИТ и телекоммуникации",
    "finance": "Финансы и страхование",
    "real_estate": "Операции с недвижимостью",
    "services": "Профессиональные и прочие услуги",
    "other": "Прочие виды деятельности",
}

# Префиксы ОКВЭД -> сектор. Более длинный префикс имеет приоритет.
_PREFIXES = {
    "01": "agriculture_food", "02": "agriculture_food", "03": "agriculture_food",
    "10": "agriculture_food", "11": "agriculture_food", "12": "agriculture_food",
    "05": "mining_oil_gas", "06": "mining_oil_gas", "09.1": "mining_oil_gas",
    "07": "mining_metals", "08": "mining_metals", "09": "mining_metals",
    "19": "oil_refining",
    "20": "chemicals", "22": "chemicals",
    "21": "pharma", "46.46": "pharma", "47.73": "pharma",
    "24": "metallurgy", "25": "metallurgy",
    "26": "manufacturing", "27": "manufacturing", "28": "manufacturing", "30": "manufacturing",
    "33": "manufacturing", "13": "manufacturing", "14": "manufacturing", "15": "manufacturing",
    "16": "manufacturing", "17": "manufacturing", "18": "manufacturing", "23": "manufacturing",
    "31": "manufacturing", "32": "manufacturing",
    "29": "auto", "45": "auto",
    "35": "energy_utilities", "36": "energy_utilities", "37": "energy_utilities",
    "38": "energy_utilities", "39": "energy_utilities",
    "41": "construction", "42": "construction", "43": "construction", "71.12.2": "construction",
    "46": "trade_wholesale", "46.71": "fuel_trade", "47.3": "fuel_trade",
    "46.2": "agriculture_food", "46.3": "agriculture_food",
    "47": "retail",
    "49": "transport", "50": "transport", "51": "transport", "52": "transport", "53": "transport",
    "55": "hospitality", "56": "hospitality",
    "58": "it_telecom", "59": "it_telecom", "60": "it_telecom", "61": "it_telecom",
    "62": "it_telecom", "63": "it_telecom",
    "64": "finance", "65": "finance", "66": "finance",
    "68": "real_estate",
    "69": "services", "70": "services", "71": "services", "72": "services", "73": "services",
    "74": "services", "75": "services", "77": "services", "78": "services", "79": "services",
    "80": "services", "81": "services", "82": "services", "85": "services", "86": "services",
    "87": "services", "88": "services", "90": "services", "93": "services", "95": "services",
    "96": "services",
}


def sector_for_okved(code: str | None) -> str:
    if not code:
        return "other"
    # Коды ОКВЭД иерархичны ("46.71.1" ⊂ "46.71" ⊂ "46"), поэтому берем самый длинный префикс.
    code = code.strip()
    matches = [p for p in _PREFIXES if code.startswith(p)]
    return _PREFIXES[max(matches, key=len)] if matches else "other"


@dataclass(frozen=True)
class Sensitivity:
    sign: int
    why: str


# Темы (см. app.news.taxonomy.TOPICS) -> сектор -> чувствительность.
SECTOR_SENSITIVITY: dict[str, dict[str, Sensitivity]] = {
    "key_rate": {
        "construction": Sensitivity(-1, "проектное финансирование и спрос на ипотеку зависят от стоимости денег"),
        "real_estate": Sensitivity(-1, "оценка объектов и стоимость обслуживания долга чувствительны к ставке"),
        "trade_wholesale": Sensitivity(-1, "оборотный капитал оптовиков часто финансируется кредитами"),
        "retail": Sensitivity(-1, "дорогой кредит сдерживает потребительский спрос и финансирование запасов"),
        "auto": Sensitivity(-1, "продажи автомобилей зависят от автокредитования"),
        "manufacturing": Sensitivity(-1, "инвестпроекты и модернизация откладываются при дорогом кредите"),
        "finance": Sensitivity(0, "процентная маржа и стоимость фондирования меняются одновременно"),
        "energy_utilities": Sensitivity(-1, "капиталоемкие инвестпрограммы финансируются долгом"),
        "transport": Sensitivity(-1, "лизинг подвижного состава и техники дорожает"),
    },
    "inflation": {
        "retail": Sensitivity(0, "выручка растет вместе с ценами, но реальный спрос и маржа под давлением"),
        "agriculture_food": Sensitivity(0, "цены реализации растут, но дорожают корма, топливо и логистика"),
        "hospitality": Sensitivity(-1, "рост издержек на продукты и персонал сложно переложить на клиента"),
        "construction": Sensitivity(-1, "растет стоимость материалов и работ по фиксированным контрактам"),
        "services": Sensitivity(-1, "зарплатные издержки растут быстрее выручки"),
    },
    "fx": {
        "mining_oil_gas": Sensitivity(1, "экспортная выручка в валюте растет в рублях при ослаблении рубля"),
        "mining_metals": Sensitivity(1, "экспортная выручка в валюте растет в рублях при ослаблении рубля"),
        "metallurgy": Sensitivity(1, "экспортеры выигрывают от слабого рубля"),
        "chemicals": Sensitivity(1, "экспортная часть выручки выигрывает от слабого рубля"),
        "trade_wholesale": Sensitivity(-1, "импортные закупки дорожают при ослаблении рубля"),
        "retail": Sensitivity(-1, "импортные товары дорожают, растет давление на цены"),
        "auto": Sensitivity(-1, "импорт автомобилей и комплектующих дорожает"),
        "pharma": Sensitivity(-1, "импортные субстанции и препараты дорожают"),
        "it_telecom": Sensitivity(-1, "импортное оборудование дорожает"),
    },
    "fuel_oil": {
        "mining_oil_gas": Sensitivity(1, "цена нефти определяет выручку добывающих компаний"),
        "oil_refining": Sensitivity(0, "маржа зависит от соотношения цен нефти и нефтепродуктов"),
        "fuel_trade": Sensitivity(0, "растет выручка, но регулирование цен на топливо ограничивает маржу"),
        "transport": Sensitivity(-1, "топливо — одна из главных статей затрат"),
        "agriculture_food": Sensitivity(-1, "дорожают топливо для техники и доставка"),
        "retail": Sensitivity(-1, "растут логистические издержки"),
    },
    "consumer_demand": {
        "retail": Sensitivity(1, "выручка напрямую зависит от потребительского спроса"),
        "hospitality": Sensitivity(1, "выручка напрямую зависит от потребительского спроса"),
        "auto": Sensitivity(1, "спрос на автомобили — часть потребительских расходов"),
        "agriculture_food": Sensitivity(1, "спрос на продукты питания"),
        "real_estate": Sensitivity(1, "арендаторы-ритейлеры зависят от трафика"),
    },
    "credit_market": {
        "construction": Sensitivity(1, "продажи и проекты зависят от доступности проектного финансирования и ипотеки"),
        "real_estate": Sensitivity(1, "спрос на объекты зависит от доступности ипотеки"),
        "finance": Sensitivity(1, "объем кредитования формирует доходы"),
        "auto": Sensitivity(1, "продажи автомобилей зависят от доступности автокредитов"),
        "retail": Sensitivity(1, "часть покупок финансируется потребкредитами"),
        "trade_wholesale": Sensitivity(1, "оборотный капитал зависит от доступности кредита"),
    },
    "construction_realestate": {
        "construction": Sensitivity(1, "событие напрямую касается рынка строительства"),
        "real_estate": Sensitivity(1, "событие напрямую касается рынка недвижимости"),
        "metallurgy": Sensitivity(1, "строительство — крупный потребитель металлопроката"),
        "manufacturing": Sensitivity(1, "спрос на стройматериалы и технику"),
    },
    "gold": {
        "mining_metals": Sensitivity(1, "цена золота определяет выручку золотодобытчиков"),
        "finance": Sensitivity(0, "влияет на спрос на инвестиционные продукты"),
    },
    "metals_steel": {
        "metallurgy": Sensitivity(1, "цены на металлы определяют выручку"),
        "construction": Sensitivity(-1, "металл — существенная часть себестоимости"),
        "manufacturing": Sensitivity(-1, "металл — сырье для машиностроения"),
        "auto": Sensitivity(-1, "металл — сырье для автопрома"),
    },
    "energy": {
        "energy_utilities": Sensitivity(1, "тарифы и регулирование определяют выручку"),
        "metallurgy": Sensitivity(-1, "энергоемкое производство"),
        "chemicals": Sensitivity(-1, "энергоемкое производство"),
    },
    "imports_exports": {
        "trade_wholesale": Sensitivity(0, "меняются условия поставок и расчетов с иностранными контрагентами"),
        "mining_oil_gas": Sensitivity(0, "экспортная логистика и расчеты"),
        "metallurgy": Sensitivity(0, "экспортная логистика и расчеты"),
        "agriculture_food": Sensitivity(0, "экспорт урожая и импорт оборудования"),
        "auto": Sensitivity(0, "импорт автомобилей и комплектующих"),
    },
    "sanctions_geopolitics": {
        "trade_wholesale": Sensitivity(-1, "цепочки поставок и платежи с иностранными партнерами"),
        "mining_oil_gas": Sensitivity(-1, "ограничения на экспорт и расчеты"),
        "metallurgy": Sensitivity(-1, "ограничения на экспорт"),
        "finance": Sensitivity(-1, "ограничения на трансграничные операции"),
    },
    "labor": {
        "hospitality": Sensitivity(-1, "трудоемкая отрасль, рост зарплат давит на маржу"),
        "retail": Sensitivity(-1, "трудоемкая отрасль, рост зарплат давит на маржу"),
        "construction": Sensitivity(-1, "дефицит рабочих специальностей"),
        "manufacturing": Sensitivity(-1, "дефицит рабочих специальностей"),
        "it_telecom": Sensitivity(-1, "конкуренция за специалистов"),
        "transport": Sensitivity(-1, "дефицит водителей и рабочих"),
    },
    "budget": {
        "construction": Sensitivity(1, "госзаказ и инфраструктурные проекты"),
        "manufacturing": Sensitivity(1, "госзаказ поддерживает промпроизводство"),
        "energy_utilities": Sensitivity(0, "тарифное регулирование и субсидии"),
    },
    "gdp_industry": {
        "manufacturing": Sensitivity(1, "событие описывает динамику промышленности"),
        "metallurgy": Sensitivity(1, "событие описывает динамику промышленности"),
        "transport": Sensitivity(1, "грузооборот следует за промышленностью"),
    },
    "bonds": {
        "finance": Sensitivity(0, "переоценка портфелей ценных бумаг"),
        "energy_utilities": Sensitivity(-1, "крупные заемщики на облигационном рынке"),
    },
    "corporate_finance": {},
    "deposits": {"finance": Sensitivity(0, "стоимость фондирования")},
    "auto": {"auto": Sensitivity(1, "событие напрямую касается автомобильного рынка")},
}
