# Project Agent Rules

## Running Tests (Windows / Sandbox)

- Do **not** run `uv run pytest` inside the sandbox. `uv run` may attempt network checks, environment syncing, or external cache access that can stall in a restricted sandbox.
- Always invoke the virtual environment directly to run tests:
  - Single or targeted tests (preferred after focused edits):
    `.venv\Scripts\python.exe -m pytest -q tests/<test_file>.py`
  - Full test suite:
    `.venv\Scripts\python.exe -m pytest -q`
  - If `uv` is explicitly required, pass `--offline --no-sync`:
    `uv run --offline --no-sync pytest -q`
- Do **not** start long-running servers (such as `uvicorn` or `tests/browser_fixture.py`) inside a normal test command without terminating them in the same command; leftover child processes keep stdout/stderr pipes open and cause the agent to wait indefinitely.
- `pytest-timeout` is configured in `pyproject.toml` (`timeout = 60`). If a specific test legitimately needs more time, override it explicitly with `--timeout=<seconds>` rather than disabling timeouts globally.
- If a PowerShell test command finishes execution on Windows but appears to hang waiting for EOF, retry via `cmd /c .venv\Scripts\python.exe -m pytest -q ...`.

## Architecture Boundaries & Development Paradigms

All changes must preserve the 4-layer unidirectional architecture (enforced by `tests/test_architecture.py`):

- **L0 Infrastructure (`db`, `config`, `utils`)**: Generic connection/config/utility helpers only; no business domain or web framework imports.
- **L1 Core Domain (`airport_surface`, `flight`, `path_map`, `route_library`)**:
  - `airport_surface` and `path_map` are pure domain/algorithm packages and must never import `fastapi`, `duckdb`, or `airport_workbench`.
  - `flight` and `route_library` depend on `db` only (never import each other).
- **L2 Application / Workbench (`airport_workbench`)**:
  - Organize by flat domain modules (`routes_*.py` + focused service modules); keep `app.py` as thin wiring only.
  - Any backend API/DTO change must regenerate `frontend/workbench/openapi/*.json` and `frontend/workbench/src/api/generated/*.ts`.
- **L3 Frontend (`frontend/workbench/src/`)**:
  - Layering: `components/ui/` ← `domain/` (shared palettes/labels/geometry) ← `api/` (sole `fetch` & generated types) ← `features/<domain>/` ← `app/`.
  - Never call `fetch()` directly outside `src/api/client.ts`; never duplicate color palettes or status label maps across components.
  - Keep individual `.tsx` feature components focused (target ≤ 500 lines; split filter bars, popovers, editors, and tables into dedicated subcomponents).
- **Database DDL Single Source of Truth**:
  - All DuckDB `CREATE TABLE` / `CREATE INDEX` / schema migrations live exclusively in `sql/schema/` and `sql/migrations/`.
  - Python repositories and scripts perform CRUD/DML only (fail fast if a table is missing; tests apply `sql/schema/01_core_tables.sql` via `db.apply_core_schema()`).
  - Never access private `._database` attributes from outside repository classes.
