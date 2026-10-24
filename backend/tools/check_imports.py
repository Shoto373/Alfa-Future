"""Проверка архитектуры backend: слои без циклов, импорты в начале модулей, функции не длиннее 80 строк.

    cd backend && python tools/check_imports.py      # код выхода 1 и список нарушений, если они есть

Слои снизу вверх; модуль может импортировать только свой или нижние слои:
  core     — config, database, models, cache, vector_store, embeddings, vectors, llm, llm_usage, notify, errors, schemas, text
  domain   — companies, news, knowledge, учетные записи (auth.store, auth.security, auth.schemas)
  ranking  — ranking
  agent    — agent
  services — storage, pipeline, warmup, quality, демо, оценка качества, перенос данных, smoke
  api      — api, auth.deps, auth.router, main
Импорт внутри функции скрывает зависимость и цикл — разрешен только для необязательной библиотеки
с пометкой «# optional» в той же строке. Тесты — tests/test_architecture.py.
"""

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
MAX_FUNCTION_LINES = 80

LAYERS = [
    ("core", ["app.config", "app.database", "app.models", "app.cache", "app.vector_store", "app.embeddings", "app.vectors",
              "app.llm", "app.llm_usage", "app.notify", "app.errors", "app.schemas", "app.text"]),
    ("domain", ["app.companies", "app.news", "app.knowledge", "app.auth.store", "app.auth.security", "app.auth.schemas"]),
    ("ranking", ["app.ranking"]),
    ("agent", ["app.agent"]),
    ("services", ["app.storage", "app.pipeline", "app.warmup", "app.quality", "app.demo", "app.demo_accounts",
                  "app.precompute_demo", "app.eval_quality", "app.eval_classify", "app.legacy_import", "app.smoke"]),
    ("api", ["app.api", "app.auth.deps", "app.auth.router", "app.main"]),
]
PACKAGES = {"app", "app.agent", "app.api", "app.auth", "app.companies", "app.knowledge", "app.news"}  # пустые __init__


def modules() -> dict[str, Path]:
    out = {}
    for path in sorted(APP.rglob("*.py")):
        name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        out[name.removesuffix(".__init__")] = path
    return out


def layer_of(module: str) -> int | None:
    best = None
    for rank, (_, prefixes) in enumerate(LAYERS):
        for prefix in prefixes:
            if (module == prefix or module.startswith(prefix + ".")) and (best is None or len(prefix) > best[1]):
                best = (rank, len(prefix))
    return best[0] if best else None


def _targets(module: str, path: Path, node: ast.AST, known: dict[str, Path]) -> list[str]:
    if isinstance(node, ast.Import):
        names = [a.name for a in node.names]
    else:
        base = node.module or ""
        if node.level:
            parts = module.split(".") if path.name == "__init__.py" else module.split(".")[:-1]
            base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
        names = [f"{base}.{a.name}" for a in node.names] + [base]
    out = []
    for name in names:
        while name and name not in known and "." in name:
            name = name.rsplit(".", 1)[0]
        if name in known and name != module and name.startswith("app"):
            out.append(name)
    return out


def analyze() -> tuple[dict[str, set[str]], list[str]]:
    """Граф импортов app.* и список нарушений (слои, импорты в функциях, длинные функции, модули вне слоев)."""
    known = modules()
    graph: dict[str, set[str]] = defaultdict(set)
    problems: list[str] = []
    for module, path in known.items():
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        # Импорт в функции — нарушение; на уровне модуля (в том числе внутри if/try) — нет.
        in_function = {id(n) for f in ast.walk(tree) if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
                       for n in ast.walk(f) if isinstance(n, (ast.Import, ast.ImportFrom))}
        if module not in PACKAGES and layer_of(module) is None:
            problems.append(f"{module}: модуль не отнесен ни к одному слою (LAYERS в tools/check_imports.py)")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                targets = _targets(module, path, node, known)
                if id(node) in in_function and "# optional" not in lines[node.lineno - 1]:
                    names = ", ".join(a.name for a in node.names)
                    problems.append(f"{module}:{node.lineno}: импорт внутри функции ({names}) — перенесите в начало модуля")
                graph[module].update(targets)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = node.end_lineno - node.lineno + 1
                if size > MAX_FUNCTION_LINES:
                    problems.append(f"{module}:{node.lineno}: функция {node.name} — {size} строк (предел {MAX_FUNCTION_LINES})")
    for module, deps in graph.items():
        mine = layer_of(module)
        for dep in deps:
            theirs = layer_of(dep)
            if mine is not None and theirs is not None and theirs > mine:
                problems.append(f"{module} → {dep}: слой «{LAYERS[mine][0]}» не импортирует верхний слой «{LAYERS[theirs][0]}»")
    problems += [f"цикл импортов: {' → '.join(c)}" for c in cycles(graph)]
    return graph, problems


def cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Сильно связные компоненты больше одного модуля (алгоритм Тарьяна)."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []

    def visit(v: str) -> None:
        index[v] = low[v] = len(index)
        stack.append(v)
        on_stack.add(v)
        for w in sorted(graph.get(v, ())):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            component = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                found.append(sorted(component))

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return found


def main() -> int:
    _, problems = analyze()
    for p in problems:
        print(p)
    print("Нарушений нет" if not problems else f"Нарушений: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
