"""Сценарии «что если» (SPR4-02): чувствительность компании к ставке, курсу и цене сырья.

Только прозрачные формулы — модель чисел не считает. Каждый вход подписан происхождением:
client_data (данные кейса), company_reported (сообщила компания), estimate (отраслевая оценка из доменной
конфигурации), user (ввел пользователь), bank (прогноз банка). Не хватает данных — явный отказ, а не ноль.
Это оценка чувствительности, а не инвестиционная рекомендация.
"""

from dataclasses import asdict, dataclass, field

from app.companies import extra, profiles
from app.domain_config import runtime

DEFAULT_FLOATING = 0.5  # доля долга с плавающей ставкой, если компания ее не сообщила (допущение)
SCENARIOS = ("key_rate", "fx", "commodity")
LIMITS = {"key_rate": (-5.0, 5.0), "fx": (-40.0, 40.0), "commodity": (-60.0, 60.0)}


class ScenarioError(Exception):
    """Нет данных для расчета: интерфейс показывает, каких входов не хватает и где их взять."""

    def __init__(self, message: str, missing: list[str]):
        super().__init__(message)
        self.missing = missing


@dataclass
class Input:
    name: str
    label: str
    value: float
    unit: str
    origin: str  # client_data | company_reported | estimate | user | bank
    source: str


@dataclass
class Result:
    scenario: str
    shock: float
    shock_unit: str
    effect_rub: float  # + выгода, − расходы/потери за год
    text: str
    formula: str
    inputs: list[Input] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def mln(value: float) -> str:
    """Рубли в «млн ₽» для текста: ≈ 87 млн ₽ (до 10 млн — с одним знаком)."""
    m = abs(value) / 1e6
    return (f"{m:.1f}" if m < 10 else f"{m:.0f}").replace(".", ",") + " млн ₽"


def _pct(share: float) -> str:
    return f"{share * 100:g}%".replace(".", ",")


def _company(company_id: str) -> dict:
    c = profiles.get(company_id)
    if c is None:
        raise ScenarioError("Компания не найдена", ["company"])
    return c


def _reported(company_id: str, key: str) -> float | None:
    value = ((extra.get(company_id) or {}).get("shares") or {}).get(key)
    return None if value is None else value / 100


def _revenue(c: dict) -> Input:
    if not c.get("revenue") or c["revenue"] <= 0:
        raise ScenarioError("В данных кейса нет выручки компании — сценарий не посчитать", ["revenue"])
    return Input("revenue", "Выручка за год", c["revenue"], "₽", "client_data", "client:profile")


def key_rate(company_id: str, shock_pp: float, debt: float | None = None, floating_share: float | None = None) -> Result:
    """Ставка → процентные расходы за год: долг × доля плавающих ставок × изменение ставки."""
    c = _company(company_id)
    inputs = []
    if debt is not None:
        inputs.append(Input("debt", "Долг (ваша оценка)", debt, "₽", "user", "user"))
    else:
        ratio = runtime.SECTOR_FINANCE.get(c["sector"], {}).get("debt_to_revenue")
        if ratio is None:
            raise ScenarioError("Для отрасли нет оценки долговой нагрузки — укажите долг компании", ["debt"])
        revenue = _revenue(c)
        debt = revenue.value * ratio
        inputs += [revenue, Input("debt_to_revenue", "Долг/выручка, средний по отрасли", ratio, "×", "estimate", "config:sectors")]
    if floating_share is None:
        floating_share = _reported(company_id, "floating_debt_share")
        origin = ("company_reported", "client:extra") if floating_share is not None else ("estimate", "assumption")
        floating_share = DEFAULT_FLOATING if floating_share is None else floating_share
    else:
        origin = ("user", "user")
    inputs.append(Input("floating_share", "Доля долга с плавающей ставкой", floating_share, "доля", *origin))
    effect = -debt * floating_share * shock_pp / 100
    debt_text = f"долг ≈ {mln(debt)}"
    formula = f"{debt_text} × {_pct(floating_share)} с плавающей ставкой × {shock_pp:+g} п.п."
    caveats = ["Долг оценен по отраслевому коэффициенту: остатков долга в данных кейса нет"] if inputs[-2].origin == "estimate" else []
    caveats.append("Долг с фиксированной ставкой переоценивается при рефинансировании — в оценку за год не входит")
    sign = "вырастут" if effect < 0 else "снизятся"
    text = f"При изменении ставки на {shock_pp:+g} п.п. процентные расходы {sign} ≈ на {mln(effect)} в год"
    return Result("key_rate", shock_pp, "п.п.", effect, text, formula, inputs, caveats)


