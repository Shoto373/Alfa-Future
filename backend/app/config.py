"""Конфигурация из переменных окружения (читается при каждом обращении — удобно для тестов)."""

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.engine import URL

REPO_ROOT = Path(__file__).resolve().parents[2]


RATE_LIMIT_DEFAULTS = {"insights": (30, 120), "questions": (20, 60), "news": (10, 30)}  # в минуту: пользователь, адрес


def rate_limits(scope: str) -> tuple[int, int]:
    """Лимит запросов в минуту на пользователя и на адрес: RATE_LIMIT_<SCOPE>=user,ip; 0 — без лимита."""
    raw = os.environ.get(f"RATE_LIMIT_{scope.upper()}")
    if raw:
        user, _, ip = raw.partition(",")
        return int(user or 0), int(ip or 0)
    return RATE_LIMIT_DEFAULTS[scope]


def secret(name: str) -> str:
    """Секрет из файла (Docker secrets: NAME_FILE=/run/secrets/…) или, для совместимости, из переменной NAME.

    Файл предпочтительнее: значение не видно в `docker inspect`, окружении процесса и выводе compose config."""
    path = os.environ.get(f"{name}_FILE")
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return os.environ.get(name, "")


def database_url() -> str:
    if not os.environ.get("DATABASE_URL") and os.environ.get("PGHOST"):
        return URL.create("postgresql+psycopg", host=os.environ["PGHOST"], port=int(os.environ.get("PGPORT", "5432")),
                          database=os.environ.get("PGDATABASE", "alfa"), username=os.environ.get("PGUSER", "alfa"),
                          password=secret("PGPASSWORD")).render_as_string(hide_password=False)
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

# Деловые разделы, а не общие ленты: в общей ленте ТАСС деловых было около половины.
DEFAULT_RSS = [
    {"name": "Банк России", "url": "https://www.cbr.ru/rss/eventrss"},
    {"name": "Интерфакс", "url": "https://www.interfax.ru/rss.asp"},
    {"name": "РБК", "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/section-economics.xml"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/section-business.xml"},
    {"name": "Коммерсантъ", "url": "https://www.kommersant.ru/RSS/section-finance.xml"},
    {"name": "Ведомости", "url": "https://www.vedomosti.ru/rss/rubric/economics"},
    {"name": "Ведомости", "url": "https://www.vedomosti.ru/rss/rubric/business"},
    {"name": "Ведомости", "url": "https://www.vedomosti.ru/rss/rubric/finance"},
    {"name": "Frank Media", "url": "https://frankmedia.ru/feed"},
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


def oidc_settings() -> dict:
    """Вход через корпоративный IdP (app/auth/oidc.py); пустой OIDC_ISSUER — вход через IdP выключен."""
    return {
        "issuer": os.environ.get("OIDC_ISSUER", "").rstrip("/"),
        "internal_issuer": os.environ.get("OIDC_INTERNAL_ISSUER", "").rstrip("/"),
        "client_id": os.environ.get("OIDC_CLIENT_ID", "alfa-pulse"),
        "client_secret": secret("OIDC_CLIENT_SECRET"),
        "redirect_uri": os.environ.get("OIDC_REDIRECT_URI", "http://localhost:8000/api/v1/auth/oidc/callback"),
        "companies_claim": os.environ.get("OIDC_COMPANIES_CLAIM", "alfa_companies"),
    }


def auth_password_enabled() -> bool:
    """Вход по email и паролю (демо); в пилоте с IdP выключается: AUTH_PASSWORD_ENABLED=0."""
    return _env("AUTH_PASSWORD_ENABLED", "1") != "0"


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
    return int(_env("RSS_MAX_ITEMS", "50"))


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


def pipeline_materiality_batch() -> int:
    """Сколько непроверенных новостей конвейер проверяет на существенность за цикл."""
    return int(_env("PIPELINE_MATERIALITY_BATCH", "40"))


def pipeline_story_labels() -> int:
    """Сколько новых сюжетов конвейер называет моделью за цикл."""
    return int(_env("PIPELINE_STORY_LABELS", "5"))


def pipeline_start_delay() -> float:
    return float(_env("PIPELINE_START_DELAY_SECONDS", "15"))


REASONING_DEFAULTS: dict[str, str] = {}


def llm_settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "fallback_base_url": os.environ.get("LLM_FALLBACK_BASE_URL", "").rstrip("/"),
        "api_key": secret("LLM_API_KEY"),
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
            # Распознавание сканов аналитики банка (SPR3-03) — визуальная модель из списка кейса.
            "vision": _env("LLM_MODEL_VISION", "qwen/qwen3-vl-30b-a3b-instruct"),
        },
        # GLM без ограничения тратит весь лимит на рассуждения; DeepSeek с ним, наоборот, рассуждает дольше.
        "reasoning_effort": os.environ.get("LLM_REASONING_EFFORT", "low"),
        "reasoning_effort_models": [m.strip() for m in _env("LLM_REASONING_EFFORT_MODELS", "glm").split(",") if m.strip()],
        # Рассуждения по ролям: off — выключены, low|medium|high — бюджет рассуждений, пусто — как решит модель.
        # По умолчанию рассуждения решает модель (как раньше): без них черновик быстрее (на эталоне 29 с против 70 с),
        # но выводы беднее. Включить быстрый режим — LLM_REASONING_COMPOSE=off.
        "reasoning": {kind: _env(f"LLM_REASONING_{kind.upper()}", REASONING_DEFAULTS.get(kind, "")).lower()
                      for kind in ("plan", "compose", "review", "qa", "classify")},
        # Лимит токенов в день — только если задан (> 0); основной ограничитель — рубли (daily_cost_limit).
        "daily_token_limit": int(_env("LLM_DAILY_TOKEN_LIMIT", "0")),
        "timeout": float(_env("LLM_TIMEOUT_SECONDS", "75")),
        # Провайдер кейса возвращает usage.cost в рублях; бюджет — 500 ₽/день на команду.
        "daily_cost_limit": float(_env("LLM_DAILY_COST_LIMIT", "450")),
    }


