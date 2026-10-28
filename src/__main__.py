"""Command-line entry point for the ADS-B path-matching experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from path_map import MatchConfig
from runner import Runner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ZBAA HMM map matching")
    parser.add_argument("--graph", type=Path, default=Path("data/graphs/zbaa_final.json"))
    parser.add_argument(
        "--arrivals",
        type=Path,
        default=Path("data/ADS-B/more_15_arr.csv"),
    )
    parser.add_argument(
        "--departures",
        type=Path,
        default=Path("data/ADS-B/more_15_dep.csv"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/path_map"))
    parser.add_argument("--limit", type=int, help="Maximum flights per batch")
    parser.add_argument("--visualize", action="store_true")
    parser.add_argument("--success-samples", type=int, default=3)
    parser.add_argument("--failure-samples", type=int, default=3)
    parser.add_argument("--search-radius", type=float, default=40.0)
    parser.add_argument("--max-candidates", type=int, default=6)
    parser.add_argument("--gps-sigma", type=float, default=10.0)
    parser.add_argument("--transition-beta", type=float, default=20.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = MatchConfig(
        search_radius=args.search_radius,
        max_candidates=args.max_candidates,
        gps_sigma=args.gps_sigma,
        transition_beta=args.transition_beta,
    )
    runner = Runner(
        args.graph,
        args.arrivals,
        args.departures,
        args.output,
        match_config=config,
        limit=args.limit,
        visualize=args.visualize,
        success_samples=args.success_samples,
        failure_samples=args.failure_samples,
    )
    runner.run()


if __name__ == "__main__":
    main()
