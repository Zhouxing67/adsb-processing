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
  - `airport_surface` and `path_map` are pure domain/algorithm packages and must never import `fastapi`, `psycopg`, `duckdb`, or `airport_workbench`.
  - `flight` and `route_library` depend on `db` only (never import each other).
- **L2 Application / Workbench (`airport_workbench`)**:
  - Organize by flat domain modules (`routes_*.py` + focused service modules); keep `app.py` as thin wiring only.
  - Any backend API/DTO change must regenerate `frontend/workbench/openapi/*.json` and `frontend/workbench/src/api/generated/*.ts`.
- **L3 Frontend (`frontend/workbench/src/`)**:
  - Layering: `components/ui/` ← `domain/` (shared palettes/labels/geometry) ← `api/` (sole `fetch` & generated types) ← `features/<domain>/` ← `app/`.
  - Never call `fetch()` directly outside `src/api/client.ts`; never duplicate color palettes or status label maps across components.
  - **Shadcn & Design-System Discipline** (enforced by `tests/test_architecture.py`):
    - Always compose UI from `src/components/ui/` primitives (`Button`, `Table`, `Card`, `Label`, `Alert`, `Toggle`, `Empty`, `Spinner`, etc.) and `workbench-shell.tsx` (`ViewHeader`, `FilterBar`, `DataTableContainer`, `PaginationFooter`, `PopoverFooter`, `InlineEditTrigger`, `IconActionButton`); never hand-roll raw `<table>`, `<label>`, `<input>`, `<select>`, `<textarea>`, or `<button>` in `app/` or `features/`.
    - Every data-table view must use `ViewHeader`, `DataTableContainer`, and `PaginationFooter` (never wrap `<Table>` in Radix `ScrollArea`).
    - Use semantic CSS tokens (`bg-primary`, `bg-muted`, `bg-accent`, `text-accent-amber`, `text-accent-teal`, `text-foreground`, `border-border`) from `src/styles/index.css` (Slate + 3-color semantic accents: cobalt `#1d5fa7`, amber `#c86428`, teal `#147a6e`); never introduce off-theme `zinc-*`/`gray-*`/`violet-*` classes or fragmented arbitrary font sizes (`text-[10px]`/`text-[12px]`/`text-[14px]`).
    - Use `InlineEditTrigger` for inline-editable table cells and `IconActionButton` for icon-only actions (enforcing `aria-label` + shadcn `Tooltip`).
  - Keep individual `.tsx` feature components focused (target ≤ 500 lines; split filter bars, popovers, editors, and tables into dedicated subcomponents).
- **Database DDL Single Source of Truth**:
  - All PostgreSQL `CREATE TABLE` / `CREATE INDEX` / schema DDL lives exclusively in `sql/schema/`.
  - Python repositories and scripts perform CRUD/DML only (fail fast if a table is missing; tests apply `sql/schema/01_core_tables.sql` via `db.apply_core_schema()`).
  - Never access private `._database` attributes from outside repository classes.

## Python Type Annotation Conventions

- **Zero-error baseline**: Keep `ty check src` (configured via `[tool.ty.src]` in `pyproject.toml`) and `ruff check` clean on touched Python modules.
- **Name instead of nest**: When a type grows beyond two levels of nesting, extract a Python 3.12+ `type Alias = ...`, `dataclass`, or `TypedDict` instead of writing deeply nested generic types.
- **Avoid type gymnastics**: Do not write convoluted type-level metaprogramming just to satisfy the checker; at dynamic boundaries (e.g. `pandas`, `networkx`, or untyped third-party stubs), isolate with an explicit local annotation, `cast`, or small `Protocol` rather than disabling checks globally.
- **Transparent signatures**: Do not use decorators that implicitly add or mutate public function parameters; declare parameters explicitly and share lock/validation boilerplate via context managers so IDE completion and static analysis stay aligned.
- **Narrow before ignoring**: For `T | None` or union types, prefer explicit narrowing (`if x is None`, `isinstance(...)`, or `assert` for proven invariants) over `# type: ignore`.