def showcase_per_sector() -> int:
    """Сколько компаний каждой отрасли доступно для регистрации (самые полные данные); 0 — все компании."""
    return int(_env("SHOWCASE_PER_SECTOR", "2"))


def llm_extra_queries() -> bool:
    """Уточняющие запросы модели-исследователя к аналитике банка перед черновиком (≈4 с ожидания)."""
    return _env("LLM_EXTRA_QUERIES", "1") != "0"


def llm_company_share() -> float:
    """Доля общего дневного бюджета LLM, которую может израсходовать одна компания-клиент."""
    return float(_env("LLM_COMPANY_SHARE", "0.2"))


# Статьи бюджета LLM помимо компаний-клиентов: учитываются в llm_usage_companies под ключом «budget:<статья>».
BUDGET_LINE_PREFIX = "budget:"
KB_INGEST_LINE = "budget:kb_ingest"


def llm_line_share(line: str | None) -> float:
    """Доля дневного бюджета для компании-клиента или отдельной статьи (распознавание аналитики — KB_INGEST_LLM_SHARE)."""
    if line == KB_INGEST_LINE:
        return float(_env("KB_INGEST_LLM_SHARE", "0.15"))
    return llm_company_share()


def kb_recorded_dir() -> Path:
    """Записанные ответы модели распознавания по sha256 PDF: демо и тесты без вызова модели и трат бюджета."""
    return Path(_env("KB_RECORDED_DIR", str(Path(__file__).parent / "knowledge" / "recorded")))


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
    return secret("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID", "")


def quality_report_hour() -> int:
    """Час (UTC), после которого уходит ежедневный отчет о качестве; 6 UTC = 9:00 МСК."""
    return int(_env("QUALITY_REPORT_HOUR_UTC", "6"))


