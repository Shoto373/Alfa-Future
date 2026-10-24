"""Конфигурация из переменных окружения (читается при каждом обращении — удобно для тестов)."""

import os
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    if not os.environ.get("DATABASE_URL") and os.environ.get("PGHOST"):
        from sqlalchemy.engine import URL
        return URL.create("postgresql+psycopg", host=os.environ["PGHOST"], port=int(os.environ.get("PGPORT", "5432")),
                          database=os.environ.get("PGDATABASE", "alfa"), username=os.environ.get("PGUSER", "alfa"),
                          password=os.environ.get("PGPASSWORD", "")).render_as_string(hide_password=False)
    return _env("DATABASE_URL", "postgresql://alfa:alfa-local@127.0.0.1:5432/alfa")


def database_schema() -> str:
    return _env("DATABASE_SCHEMA", "public")

ALLOWED_MODELS = (
    "gemma-4-26b-a4b",
    "glm-5.3-flash",
    "qwen3.6-35b-a3b",
    "deepseek-v4.1-flash",
    "qwen3-vl-30b-a3b-instruct",
    "kimi-k2.6",
)

DEFAULT_RSS = [
    {"name": "Банк России", "url": "https://www.cbr.ru/rss/eventrss"},
    {"name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp"},
    {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"},
    {"name": "ТАСС", "url": "https://tass.ru/rss/v2.xml"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/news.xml"},
]


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def data_dir() -> Path:
    return Path(_env("DATA_DIR", str(REPO_ROOT / "data" / "synthetic")))


def fallback_data_dir() -> Path:
    return Path(_env("FALLBACK_DATA_DIR", str(REPO_ROOT / "data" / "synthetic")))


def runtime_dir() -> Path:
    path = Path(_env("RUNTIME_DIR", str(REPO_ROOT / "data" / "runtime")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def profiles_path() -> Path:
    return Path(_env("PROFILES_PATH", str(runtime_dir() / "companies.json")))


def analysis_timeout() -> float:
    return float(_env("ANALYSIS_TIMEOUT_SECONDS", "150"))


def session_ttl_hours() -> float:
    """Срок жизни сессии; продлевается при активности (скользящее окно)."""
    return float(_env("SESSION_TTL_HOURS", "12"))


def operator_emails() -> set[str]:
    """Сотрудники банка (email через запятую): метрики, расходы LLM, журнал инструментов, ручной сбор новостей.

    Администратор компании — представитель клиента, а не банка: эти данные сводные по всем клиентам.
    Пусто — служебные адреса закрыты для всех."""
    return {e.strip().lower() for e in os.environ.get("OPERATOR_EMAILS", "").split(",") if e.strip()}


def frontend_origin() -> str:
    return _env("FRONTEND_ORIGIN", "http://localhost:3000")


def frontend_origins() -> list[str]:
    """Allow both loopback names on the configured port for local development."""
    origin = frontend_origin().rstrip("/")
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or parts.hostname not in ("localhost", "127.0.0.1"):
        return [origin]
    alias = "127.0.0.1" if parts.hostname == "localhost" else "localhost"
    netloc = f"{alias}:{parts.port}" if parts.port is not None else alias
    return [origin, parts._replace(netloc=netloc).geturl()]


def rss_sources() -> list[dict]:
    raw = os.environ.get("RSS_SOURCES")
    if raw is None:
        return DEFAULT_RSS
    out = []
    for part in raw.split(","):
        if "|" in part:
            name, url = part.split("|", 1)
            out.append({"name": name.strip(), "url": url.strip()})
    return out


def rss_max_items() -> int:
    return int(_env("RSS_MAX_ITEMS", "30"))


def rss_full_text() -> bool:
    """Скачивать полный текст статьи по ссылке из RSS (анонс ленты — запасной вариант)."""
    return _env("RSS_FULL_TEXT", "1").lower() not in ("0", "false", "no", "off")


def demo_accounts() -> bool:
    """Готовые учетные записи для локальной проверки (app/demo_accounts.py); только локальный compose.yaml."""
    return _env("DEMO_ACCOUNTS", "0") == "1"


def demo_password() -> str:
    return _env("DEMO_PASSWORD", "alfa-demo-2026")


def rss_refresh_minutes() -> int:
    """Период автоматического конвейера (сбор RSS и разборы); 0 — выключен."""
    return int(_env("RSS_REFRESH_MINUTES", "15"))


def pipeline_rules_top() -> int:
    """Сколько самых релевантных новостей ленты конвейер разбирает правилами на пару «компания — роль»."""
    return int(_env("PIPELINE_RULES_TOP", "10"))


def pipeline_llm_per_cycle() -> int:
    """Сколько карточек конвейер пересчитывает моделью за цикл (0 — только правила)."""
    return int(_env("PIPELINE_LLM_PER_CYCLE", "5"))


def pipeline_llm_share() -> float:
    """Доля дневного лимита LLM, которую может потратить конвейер; остальное — запросам пользователей."""
    return float(_env("PIPELINE_LLM_SHARE", "0.5"))


def pipeline_story_labels() -> int:
    """Сколько новых сюжетов конвейер называет моделью за цикл."""
    return int(_env("PIPELINE_STORY_LABELS", "5"))


def pipeline_start_delay() -> float:
    return float(_env("PIPELINE_START_DELAY_SECONDS", "15"))


def llm_settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "fallback_base_url": os.environ.get("LLM_FALLBACK_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        # Модель на каждую роль агента. Выбор по сравнению всех моделей кейса на одной реальной задаче:
        # DeepSeek пишет самые конкретные выводы (≈26 с, 0,3 ₽), GLM быстрая и точная для плана и проверки
        # (≈13 с, 0,1 ₽), Kimi-K2.6 тратит >7000 токенов на рассуждения и не укладывается во время ответа.
        # Критик — другая модель, чем автор разбора, чтобы проверка была независимой.
        "models": {
            "plan": _env("LLM_MODEL_PLAN", "z-ai/glm-5.3-flash"),
            "compose": _env("LLM_MODEL_COMPOSE", "deepseek/deepseek-v4.1-flash"),
            "review": _env("LLM_MODEL_REVIEW", "z-ai/glm-5.3-flash"),
            "qa": _env("LLM_MODEL_QA", "deepseek/deepseek-v4.1-flash"),
            # Классификация неуверенных новостей — Gemma 4 (рекомендована кейсом для классификации).
            "classify": _env("LLM_MODEL_CLASSIFY", "google/gemma-4-26b-a4b-it"),
        },
        # GLM без ограничения тратит весь лимит на рассуждения; DeepSeek с ним, наоборот, рассуждает дольше.
        "reasoning_effort": os.environ.get("LLM_REASONING_EFFORT", "low"),
        "reasoning_effort_models": [m.strip() for m in _env("LLM_REASONING_EFFORT_MODELS", "glm").split(",") if m.strip()],
        "daily_token_limit": int(_env("LLM_DAILY_TOKEN_LIMIT", "400000")),
        "timeout": float(_env("LLM_TIMEOUT_SECONDS", "75")),
        # Провайдер кейса возвращает usage.cost в рублях; бюджет — 500 ₽/день на команду.
        "daily_cost_limit": float(_env("LLM_DAILY_COST_LIMIT", "450")),
    }


def llm_company_share() -> float:
    """Доля общего дневного бюджета LLM, которую может израсходовать одна компания-клиент."""
    return float(_env("LLM_COMPANY_SHARE", "0.2"))


def llm_user_limits() -> dict[str, int]:
    """Запросы к модели на пользователя в час: «Пересчитать» и вопросы в чате (0 — без ограничения)."""
    return {"refresh": int(_env("LLM_USER_REFRESH_PER_HOUR", "10")),
            "question": int(_env("LLM_USER_QUESTIONS_PER_HOUR", "30"))}


def llm_economy() -> tuple[float, str]:
    """С какой доли дневного лимита черновики и ответы чата пишет более дешевая модель, и какая."""
    return float(_env("LLM_ECONOMY_AT", "0.8")), _env("LLM_MODEL_ECONOMY", "z-ai/glm-5.3-flash")


# Оценка цены, ₽ за 1000 токенов (вход + выход), с запасом — по замерам выбора моделей (см. llm_settings).
# Нужна для резерва бюджета до ответа и для учета, если шлюз не вернул usage.cost; списывается факт.
LLM_PRICES = {"deepseek": 0.06, "glm": 0.04, "gemma": 0.03, "qwen3-vl": 0.06, "qwen": 0.06, "kimi": 0.6}
LLM_DEFAULT_PRICE = 0.1


def llm_price_per_1k(model: str) -> float:
    """Цена модели по первому совпавшему фрагменту имени; LLM_PRICES=deepseek=0.05,glm=0.03 переопределяет."""
    overrides = {}
    for part in os.environ.get("LLM_PRICES", "").split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            overrides[key.strip().lower()] = float(value)
    name = model.lower()
    for prices in (overrides, LLM_PRICES):
        for key, price in prices.items():
            if key in name:
                return price
    return LLM_DEFAULT_PRICE


def bank_pdf_dir() -> Path | None:
    value = os.environ.get("BANK_PDF_DIR")
    return Path(value) if value and Path(value).is_dir() else None


def embeddings_settings() -> dict:
    """Локальная embedding-модель для смыслового сравнения (не генеративная LLM — разрешена кейсом)."""
    return {
        "enabled": _env("EMBEDDINGS_ENABLED", "1").lower() not in ("0", "false", "no", "off"),
        "model": _env("EMBEDDINGS_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
        "cache_dir": os.environ.get("EMBEDDINGS_CACHE_DIR") or None,
        "batch_size": int(_env("EMBEDDINGS_BATCH_SIZE", "32")),
        # Векторы хранятся в PostgreSQL (pgvector); 0 — только в памяти процесса.
        "persist": _env("EMBEDDINGS_PERSIST", "1").lower() not in ("0", "false", "no", "off"),
    }


def redis_url() -> str | None:
    """Общий кэш ленты и служебных значений; без адреса — кэш в памяти процесса."""
    return os.environ.get("REDIS_URL") or None


def feed_cache_seconds() -> int:
    return int(_env("FEED_CACHE_SECONDS", "300"))


def warm_feeds_on_start() -> bool:
    return _env("WARM_FEEDS_ON_START", "1").lower() not in ("0", "false", "no", "off")


def telegram_settings() -> tuple[str, str]:
    """Бот для ежедневного отчета о качестве (тот же, что у мониторинга сервера)."""
    return os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", "")


def quality_report_hour() -> int:
    """Час (UTC), после которого уходит ежедневный отчет о качестве; 6 UTC = 9:00 МСК."""
    return int(_env("QUALITY_REPORT_HOUR_UTC", "6"))


def classify_llm_enabled() -> bool:
    """Модель-классификатор для неуверенных новостей. Выключена: на эталоне и реальной ленте она добавляла
    ложные срабатывания (политика, иностранные компании) и не находила пропущенных деловых новостей
    (python -m app.eval_classify --llm). Включение — CLASSIFY_LLM=1."""
    return _env("CLASSIFY_LLM", "0").lower() in ("1", "true", "yes", "on")
