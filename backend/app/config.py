"""Конфигурация из переменных окружения (читается при каждом обращении — удобно для тестов)."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

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


def frontend_origin() -> str:
    return _env("FRONTEND_ORIGIN", "http://localhost:3000")


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


def rss_refresh_minutes() -> int:
    return int(_env("RSS_REFRESH_MINUTES", "0"))


def llm_settings() -> dict:
    return {
        "base_url": os.environ.get("LLM_BASE_URL", "").rstrip("/"),
        "fallback_base_url": os.environ.get("LLM_FALLBACK_BASE_URL", "").rstrip("/"),
        "api_key": os.environ.get("LLM_API_KEY", ""),
        "model_reasoning": _env("LLM_MODEL_REASONING", "z-ai/glm-5.3-flash"),
        "model_fast": _env("LLM_MODEL_FAST", "deepseek/deepseek-v4.1-flash"),
        "daily_token_limit": int(_env("LLM_DAILY_TOKEN_LIMIT", "400000")),
        "timeout": float(_env("LLM_TIMEOUT_SECONDS", "75")),
        # Провайдер кейса возвращает usage.cost в рублях; бюджет — 500 ₽/день на команду.
        "daily_cost_limit": float(_env("LLM_DAILY_COST_LIMIT", "450")),
    }


def bank_pdf_dir() -> Path | None:
    value = os.environ.get("BANK_PDF_DIR")
    return Path(value) if value and Path(value).is_dir() else None
