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
