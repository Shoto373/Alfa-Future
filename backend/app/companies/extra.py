"""Дополнительные сведения, которые компания сообщила о себе сама.

Данные кейса (CSV) не знают, какая доля долга под плавающей ставкой или сколько
выручки в валюте, а от этого зависит, как новость скажется на компании.
Администратор компании заполняет несколько ключевых долей и свободный текст
(можно загрузить из файла). Доли становятся признаками чувствительности
(влияют на ленту и выводы), текст — источником «Сведения от компании» для агента.

Кроме текста можно приложить файлы CSV и PDF (выгрузки, отчеты, презентации):
из них извлекается текст, и он становится частью того же источника.

Хранится в app_state под ключом company_extra:<id>. Текст и файлы — недоверенные данные:
при сохранении из них вырезаются похожие на инструкции фрагменты.
"""

import csv
import io
import time
import uuid
from datetime import datetime, timezone

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app import database
from app.text import safe_text

KEY = "company_extra:"
NOTES_LIMIT = 15000
MEMO_SECONDS = 5.0
FILE_MAX_BYTES = 5 * 1024 * 1024
FILE_TEXT_LIMIT = 20000   # символов текста из одного файла
MAX_FILES = 10
CSV_MAX_ROWS = 300
PROMPT_FILE_CHARS = 3000  # сколько текста файла видит модель: новость остается главным источником
KINDS = {"pdf": "PDF", "csv": "CSV"}


class FileError(ValueError):
    """Файл не подходит: формат, размер или в нем нет текста."""

# Доли в процентах (0–100): подпись, тема новостей, знак эффекта при «up» темы и вес.
# Знаки — в соглашении composer: up для fx — ослабление рубля, для key_rate — рост ставки.
SHARES = {
    "floating_debt_share": {
        "label": "Кредиты с плавающей ставкой",
        "exposures": [("key_rate", -1, 1.4, "рост ставки сразу увеличивает расходы на проценты"),
                      ("credit_market", 1, 0.6, "условия кредитования напрямую меняют стоимость долга")],
    },
    "fx_revenue_share": {
        "label": "Валютная выручка",
        "exposures": [("fx", 1, 1.2, "ослабление рубля увеличивает рублевую выручку"),
                      ("imports_exports", 1, 0.6, "условия экспорта влияют на выручку")],
    },
    "import_share": {
        "label": "Импорт в закупках",
        "exposures": [("fx", -1, 1.2, "ослабление рубля удорожает закупки"),
                      ("imports_exports", -1, 0.6, "пошлины и ограничения на импорт влияют на закупки"),
                      ("logistics", -1, 0.4, "поставки зависят от логистики")],
    },
}

_memo: dict[str, tuple[float, dict | None]] = {}


def get(company_id: str) -> dict | None:
    now = time.monotonic()
    hit = _memo.get(company_id)
    if hit and now - hit[0] < MEMO_SECONDS:
        return hit[1]
    value = database.state(KEY + company_id)
    _memo[company_id] = (now, value)
    return value


def _clean(text: str) -> str:
    # Построчно: абзацы и строки таблиц сохраняются.
    return "\n".join(filter(None, (safe_text(line) for line in text.strip().splitlines())))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _store(company_id: str, value: dict) -> dict:
    with database.session() as db:
        database.set_state(KEY + company_id, value, db)
    _memo[company_id] = (time.monotonic(), value)
    return value


