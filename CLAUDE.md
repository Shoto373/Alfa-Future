# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Alfa Pulse (Альфа.Пульс) — hackathon project (deadline 2026-10-26). Sprint 1 is a technical skeleton: Next.js frontend → one Python/FastAPI backend that calls an in-process analysis function. Synthetic fixtures only; no DB, no LLM, no auth. Project docs, user-facing text and commit bodies are in Russian.

## Commands

Backend (run from `backend/`; Python 3.11 in Docker, pinned deps in `backend/requirements.txt`):
```bash
python -m pip install -r requirements.txt
python -m pytest -q                                   # all backend tests
python -m pytest tests/test_api.py -q                 # one file
python -m pytest tests/test_api.py::test_list_companies -q   # one test
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
CI runs `python -m pytest backend/tests -v` from the repo root; that must keep working too.

Frontend (run from `frontend/`; Node ≥ 20.9, exact versions + `package-lock.json`):
```bash
npm ci
npm run typecheck     # tsc --noEmit
npm run build
npm run dev           # 0.0.0.0:3000
NEXT_PUBLIC_API_MOCK=empty npm run dev   # local test double: ok | empty | error | slow
```

Full stack and end-to-end:
```bash
docker compose -f compose.yaml up --build -d     # exactly two services: backend :8000, frontend :3000 (127.0.0.1 only)
python tests/e2e/smoke.py --base-url http://localhost:8000   # stdlib only, non-zero exit on failure
```
The root also has `docker-compose.yml` (production: legacy `app/` + nginx/HTTPS). Docker picks `compose.yaml` with a warning, so pass `-f compose.yaml` explicitly.

## Architecture

**The contract is the source of truth.** `backend/app/schemas.py` (Pydantic, all fields required, `extra="forbid"`) ↔ `contracts/schemas/common.json` ↔ `contracts/openapi.yaml` ↔ `contracts/examples/*.json` ↔ `frontend/lib/types.ts`. `backend/tests/test_contracts.py` regenerates JSON Schema from the models via `pydantic.json_schema.models_json_schema` and fails when `common.json` drifts. It also checks that the routes in `openapi.yaml` match the real `app.openapi()`. If you change a model, regenerate the schema and examples (see `contracts/README.md`) and update the TS types.

**Request flow for `POST /api/v1/insights`** (`backend/app/api/router.py`):
1. `RequestContextMiddleware` (`api/setup.py`) assigns `request.state.request_id`, enforces the 64 KiB body limit (by Content-Length and by streamed bytes), and logs only metadata.
2. The fixtures repository (`app/companies/repository.py`) reads `FIXTURES_DIR` (default `contracts/examples`) on every call. Corrupt fixtures raise `FixturesError` → 500. They are never replaced by an empty list.
3. `analysis_service.generate_insight(company, role, event, request_id)` is wrapped in `asyncio.wait_for(ANALYSIS_TIMEOUT_SECONDS)`. It is called through the module attribute (`app.analysis.service`), so tests can `monkeypatch.setattr(analysis_service, "generate_insight", ...)`. Keep it that way.
4. The result is re-validated as `Insight`, and `request_id/company_id/event_id/role` must match the request. Otherwise → 500 `INVALID_ANALYSIS_RESULT`.

**Errors.** Every error uses `{"error":{code,message,request_id,retryable}}` from `app/api/errors.py`. Raise `ApiError("CODE")`. FastAPI's 422 is remapped to 400 `INVALID_REQUEST`. `retryable` is true only for 503/504. The analysis module signals failure with `AnalysisUnavailable` / `InvalidAnalysisResult` from `app/errors.py`. There is intentionally no runtime flag or endpoint for simulating failure: failures are tested by substituting the function.

**Middleware order matters.** `CORSMiddleware` is added last (outermost), so 413 responses from the context middleware still get CORS headers. Only `FRONTEND_ORIGIN` is allowed.

**Analysis module** (`app/analysis/service.py`) is deterministic and pure. It must not look up companies, read files or open HTTP. Card content depends on `has_credit` / `has_deposit`; `null` means "unknown" (goes to `uncertainty`), not false. The role changes the emphasis: CFO → checking contract terms, CEO → financing plans. The output always has `is_mock=true` and `bank_position=null`, and `model_conclusion` states that no LLM was called.

**Frontend** (`frontend/components/NewsAnalytics.tsx`) calls FastAPI directly from the browser via `NEXT_PUBLIC_API_BASE_URL`. It is baked in at build time and passed as a Docker build arg. There are no Next.js API routes. Stale responses are dropped with a sequence ref plus `AbortController`. Changing the company or role clears the card. `lib/api.ts` applies a 10 s browser timeout and maps network failures to a retryable `NETWORK_ERROR`, because a stopped backend produces no HTTP 503. `next-env.d.ts` is gitignored; `global.d.ts` provides the Next types so `typecheck` works before the first build.

## Ownership and rules (from AGENTS.md)

- Each sprint task owns specific paths (see the table in `AGENTS.md`). Skeleton files — `main.py`, `schemas.py`, `errors.py`, `requirements.txt`, `.python-version`, `contracts/` — change only through their owner/integrator. API wiring goes through `configure_api(app)` in `api/setup.py`, not by editing `main.py` ad hoc.
- Legacy production files (`app/`, root `Dockerfile`, root `requirements.txt`, `docker-compose.yml`, `nginx/`, `deploy/`, `.github/`) are not deleted without agreement. Note that `.github/workflows/deploy.yml` deploys the legacy root `Dockerfile` and runs on every PR to `main`, not only on merges.
- Don't merge into `main`, force-push, `reset --hard` or `git clean`; work on `task/spr1-*` branches. Never commit `.env`, real CSV/PDF data or `phone1.conf` (a VPN config). The sprint spec `.docx`/`TZ_*.md` files are intentionally gitignored.
