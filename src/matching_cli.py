"""Select and run one of the two flight matching modes."""

from __future__ import annotations

import argparse
from typing import Sequence

from airport_surface import load_graph
from batch_matching import BatchMatchingRunner, DatabaseDataset
from config import ApplicationSettings, load_settings
from flight import MovementType
from flight.flight_catalogue_repository import BEIJING
from flight.flight_repository import FlightDatabase, open_flight_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ADS-B airport path matching")
    parser.add_argument("--workbench", action="store_true", help="start interactive matching")
    return parser


def run_batch(settings: ApplicationSettings, database: FlightDatabase) -> None:
    datasets = tuple(
        DatabaseDataset(movement.value, movement, database)
        for movement in (MovementType.ARRIVAL, MovementType.DEPARTURE)
    )
    BatchMatchingRunner(
        settings.graph_path,
        datasets,
        settings.batch.output_dir,
        match_config=settings.matching,
        limit=settings.batch.limit,
    ).run()


def run_workbench(settings: ApplicationSettings, database: FlightDatabase) -> None:
    from airport_workbench import open_workbench

    workbench = settings.workbench
    open_workbench(
        load_graph(settings.graph_path),
        save_path=settings.graph_path,
        host=workbench.host,
        port=workbench.port,
        open_browser=workbench.open_browser,
        match_config=settings.matching,
        input_time_semantics=BEIJING,
        display_timezone=workbench.display_timezone,
        flight_database=database,
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
        database = open_flight_database(settings.database, read_only=not args.workbench)
        run = run_workbench if args.workbench else run_batch
        try:
            run(settings, database)
        except database.database_error as error:
            parser.error(f"DuckDB: {error}")
    except (OSError, TypeError, ValueError) as error:
        parser.error(str(error))