def fx(company_id: str, shock_pct: float, fx_revenue_share: float | None = None, import_share: float | None = None) -> Result:
    """Курс → выручка и закупки ВЭД: shock_pct > 0 — рубль слабее на столько процентов."""
    c = _company(company_id)
    rev_share = fx_revenue_share if fx_revenue_share is not None else _reported(company_id, "fx_revenue_share")
    imp_share = import_share if import_share is not None else _reported(company_id, "import_share")
    if rev_share is None and imp_share is None:
        raise ScenarioError("Нет долей валютной выручки и импорта — укажите их в профиле компании или в расчете",
                            ["fx_revenue_share", "import_share"])
    inputs, parts, effect = [], [], 0.0
    if rev_share is not None:
        revenue = _revenue(c)
        origin = ("user", "user") if fx_revenue_share is not None else ("company_reported", "client:extra")
        inputs += [revenue, Input("fx_revenue_share", "Доля валютной выручки", rev_share, "доля", *origin)]
        effect += revenue.value * rev_share * shock_pct / 100
        parts.append(f"выручка {mln(revenue.value)} × {_pct(rev_share)} валютной")
    if imp_share is not None:
        purchases = (c.get("suppliers") or {}).get("total_amount")
        if not purchases:
            raise ScenarioError("В данных кейса нет платежей поставщикам — импортные закупки не оценить", ["purchases"])
        origin = ("user", "user") if import_share is not None else ("company_reported", "client:extra")
        inputs += [Input("purchases", "Платежи поставщикам за период данных", purchases, "₽", "client_data", "client:payments"),
                   Input("import_share", "Доля импорта в закупках", imp_share, "доля", *origin)]
        effect -= purchases * imp_share * shock_pct / 100
        parts.append(f"− закупки {mln(purchases)} × {_pct(imp_share)} импорта")
    formula = f"({' '.join(parts)}) × {shock_pct:+g}% к курсу"
    sign = "выигрывает" if effect > 0 else "теряет"
    text = f"При изменении курса рубля на {shock_pct:+g}% (плюс — рубль слабее) компания {sign} ≈ {mln(effect)} в год"
    return Result("fx", shock_pct, "%", effect, text, formula, inputs, ["Без учета хеджирования и пересмотра цен в контрактах"])


def commodity(company_id: str, shock_pct: float, exposure: float | None = None) -> Result:
    """Цена сырья → маржа сырьевой отрасли: выручка × доля, зависящая от цены сырья × изменение цены."""
    c = _company(company_id)
    model = runtime.SECTOR_FINANCE.get(c["sector"], {}).get("commodity")
    if model is None and exposure is None:
        raise ScenarioError("Отрасль компании не сырьевая — укажите долю выручки, зависящую от цены сырья", ["exposure"])
    revenue = _revenue(c)
    share = exposure if exposure is not None else model["revenue_exposure"]
    label = model["label"] if model else "сырье"
    origin = ("user", "user") if exposure is not None else ("estimate", "config:sectors")
    inputs = [revenue, Input("exposure", f"Доля выручки, зависящая от цены ({label})", share, "доля", *origin)]
    effect = revenue.value * share * shock_pct / 100
    formula = f"выручка {mln(revenue.value)} × {_pct(share)} × {shock_pct:+g}% к цене ({label})"
    sign = "растет" if effect > 0 else "снижается"
    text = f"При изменении цены ({label}) на {shock_pct:+g}% валовая маржа {sign} ≈ на {mln(effect)} в год"
    return Result("commodity", shock_pct, "%", effect, text, formula, inputs,
                  ["Себестоимость считается неизменной: эффект ложится на маржу целиком"])


def simulate(company_id: str, scenario: str, shock: float, **overrides) -> Result:
    if scenario not in SCENARIOS:
        raise ScenarioError(f"Неизвестный сценарий: {scenario}", ["scenario"])
    low, high = LIMITS[scenario]
    if not low <= shock <= high:
        raise ScenarioError(f"Изменение должно быть от {low:g} до {high:g}", ["shock"])
    fn = {"key_rate": key_rate, "fx": fx, "commodity": commodity}[scenario]
    return fn(company_id, shock, **{k: v for k, v in overrides.items() if v is not None})