def materiality_llm_enabled() -> bool:
    """Проверка существенности новости моделью-классификатором (app.news.materiality). Включена по умолчанию,
    если LLM подключена; MATERIALITY_LLM=0 — только словари и смысловая модель."""
    return _env("MATERIALITY_LLM", "1").lower() in ("1", "true", "yes", "on")


def classify_llm_enabled() -> bool:
    """Модель-классификатор для неуверенных новостей. Выключена: на эталоне и реальной ленте она добавляла
    ложные срабатывания (политика, иностранные компании) и не находила пропущенных деловых новостей
    (python -m app.eval_classify --llm). Включение — CLASSIFY_LLM=1."""
    return _env("CLASSIFY_LLM", "0").lower() in ("1", "true", "yes", "on")



# Источники новостей (SPR3-02): вес доверия, лицензия и частота опроса — у каждого источника.
# license: "full" — можно хранить полный текст; "lead" — только заголовок и лид (лицензированные ленты).
SOURCE_TRUST = {"Банк России": 1.0, "Интерфакс": 0.95, "РБК": 0.85, "Коммерсантъ": 0.9, "Ведомости": 0.9,
                "Frank Media": 0.75}
LICENSED_FEEDS = [
    {"name": "Интерфакс", "format": "interfax", "file": "interfax.xml", "trust": 0.95},
    {"name": "ПРАЙМ", "format": "prime", "file": "prime.json", "trust": 0.9},
]


def _source(kind: str, name: str, url: str = "", **extra) -> dict:
    sid = f"{kind}:{hashlib.sha1(f'{name}|{url}'.encode()).hexdigest()[:8]}"
    # interval_minutes=0 — опрос в каждом цикле конвейера (RSS_REFRESH_MINUTES); больше — реже, для платных лент.
    base = {"id": sid, "kind": kind, "name": name, "url": url, "trust": SOURCE_TRUST.get(name, 0.8),
            "license": "full", "interval_minutes": 0}
    return {**base, **extra}


def news_sources() -> list[dict]:
    """Реестр источников: RSS из RSS_SOURCES, лицензированные ленты (заглушка из LICENSED_FEED_DIR),
    ручные материалы из MANUAL_NEWS_FILE. SOURCES_FILE (JSON-список) полностью заменяет реестр."""
    path = os.environ.get("SOURCES_FILE")
    if path:
        return [_source(s["kind"], s["name"], s.get("url", ""), **{k: v for k, v in s.items() if k not in ("kind", "name", "url")})
                for s in json.loads(Path(path).read_text(encoding="utf-8"))]
    out = [_source("rss", s["name"], s["url"]) for s in rss_sources()]
    feed_dir = licensed_feed_dir()
    if feed_dir:
        out += [_source("licensed", f["name"], str(feed_dir / f["file"]), format=f["format"], trust=f["trust"],
                        license="lead") for f in LICENSED_FEEDS]
    manual = os.environ.get("MANUAL_NEWS_FILE")
    if manual:
        out.append(_source("manual", "Редакция Альфа.Пульса", manual, trust=0.9))
    return out


def licensed_feed_dir() -> Path | None:
    """Каталог заглушки лицензированных лент (формат Интерфакс/ПРАЙМ). Без договора реальные ленты не подключаются."""
    value = os.environ.get("LICENSED_FEED_DIR", "").strip()
    return Path(value) if value else None


def otlp_endpoint() -> str:
    """Локальный коллектор трасс OTLP/HTTP (Tempo из профиля monitoring); пусто — трассы не экспортируются."""
    return os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip().rstrip("/")


def metrics_token() -> str:
    """Токен для /metrics и приемника алертов; пусто — /metrics открыт (в production nginx его не публикует)."""
    return secret("METRICS_TOKEN")


def ranking_weights_file() -> str:
    """Другой файл весов ранжирования (кандидат калибровки); пусто — app/ranking_weights.json."""
    return os.environ.get("RANKING_WEIGHTS_FILE", "").strip()


def story_similarity() -> float:
    """Порог смысловой близости заголовков для объединения новостей в сюжет."""
    return float(_env("STORY_SIMILARITY", "0.78"))
