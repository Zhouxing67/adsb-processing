"""CLI entry point for importing and inspecting the PostgreSQL route library."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from config import load_settings
from db import PostgresConnection

from .importer import import_batch_run
from .repository import RouteLibraryRepository


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the PostgreSQL airport route library")
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
        connection = PostgresConnection(settings.database.dsn, read_only=False)
        try:
            repository = RouteLibraryRepository(connection)
            if args.command == "import":
                try:
                    summary = import_batch_run(
                        args.run_dir,
                        repository,
                        replace_candidates=not args.append,
                    )
                except connection.database_error as error:
                    parser.error(f"PostgreSQL: {error}")
                print(
                    f"Imported route library for graph {summary.graph_id}: "
                    f"rows={summary.total_match_rows} matched={summary.matched_rows} "
                    f"skipped_missing_od={summary.skipped_missing_od} "
                    f"unique={summary.unique_routes} "
                    f"deleted_candidates={summary.deleted_candidates} "
                    f"inserted={summary.inserted_routes} existing={summary.existing_routes}"
                )
        finally:
            connection.close()
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
