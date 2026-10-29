"""Argument parsing and mode dispatch for the unified matching entry point."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from airport_surface import load_graph
from matching_inputs import LoadedDataset, load_datasets, select_input_files
from path_map import MatchConfig
from runner import Runner

DEFAULT_GRAPH = Path("data/graphs/zbaa_final.json")
DEFAULT_OUTPUT = Path("outputs/path_map")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ADS-B airport path matching")
    parser.add_argument("--workbench", action="store_true", help="start interactive matching")
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--arrivals", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--departures", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--input-timezone", default="UTC")
    parser.add_argument("--search-radius", type=float, default=40.0)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--gps-sigma", type=float, default=10.0)
    parser.add_argument("--transition-beta", type=float, default=20.0)
    parser.add_argument("--output", type=Path, default=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--host", default=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--display-timezone", default=argparse.SUPPRESS)
    return parser


def _validate_mode_options(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> None:
    if args.workbench:
        forbidden = [name for name in ("output", "limit") if hasattr(args, name)]
        if forbidden:
            parser.error(
                "Workbench mode does not accept "
                + ", ".join(f"--{name.replace('_', '-')}" for name in forbidden)
            )
    else:
        forbidden = [
            name
            for name in ("host", "port", "no_browser", "display_timezone")
            if hasattr(args, name)
        ]
        if forbidden:
            parser.error(
                "Batch mode does not accept "
                + ", ".join(f"--{name.replace('_', '-')}" for name in forbidden)
            )
    if hasattr(args, "limit") and args.limit < 0:
        parser.error("--limit must be a non-negative integer")
    if hasattr(args, "port") and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")


def _validate_timezone(value: str, option: str) -> None:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown {option} timezone: {value}") from error


def _match_config(args: argparse.Namespace) -> MatchConfig:
    return MatchConfig(
        search_radius=args.search_radius,
        max_candidates=args.max_candidates,
        gps_sigma=args.gps_sigma,
        transition_beta=args.transition_beta,
    )


def _load_selected_datasets(args: argparse.Namespace) -> tuple[LoadedDataset, ...]:
    arrivals_provided = hasattr(args, "arrivals")
    departures_provided = hasattr(args, "departures")
    inputs = select_input_files(
        getattr(args, "arrivals", None),
        getattr(args, "departures", None),
        arrivals_provided=arrivals_provided,
        departures_provided=departures_provided,
    )
    return load_datasets(inputs, args.input_timezone)


def run_batch(
    args: argparse.Namespace,
    datasets: tuple[LoadedDataset, ...],
    config: MatchConfig,
) -> None:
    Runner(
        args.graph,
        datasets,
        getattr(args, "output", DEFAULT_OUTPUT),
        match_config=config,
        limit=getattr(args, "limit", None),
    ).run()


def run_workbench(
    args: argparse.Namespace,
    datasets: tuple[LoadedDataset, ...],
    config: MatchConfig,
) -> None:
    from airport_workbench import open_workbench

    graph = load_graph(args.graph)
    flights = []
    sources = []
    movement_types = []
    for dataset in datasets:
        loaded = list(dataset.iterate())
        flights.extend(loaded)
        sources.extend([str(dataset.path)] * len(loaded))
        movement_types.extend([dataset.movement_type.value] * len(loaded))
    if not flights:
        raise ValueError("Selected ADS-B inputs contain no flights")
    open_workbench(
        graph,
        flights=flights,
        save_path=args.graph,
        host=getattr(args, "host", "127.0.0.1"),
        port=getattr(args, "port", 8765),
        open_browser=not getattr(args, "no_browser", False),
        match_config=config,
        flight_sources=sources,
        movement_types=movement_types,
        input_time_semantics=args.input_timezone,
        display_timezone=getattr(args, "display_timezone", "UTC"),
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_mode_options(parser, args)
    try:
        _validate_timezone(args.input_timezone, "input")
        if args.workbench:
            _validate_timezone(getattr(args, "display_timezone", "UTC"), "display")
        config = _match_config(args)
        datasets = _load_selected_datasets(args)
        if args.workbench:
            run_workbench(args, datasets, config)
        else:
            run_batch(args, datasets, config)
    except (FileNotFoundError, OSError, TypeError, ValueError) as error:
        parser.error(str(error))