def save(company_id: str, shares: dict[str, float | None], notes: str, user_id: str) -> dict:
    current = get(company_id) or {}
    return _store(company_id, {
        "shares": {k: round(float(v), 1) for k, v in shares.items() if k in SHARES and v is not None},
        "notes": _clean(notes)[:NOTES_LIMIT],
        "files": current.get("files", []),
        "updated_at": _now(),
        "updated_by": user_id,
    })


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _csv_text(data: bytes) -> str:
    raw = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(raw), dialect) if any(cell.strip() for cell in r)]
    if not rows:
        raise FileError("В CSV нет данных")
    header, body = rows[0], rows[1:CSV_MAX_ROWS + 1]
    # Строка таблицы «столбец: значение» читается и моделью, и проверкой чисел.
    lines = ["Столбцы: " + ", ".join(h.strip() for h in header)]
    lines += ["; ".join(f"{h.strip()}: {v.strip()}" for h, v in zip(header, r) if v.strip()) for r in body]
    if len(rows) - 1 > CSV_MAX_ROWS:
        lines.append(f"(показаны первые {CSV_MAX_ROWS} строк из {len(rows) - 1})")
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "").strip() for page in reader.pages[:50]]
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise FileError("Не удалось прочитать PDF") from exc
    text = "\n".join(p for p in pages if p)
    if len(text) < 40:
        raise FileError("В PDF нет текстового слоя (скан?) — загрузите версию с текстом или CSV")
    return text


def add_file(company_id: str, name: str, data: bytes, user_id: str) -> dict:
    """Извлекает текст из CSV или PDF и добавляет файл к сведениям компании."""
    name = name.strip().replace("\\", "/").split("/")[-1][:120] or "файл"
    kind = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if kind not in KINDS:
        raise FileError("Поддерживаются файлы CSV и PDF")
    if not data:
        raise FileError("Файл пустой")
    if len(data) > FILE_MAX_BYTES:
        raise FileError("Файл больше 5 МБ")
    current = get(company_id) or {"shares": {}, "notes": ""}
    files = current.get("files", [])
    if len(files) >= MAX_FILES:
        raise FileError(f"Можно приложить не больше {MAX_FILES} файлов — удалите ненужные")
    text = _clean(_pdf_text(data) if kind == "pdf" else _csv_text(data))[:FILE_TEXT_LIMIT]
    if not text:
        raise FileError("В файле не нашлось текста")
    entry = {"file_id": uuid.uuid4().hex[:12], "name": name, "kind": kind, "size": len(data),
             "chars": len(text), "uploaded_at": _now(), "text": text}
    _store(company_id, {**current, "files": files + [entry], "updated_at": _now(), "updated_by": user_id})
    return entry


def delete_file(company_id: str, file_id: str, user_id: str) -> bool:
    current = get(company_id) or {}
    files = current.get("files", [])
    kept = [f for f in files if f["file_id"] != file_id]
    if len(kept) == len(files):
        return False
    _store(company_id, {**current, "files": kept, "updated_at": _now(), "updated_by": user_id})
    return True


def updated_at(company_id: str) -> datetime | None:
    """Время последнего изменения: карточки, собранные раньше, считаются устаревшими."""
    value = get(company_id)
    return datetime.fromisoformat(value["updated_at"]) if value else None


def signature(company_id: str) -> str:
    value = get(company_id)
    return value["updated_at"] if value else "-"


def fmt(share: float) -> str:
    return f"{share:g}%".replace(".", ",")


def exposures(company_id: str) -> list[dict]:
    """Признаки чувствительности из сообщенных долей (feature = extra.<ключ>)."""
    value = get(company_id)
    out = []
    for key, share in ((value or {}).get("shares") or {}).items():
        if key not in SHARES or share <= 0:
            continue
        spec = SHARES[key]
        for topic, sign, weight, why in spec["exposures"]:
            out.append({"topic": topic, "weight": round(weight * min(1.0, 0.3 + share / 100), 3), "sign": sign,
                        "feature": f"extra.{key}", "value": share,
                        "why": f"{spec['label']} — {fmt(share)} (со слов компании): {why}", "origin": "company_reported"})
    return out


def text(value: dict | None, file_chars: int | None = None) -> str:
    """Сведения одним текстом — источник client:extra для агента и проверки чисел.

    file_chars ограничивает текст каждого файла (для модели); без него — весь текст (для проверки чисел).
    """
    if not value:
        return ""
    lines = [f"{SHARES[k]['label']}: {fmt(v)}." for k, v in (value.get("shares") or {}).items() if k in SHARES]
    if value.get("notes"):
        lines.append(value["notes"])
    for f in value.get("files", []):
        body = f["text"] if file_chars is None else f["text"][:file_chars]
        lines.append(f"Файл «{f['name']}»: {body}")
    return " ".join(lines)
