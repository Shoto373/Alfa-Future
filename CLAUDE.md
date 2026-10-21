# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Alfa Pulse (Альфа.Пульс) — hackathon prototype (Alfa-Bank case, deadline 2026-10-26): a Next.js "Alfa-Business" UI plus one FastAPI backend. The backend turns news and Alfa-Bank research into personalized insights for large companies. UI text, docs and commit bodies are in Russian. The full case and data live in the gitignored `контекст/` folder (task PDF, bank research PDFs, client CSVs). Never commit anything from it.

## Commands

Backend (run from `backend/`; Python 3.11 in Docker, pinned `requirements.txt`):
```bash
python -m pytest -q                                  # all tests (use synthetic data via conftest)
python -m pytest tests/test_agent.py::test_questions -q
python -m uvicorn app.main:app --port 8000
python -m app.companies.etl --data-dir ../data/synthetic --out /tmp/companies.json
python scripts/gen_contracts.py                      # regenerate contracts/ after changing schemas.py or routes
python scripts/make_synthetic_data.py --out ../data/synthetic
```
CI runs `python -m pytest backend/tests -v` from the repo root; that must keep working too.

Frontend (`frontend/`, Next 16 — see `frontend/AGENTS.md`: check `node_modules/next/dist/docs` before using Next APIs):
```bash
npm ci && npm run build && npm run typecheck   # typecheck needs .next types, so build first after route changes
npm run dev
```

Stack and end-to-end:
```bash
docker compose -f compose.yaml up --build -d   # always pass -f: root docker-compose.yml is production (nginx)
CASE_DATA_DIR=./контекст/data BANK_PDF_HOST_DIR=./контекст/drive-download-20261021T181704Z-1-001 docker compose -f compose.yaml up --build -d
python tests/e2e/smoke.py --base-url http://localhost:8000
python tests/e2e/ui_check.py --front http://localhost:3000   # needs playwright + chromium
```

## Architecture

**Data flow.**
- `companies/etl.py` (stdlib only) turns the case CSVs from `DATA_DIR` into large-business profiles. It caches them in `RUNTIME_DIR/companies.json` and rebuilds when the CSV size or mtime signature changes. If `DATA_DIR` has no CSVs, it falls back to `data/synthetic`.
- `profiles.exposures()` derives explainable `{topic, sign, weight, feature, why, origin}` rows from three sources: the sector sensitivity table (`sectors.SECTOR_SENSITIVITY`), product flags, and the counterparty sectors in the payment data.
- Exposures drive `ranking.score()`, the agent composer and the UI. A new sector or topic therefore usually needs entries in `sectors.py`, `news/taxonomy.py` and `agent/composer.py` (`DIRECTION_VALUE`, `TOPIC_EFFECT`, `ACTIONS`).

**Direction semantics.**
- The classifier gives a per-topic direction (`topic_directions`); credit tightening means `down`.
- Composer effect = `exposure.sign × DIRECTION_VALUE[topic][direction]`, where `up` is the topic's "more of it" direction (weaker ruble for `fx`, rate up for `key_rate`).
- Keep the signs in `SECTOR_SENSITIVITY` and `profiles.exposures` consistent with that convention. Mixing conventions silently flips risks and opportunities.

**Agent** (`agent/orchestrator.run`): plan (LLM or rules) → `ToolRunner` calls (read-only registry, typed args, call budget, `audit.jsonl`) → `ctx` → draft (LLM JSON merged over the rules draft, or rules only) → `validators.check` → `apply_fix` / broaden search (at most 2 rounds) → `Insight` with trace.
- Every claim has an `origin` (`fact|client_data|bank|ai`) and `source_ids` that must exist in `sources`.
- `bank` claims may cite only `bank:*` ids.
- Numbers in `ai` and fact claims must appear in the grounding text (`_grounding_text`). If you add templated numbers to composer actions, add them to the grounding text too, or the validator will drop the claim.

**LLM** (`agent/llm.py`): OpenAI-compatible, enabled only when `LLM_BASE_URL` and `LLM_API_KEY` are set. Model names must match `config.ALLOWED_MODELS` (the case allowlist). Any `LLMError` falls back to rules and is logged in the trace. Tests mock `llm.httpx.post`.

**Knowledge base:** `knowledge/bank_analytics.json` holds hand-extracted theses (the PDFs are scanned images) with doc, page and stance. Search is BM25 over 5-char stems plus topic and sector boosts plus recency. Stale docs (the 2021 steel report) are excluded unless `include_stale`.

**API:** errors via `ApiError(code)` → `{"error": {...}}`; 422 is remapped to 400 and also stripped from OpenAPI. `RequestContextMiddleware` sets `request.state.request_id` and the 64 KiB body limit. CORS is the outermost middleware. Insights are cached per (company, role, news) in `storage.py`.

**Frontend:**
- The `app/(bank)` route group is wrapped in `Shell` (sidebar, company switcher, role select), and the session lives in localStorage (`lib/session.tsx`).
- `lib/hooks.useLoad` aborts on dependency change; the insight page guards against stale responses with a sequence ref.
- `NEXT_PUBLIC_API_BASE_URL` is baked in at build time.

## Rules

- File ownership and process rules are in `AGENTS.md`.
- Legacy files `app/`, the root `Dockerfile` and root `requirements.txt` are unused; don't delete them without agreement.
- CD (`deploy.yml`) runs on every PR to `main`, not only on merge, and deploys to the production server.
- Don't merge into `main` or force-push without being asked. Never commit `.env`, `контекст/`, real CSV/PDF or `phone1.conf`.
