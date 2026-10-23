"""Описание релиза для агента деплоя (release.json в ветке deploy): какой коммит main выкатывается."""
import json
import os
import sys
from datetime import datetime, timezone

sha = os.environ["SHA"]
release = {
    "commit": sha,
    "short": sha[:7],
    "subject": os.environ.get("SUBJECT", ""),
    "author": os.environ.get("AUTHOR", ""),
    "url": f'{os.environ["REPO_URL"]}/commit/{sha}',
    "run_url": os.environ.get("RUN_URL", ""),
    "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}
with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump(release, f, ensure_ascii=False, indent=2)
    f.write("\n")
