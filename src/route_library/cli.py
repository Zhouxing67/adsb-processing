"""CLI entry point for importing and inspecting the DuckDB route library."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from config import load_settings
from flight.flight_repository import open_flight_database

from .importer import import_batch_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the DuckDB airport route library")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import",
        help="Import deduplicated routes from a batch matching output directory",
    )
    import_parser.add_argument(
        "run_dir",
        type=Path,
        help=(
            "Path to a BatchMatchingRunner output directory "
            "(containing graph.json, paths.jsonl, matches.jsonl)"
        ),
    )
    import_parser.add_argument(
        "--append",
        action="store_true",
        help="Keep existing candidate routes for the same graph_id instead of replacing them",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        database = open_flight_database(settings.database, read_only=False)
        if args.command == "import":
            try:
                summary = import_batch_run(
                    args.run_dir,
                    database.routes,
                    replace_candidates=not args.append,
                )
            except database.database_error as error:
                parser.error(f"DuckDB: {error}")
            print(
                f"Imported route library for graph {summary.graph_id}: "
                f"rows={summary.total_match_rows} matched={summary.matched_rows} "
                f"skipped_missing_od={summary.skipped_missing_od} "
                f"unique={summary.unique_routes} deleted_candidates={summary.deleted_candidates} "
                f"inserted={summary.inserted_routes} existing={summary.existing_routes}"
            )
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
