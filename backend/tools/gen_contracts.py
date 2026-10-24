"""Публичный контракт API: contracts/openapi.json из схем FastAPI и Pydantic.

    cd backend && python tools/gen_contracts.py           # записать contracts/openapi.json
    cd backend && python tools/gen_contracts.py --check   # код выхода 1, если файл расходится со схемами (CI)

Типы интерфейса генерируются из этого файла: cd frontend && npm run gen:api.
Политика версий и каталог ошибок — docs/api-versioning.md.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPENAPI = ROOT / "contracts" / "openapi.json"


def render() -> str:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.main import app  # после sys.path: инструмент запускается из backend/ или из корня

    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="только сравнить с contracts/openapi.json")
    args = ap.parse_args()
    text = render()
    if args.check:
        if not OPENAPI.exists() or OPENAPI.read_text(encoding="utf-8") != text:
            print("contracts/openapi.json расходится со схемами: python tools/gen_contracts.py")
            return 1
        print("Контракт совпадает со схемами")
        return 0
    OPENAPI.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI.write_text(text, encoding="utf-8", newline="\n")
    print(f"Записан {OPENAPI.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
