"""Architecture fitness tests enforcing package boundaries and coding paradigms."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
SCRIPTS_DIR = ROOT / "scripts"
FRONTEND_SRC = ROOT / "frontend" / "workbench" / "src"

ALLOWED_PACKAGE_DEPS: dict[str, set[str]] = {
    "utils": set(),
    "db": set(),
    "config": {"airport_surface", "path_map"},
    "airport_surface": {"utils"},
    "flight": {"db", "utils"},
    "path_map": {"airport_surface", "flight"},
    "route_library": {"airport_surface", "config", "db", "path_map"},
    "airport_workbench": {
        "airport_surface",
        "db",
        "flight",
        "path_map",
        "route_library",
        "utils",
    },
}

PURE_DOMAIN_PACKAGES = {"airport_surface", "path_map"}
FORBIDDEN_IN_PURE_DOMAIN = {"fastapi", "starlette", "uvicorn", "duckdb", "sqlalchemy"}


def _imported_top_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_python_package_dependencies_are_acyclic_and_layered():
    packages = {
        path.name
        for path in SRC_DIR.iterdir()
        if path.is_dir() and not path.name.startswith("_")
    }
    assert packages == set(ALLOWED_PACKAGE_DEPS), (
        f"Update ALLOWED_PACKAGE_DEPS for packages: {sorted(packages)}"
    )

    graph: dict[str, set[str]] = {pkg: set() for pkg in packages}
    violations: list[str] = []
    for py_file in SRC_DIR.rglob("*.py"):
        rel = py_file.relative_to(SRC_DIR)
        if len(rel.parts) < 2:
            continue
        owner = rel.parts[0]
        if owner not in packages:
            continue
        imported = _imported_top_modules(py_file)
        for target in imported & packages:
            if target == owner:
                continue
            graph[owner].add(target)
            if target not in ALLOWED_PACKAGE_DEPS[owner]:
                violations.append(f"{rel.as_posix()} imports forbidden package {target!r}")
        if owner in PURE_DOMAIN_PACKAGES:
            bad = imported & FORBIDDEN_IN_PURE_DOMAIN
            if bad:
                violations.append(f"{rel.as_posix()} imports web/db modules {sorted(bad)}")

    assert not violations, "Package boundary violations:\n" + "\n".join(violations)

    # Verify DAG (no cycles) via DFS
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, trail: list[str]) -> None:
        visiting.add(node)
        for nxt in sorted(graph[node]):
            if nxt in visiting:
                raise AssertionError(f"Circular package dependency: {' -> '.join([*trail, nxt])}")
            if nxt not in visited:
                dfs(nxt, [*trail, nxt])
        visiting.remove(node)
        visited.add(node)

    for pkg in sorted(packages):
        if pkg not in visited:
            dfs(pkg, [pkg])


def test_no_ddl_create_table_in_python_source():
    """Enforce Paradigm 1: all DuckDB table DDL lives in sql/schema/, Python only does CRUD."""
    pattern = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TABLE\b", re.IGNORECASE)
    offenders: list[str] = []
    for py_file in (*SRC_DIR.rglob("*.py"), *SCRIPTS_DIR.rglob("*.py")):
        if py_file.name == "export_workbench_openapi.py":
            continue
        text = py_file.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(py_file.relative_to(ROOT).as_posix())
    assert not offenders, (
        "DDL CREATE TABLE must live in sql/schema/ only, not Python:\n" + "\n".join(offenders)
    )


def test_no_private_database_attribute_penetration():
    """Callers outside src/flight/ and src/route_library/ must not reach into ._database."""
    offenders: list[str] = []
    for py_file in (*SRC_DIR.rglob("*.py"), *SCRIPTS_DIR.rglob("*.py")):
        rel = py_file.relative_to(ROOT).as_posix()
        if rel.startswith(("src/flight/", "src/route_library/")):
            continue
        if "._database" in py_file.read_text(encoding="utf-8"):
            offenders.append(rel)
    assert not offenders, "Private ._database access outside repositories:\n" + "\n".join(offenders)


def test_frontend_components_never_call_raw_fetch():
    """All frontend HTTP calls must go through src/api/client.ts."""
    offenders: list[str] = []
    fetch_call = re.compile(r"\bfetch\s*\(")
    for ts_file in FRONTEND_SRC.rglob("*.ts*"):
        rel = ts_file.relative_to(FRONTEND_SRC).as_posix()
        if rel == "api/client.ts" or rel.startswith("api/generated/"):
            continue
        if fetch_call.search(ts_file.read_text(encoding="utf-8")):
            offenders.append(rel)
    assert not offenders, "Direct fetch() outside src/api/client.ts:\n" + "\n".join(offenders)


def test_frontend_palettes_live_only_in_domain_palette():
    """Color palettes must have a single source of truth in src/domain/palette.ts."""
    offenders: list[str] = []
    for ts_file in FRONTEND_SRC.rglob("*.ts*"):
        rel = ts_file.relative_to(FRONTEND_SRC).as_posix()
        if rel == "domain/palette.ts" or rel.startswith("api/generated/"):
            continue
        text = ts_file.read_text(encoding="utf-8")
        if "#0072B2" in text or "#7C3AED" in text:
            offenders.append(rel)
    assert not offenders, (
        "Duplicated palette hex codes outside src/domain/palette.ts:\n" + "\n".join(offenders)
    )


RAW_BUTTON_ALLOWLIST = {
    "app/App.tsx",  # Draggable main-view tab buttons for split-screen DnD
    "features/layout/RailResizer.tsx",  # Specialized pointer-capture drag separator
}


def test_frontend_uses_shadcn_primitives_not_raw_html():
    """App and feature components must use src/components/ui/ primitives instead of raw HTML form/table controls."""
    forbidden_tags = ("table", "label", "input", "select", "textarea")
    tag_pattern = re.compile(r"<(" + "|".join(forbidden_tags) + r")\b")
    button_pattern = re.compile(r"<button\b")
    offenders: list[str] = []

    for tsx_file in FRONTEND_SRC.rglob("*.tsx"):
        rel = tsx_file.relative_to(FRONTEND_SRC).as_posix()
        if rel.startswith("components/ui/"):
            continue
        text = tsx_file.read_text(encoding="utf-8")
        bad_tags = sorted(set(tag_pattern.findall(text)))
        if bad_tags:
            offenders.append(f"{rel}: raw HTML tag(s) {bad_tags}")
        if rel not in RAW_BUTTON_ALLOWLIST and button_pattern.search(text):
            offenders.append(f"{rel}: raw <button> (use Button, Toggle, InlineEditTrigger, or IconActionButton)")

    assert not offenders, "Non-shadcn raw HTML controls found:\n" + "\n".join(offenders)


def test_frontend_respects_slate_tokens_and_typography():
    """Prevent off-theme gray/accent color classes and fragmented arbitrary font sizes from creeping back."""
    off_theme_colors = re.compile(r"\b(?:bg|text|border|ring)-(?:zinc|gray|neutral|stone|violet|purple)(?:-\d+)?(?:/\d+)?")
    bad_font_sizes = re.compile(r"\btext-\[(?:10|12|14)px\]")
    offenders: list[str] = []

    for tsx_file in FRONTEND_SRC.rglob("*.tsx"):
        rel = tsx_file.relative_to(FRONTEND_SRC).as_posix()
        text = tsx_file.read_text(encoding="utf-8")
        bad_colors = sorted(set(off_theme_colors.findall(text)))
        if bad_colors:
            offenders.append(f"{rel}: off-theme color classes {bad_colors}")
        if rel != "features/graph-editor/Inspector.tsx":
            bad_sizes = sorted(set(bad_font_sizes.findall(text)))
            if bad_sizes:
                offenders.append(f"{rel}: fragmented font sizes {bad_sizes}")

    assert not offenders, "Design token / typography drift detected:\n" + "\n".join(offenders)


def test_frontend_table_views_share_workbench_shell():
    """Every feature view rendering a data <Table> must use the shared workbench-shell layout primitives."""
    required_shell_parts = ("ViewHeader", "DataTableContainer", "PaginationFooter")
    offenders: list[str] = []

    for tsx_file in (FRONTEND_SRC / "features").rglob("*.tsx"):
        rel = tsx_file.relative_to(FRONTEND_SRC).as_posix()
        text = tsx_file.read_text(encoding="utf-8")
        if "<Table" not in text:
            continue
        missing = [part for part in required_shell_parts if part not in text]
        if missing:
            offenders.append(f"{rel}: missing workbench-shell primitive(s) {missing}")

    assert not offenders, "Table view shell inconsistency:\n" + "\n".join(offenders)
