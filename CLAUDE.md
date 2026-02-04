# Repository Guidelines

## Project Structure & Module Organization
LifeOS splits backend logic inside `api/` (routes, services, schedulers), configuration and prompts in `config/`, launch helpers in `scripts/`, browser UIs in `web/`, and automated checks in `tests/`. Docs, PRDs, and architecture notes live in `docs/`. Persistent artifacts stay in `data/` (gitignored) while runtime logs go to `logs/`; keep contributions within these lanes to preserve discoverability.

## Build, Test, and Development Commands
- `./scripts/chromadb.sh start|stop`: control the external vector database that powers retrieval.
- `./scripts/server.sh start|restart|status`: ONLY supported way to run the API; restart after every Python change to avoid ghost uvicorn processes.
- `./scripts/test.sh [smoke|all]`: run pytest suites; `smoke` adds critical browser coverage, `all` runs full slow matrices.
- `./scripts/deploy.sh "message"`: runs tests, restarts services, and performs the commit/push sequence used in production.

## Coding Style & Naming Conventions
Backend code targets Python 3.11+, using 4-space indentation, type hints, and descriptive names (e.g., `ingest_weekly_digest`). Keep modules feature-scoped: routes live in `api/routes/`, business logic in `api/services/`, shared schemas/config live in `config/`. Prefer Pydantic models (`config/settings.py`) for new settings and follow the `LIFEOS_*` env alias pattern. Front-end files under `web/` are static HTML/JS; keep IDs/classes kebab-cased to match the existing markup.

## Testing Guidelines
Tests use pytest with asyncio support (`pytest-asyncio`) and the markers defined in `pyproject.toml` (`unit`, `slow`, `integration`, `browser`, etc.). Place new suites in `tests/` using `test_*.py` files and `test_*` functions for discovery. Favor deterministic unit coverage first, then gate heavier cases behind markers to keep `./scripts/test.sh` near its ~30s budget. Summarize any required manual verification in the PR when automation is infeasible.

## Commit & Pull Request Guidelines
Git history favors short, imperative summaries (`Add weekly digest endpoint`, `Fix chroma sync`). Use similar phrasing, keep subject lines under ~60 characters, and explain the “why” in the body when needed. Each PR should state motivation, list executed commands/tests, and link related issues. Include screenshots or log excerpts for UI/data changes, and avoid bundling unrelated work so deploys stay atomic.

## Security & Operations Tips
Configuration secrets live in `.env` and are read through `config/settings.py`; never commit real keys. Updating `config/people_dictionary.json` or other lookup tables requires a server restart to load the new entities. Always keep services bound to `0.0.0.0` via the provided scripts for parity between localhost and Tailscale clients, and tail `logs/` after restarts to catch sync or cron regressions early.
