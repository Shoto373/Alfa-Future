"""Валидатор конфигурации доменных знаний (SPR4-00). Невалидная конфигурация не публикуется.

    cd backend && python -m app.domain_config.validate config/sectors

Ошибки (error) запрещают публикацию, предупреждения (warning) — нет. Проверяется:
- схема каждого документа (поля, типы, знаки -1/0/+1);
- ссылки: темы чувствительности и эталонов есть в topics, отрасли — в sectors, префиксы ОКВЭД не повторяются;
- конвенция знаков: direction_value.up > 0, down < 0, все значения в [-1; 1];
- эталоны знака (control_cases): «рост ставки — риск для стройки» — перевернутый знак ломает эталон;
- действия: роли из списка, числа в действиях и формулировках эффекта запрещены (числа — только из источников);
- у темы без своих действий для какой-то роли используется общее — это предупреждение.
"""

import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.domain_config.schema import DOCS, ROLES

_DIGIT = re.compile(r"\d")
_OKVED = re.compile(r"^\d{2}(\.\d{1,2}){0,2}(\.\d)?$")


@dataclass
class Issue:
    level: str  # error | warning
    doc: str
    path: str
    message: str

    def as_dict(self) -> dict:
        return asdict(self)


def parse(texts: dict[str, str]) -> tuple[dict, list[Issue]]:
    """YAML-тексты документов → проверенные словари (model_dump) и ошибки разбора/схемы."""
    docs, issues = {}, []
    for name, model in DOCS.items():
        try:
            raw = yaml.safe_load(texts.get(name) or "")
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            where = f"строка {mark.line + 1}" if mark else ""
            issues.append(Issue("error", name, where, f"Ошибка YAML: {getattr(exc, 'problem', exc)}"))
            continue
        try:
            docs[name] = model.model_validate(raw or {}).model_dump(mode="json")
        except ValidationError as exc:
            issues += [Issue("error", name, ".".join(str(p) for p in e["loc"]), e["msg"]) for e in exc.errors()]
    return docs, issues


def _sign(value: float) -> str:
    return "risk" if value < 0 else "opportunity" if value > 0 else "neutral"


def _cross(docs: dict) -> list[Issue]:
    topics, sectors = docs["topics"]["topics"], docs["sectors"]["sectors"]
    out = []
    order = docs["sectors"]["topic_order"]
    for t in order:
        if t not in topics:
            out.append(Issue("error", "sectors", f"topic_order.{t}", f"Темы «{t}» нет в topics"))
    seen: dict[str, str] = {}
    for key, s in sectors.items():
        for t in s["sensitivity"]:
            if t not in topics:
                out.append(Issue("error", "sectors", f"sectors.{key}.sensitivity.{t}", f"Темы «{t}» нет в topics"))
            elif t not in order:
                out.append(Issue("error", "sectors", "topic_order", f"Тема «{t}» используется в чувствительности, но нет в topic_order"))
        for p in s["okved"]:
            if not _OKVED.match(p):
                out.append(Issue("error", "sectors", f"sectors.{key}.okved", f"Префикс ОКВЭД «{p}» в неверном формате"))
            elif p in seen:
                out.append(Issue("error", "sectors", f"sectors.{key}.okved", f"Префикс «{p}» уже у отрасли «{seen[p]}»"))
            seen[p] = key
    return out


def _signs(docs: dict) -> list[Issue]:
    topics, sectors = docs["topics"]["topics"], docs["sectors"]["sectors"]
    out = []
    for key, t in topics.items():
        dv = t.get("direction_value")
        if not dv:
            if t.get("effect"):
                out.append(Issue("warning", "topics", f"topics.{key}", "Нет direction_value: знак эффекта не определится"))
            continue
        if not (dv.get("up", 0) > 0 and dv.get("down", 0) < 0):
            out.append(Issue("error", "topics", f"topics.{key}.direction_value",
                             "Конвенция знаков: up — «темы стало больше» (> 0), down — меньше (< 0)"))
        if any(abs(v) > 1 for v in dv.values()):
            out.append(Issue("error", "topics", f"topics.{key}.direction_value", "Значения направления — от -1 до 1"))
    for n, case in enumerate(docs["sectors"]["control_cases"]):
        t, s = topics.get(case["topic"]), sectors.get(case["sector"])
        if t is None or s is None:
            out.append(Issue("error", "sectors", f"control_cases.{n}", "Эталон ссылается на несуществующую тему или отрасль"))
            continue
        sens = s["sensitivity"].get(case["topic"])
        value = (sens["sign"] if sens else 0) * (t.get("direction_value") or {}).get(case["direction"], 0)
        if _sign(value) != case["expect"]:
            out.append(Issue("error", "sectors", f"sectors.{case['sector']}.sensitivity.{case['topic']}",
                             f"Эталон «{case['why'] or case['topic']}»: событие {case['direction']} для отрасли должно быть "
                             f"«{case['expect']}», а по конфигурации получается «{_sign(value)}» — проверьте знак"))
    return out


def _texts(docs: dict) -> list[Issue]:
    topics = docs["topics"]["topics"]
    out = []
    libs = [(f"topics.{k}.actions", t["actions"]) for k, t in topics.items()] + [("default_actions", docs["topics"]["default_actions"])]
    for path, lib in libs:
        for role, items in lib.items():
            if role != "default" and role not in ROLES:
                out.append(Issue("error", "topics", f"{path}.{role}", f"Неизвестная роль «{role}»"))
            for i, a in enumerate(items):
                if _DIGIT.search(a["text"]):
                    out.append(Issue("error", "topics", f"{path}.{role}.{i}",
                                     "Число в тексте действия: числа в разборе — только из новости, тезисов банка и данных компании"))
    for key, t in topics.items():
        for part in ("effect", "effect_down"):
            for side, text in (t.get(part) or {}).items():
                if _DIGIT.search(text):
                    out.append(Issue("error", "topics", f"topics.{key}.{part}.{side}", "Число в формулировке эффекта"))
        missing = [r for r in ROLES if not t["actions"].get(r) and not t["actions"].get("default")]
        if missing:
            out.append(Issue("warning", "topics", f"topics.{key}.actions",
                             f"Нет своих действий для ролей: {', '.join(missing)} — будут общие действия"))
        if not t["meanings"]:
            out.append(Issue("warning", "topics", f"topics.{key}.meanings", "Нет смысловых описаний: тема найдется только по словам"))
    if not docs["topics"]["default_actions"].get("default"):
        out.append(Issue("error", "topics", "default_actions.default", "Нужно общее действие на случай, когда у темы нет своих"))
    return out


def validate_texts(texts: dict[str, str]) -> tuple[dict, list[Issue]]:
    """Полная проверка YAML-текстов: (документы, ошибки и предупреждения). Публиковать — только без error."""
    docs, issues = parse(texts)
    if len(docs) == len(DOCS):
        issues += _cross(docs) + _signs(docs) + _texts(docs)
    return docs, issues


def read_dir(path: Path) -> dict[str, str]:
    return {name: (path / f"{name}.yaml").read_text(encoding="utf-8") for name in DOCS}


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else Path(__file__).resolve().parents[2] / "config" / "sectors")
    _, issues = validate_texts(read_dir(path))
    for i in issues:
        print(f"{i.level.upper():8} {i.doc}:{i.path}  {i.message}")
    errors = sum(i.level == "error" for i in issues)
    print(f"Ошибок: {errors}, предупреждений: {len(issues) - errors}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
