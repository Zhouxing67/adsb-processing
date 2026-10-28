"""Application runner for ZBAA ADS-B map-matching experiments."""

from __future__ import annotations

import csv
import json
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from traffic.core import Flight, Traffic

from airport_surface import load_graph
from airport_workbench import open_workbench
from path_map import MapMatchingError, MatchConfig, Matcher, MovementType
from path_map.path import Path as MatchedPath

MATCH_COLUMNS = [
    "batch",
    "flight_id",
    "movement_type",
    "observation_count",
    "edge_count",
    "path_length_m",
    "elapsed_seconds",
]
EDGE_COLUMNS = ["batch", "flight_id", "sequence", "from_node", "to_node", "key"]
FAILURE_COLUMNS = [
    "batch",
    "flight_id",
    "observation_count",
    "failure_type",
    "reason",
    "elapsed_seconds",
]


@dataclass(frozen=True, slots=True)
class BatchSpec:
    name: str
    input_path: Path
    movement_type: MovementType


class Runner:
    """Load data, reuse one matcher, write reports, and optionally visualize samples."""

    def __init__(
        self,
        graph_path: Path,
        arrival_path: Path,
        departure_path: Path,
        output_dir: Path,
        *,
        match_config: MatchConfig | None = None,
        limit: int | None = None,
        visualize: bool = False,
        success_samples: int = 3,
        failure_samples: int = 3,
    ) -> None:
        self.graph_path = graph_path
        self.output_dir = output_dir
        self.match_config = match_config or MatchConfig()
        self.limit = limit
        self.visualize = visualize
        self.success_samples = success_samples
        self.failure_samples = failure_samples
        self.batches = (
            BatchSpec("arrival", arrival_path, MovementType.ARRIVAL),
            BatchSpec("departure", departure_path, MovementType.DEPARTURE),
        )

    @staticmethod
    def _flight_id(flight: Flight) -> str:
        value = flight.flight_id
        return str(value) if value is not None else "unknown"

    @staticmethod
    def _failure_type(reason: str) -> str:
        if "At least two valid observations" in reason:
            return "insufficient_observations"
        if "time gap" in reason:
            return "time_gap"
        if "No edge candidates" in reason:
            return "no_candidates"
        if "No connected network path" in reason:
            return "disconnected"
        return "matching_error"

    def _iter_flights(self, path: Path) -> Iterator[Flight]:
        """Load a CSV as Traffic and yield flights in timestamp order."""
        if not path.exists():
            raise FileNotFoundError(f"ADS-B input does not exist: {path}")

        traffic = Traffic.from_file(path, parse_dates=["timestamp"])
        if "flight_id" not in traffic.data.columns:
            raise ValueError(f"ADS-B input has no flight_id column: {path}")
        if traffic.data["flight_id"].isna().any():
            raise ValueError(f"ADS-B input contains an empty flight_id: {path}")

        for flight in traffic.iterate(nb_flights=self.limit):
            ordered = flight.data.sort_values("timestamp").reset_index(drop=True)
            yield Flight(ordered)

    def _run_batch(
        self,
        spec: BatchSpec,
        matcher: Matcher,
    ) -> tuple[dict[str, Any], list[Flight], list[MatchedPath]]:
        successful_sample_flights: list[Flight] = []
        failed_sample_flights: list[Flight] = []
        sample_paths: list[MatchedPath] = []
        started = time.perf_counter()
        batch_dir = self.output_dir / spec.name
        batch_dir.mkdir(parents=True, exist_ok=True)
        matched_count = 0
        failed_count = 0
        failure_counts: Counter[str] = Counter()

        def build_summary(status: str) -> dict[str, Any]:
            elapsed = time.perf_counter() - started
            total = matched_count + failed_count
            return {
                "status": status,
                "batch": spec.name,
                "input": str(spec.input_path),
                "total_flights": total,
                "matched_flights": matched_count,
                "failed_flights": failed_count,
                "success_rate": matched_count / total if total else None,
                "elapsed_seconds": elapsed,
                "average_seconds_per_flight": elapsed / total if total else None,
                "failure_counts": dict(failure_counts),
            }

        def save_summary(status: str) -> dict[str, Any]:
            summary = build_summary(status)
            (batch_dir / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return summary

        with (
            (batch_dir / "matches.csv").open("w", newline="", encoding="utf-8-sig") as match_file,
            (batch_dir / "matched_edges.csv").open(
                "w", newline="", encoding="utf-8-sig"
            ) as edge_file,
            (batch_dir / "failures.csv").open(
                "w", newline="", encoding="utf-8-sig"
            ) as failure_file,
        ):
            match_writer = csv.DictWriter(match_file, fieldnames=MATCH_COLUMNS)
            edge_writer = csv.DictWriter(edge_file, fieldnames=EDGE_COLUMNS)
            failure_writer = csv.DictWriter(failure_file, fieldnames=FAILURE_COLUMNS)
            match_writer.writeheader()
            edge_writer.writeheader()
            failure_writer.writeheader()
            save_summary("running")

            try:
                for number, flight in enumerate(self._iter_flights(spec.input_path), start=1):
                    flight_id = self._flight_id(flight)
                    flight_started = time.perf_counter()
                    try:
                        path = matcher.map_flight(flight, movement_type=spec.movement_type)
                    except MapMatchingError as error:
                        reason = str(error)
                        failure_type = self._failure_type(reason)
                        failure_writer.writerow(
                            {
                                "batch": spec.name,
                                "flight_id": flight_id,
                                "observation_count": len(flight.data),
                                "failure_type": failure_type,
                                "reason": reason,
                                "elapsed_seconds": time.perf_counter() - flight_started,
                            }
                        )
                        failed_count += 1
                        failure_counts[failure_type] += 1
                        if len(failed_sample_flights) < self.failure_samples:
                            failed_sample_flights.append(flight)
                    else:
                        match_writer.writerow(
                            {
                                "batch": spec.name,
                                "flight_id": flight_id,
                                "movement_type": spec.movement_type.value,
                                "observation_count": len(flight.data),
                                "edge_count": len(path),
                                "path_length_m": path.total_length,
                                "elapsed_seconds": time.perf_counter() - flight_started,
                            }
                        )
                        matched_count += 1
                        for sequence, edge in enumerate(path.edges):
                            edge_writer.writerow(
                                {
                                    "batch": spec.name,
                                    "flight_id": flight_id,
                                    "sequence": sequence,
                                    "from_node": repr(edge.from_),
                                    "to_node": repr(edge.to_),
                                    "key": repr(edge.key_),
                                }
                            )
                        if len(sample_paths) < self.success_samples:
                            successful_sample_flights.append(flight)
                            sample_paths.append(path)

                    if number % 100 == 0:
                        match_file.flush()
                        edge_file.flush()
                        failure_file.flush()
                        save_summary("running")
                        print(
                            f"[{spec.name}] processed={number} "
                            f"matched={matched_count} failed={failed_count}"
                        )
            except BaseException:
                save_summary("interrupted")
                raise

        summary = save_summary("completed")
        elapsed = summary["elapsed_seconds"]
        print(
            f"[{spec.name}] total={matched_count + failed_count} matched={matched_count} "
            f"failed={failed_count} elapsed={elapsed:.2f}s"
        )
        return summary, successful_sample_flights + failed_sample_flights, sample_paths

    def run(self) -> dict[str, Any]:
        if not self.graph_path.exists():
            raise FileNotFoundError(f"Airport graph does not exist: {self.graph_path}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        airport_graph = load_graph(self.graph_path)
        matcher = Matcher(airport_graph, self.match_config)

        summaries: list[dict[str, Any]] = []
        sample_flights: list[Flight] = []
        sample_paths: list[MatchedPath] = []
        started = time.perf_counter()
        for spec in self.batches:
            summary, flights, paths = self._run_batch(spec, matcher)
            summaries.append(summary)
            sample_flights.extend(flights)
            sample_paths.extend(paths)

        total = sum(item["total_flights"] for item in summaries)
        matched = sum(item["matched_flights"] for item in summaries)
        failed = sum(item["failed_flights"] for item in summaries)
        report = {
            "graph": str(self.graph_path),
            "total_flights": total,
            "matched_flights": matched,
            "failed_flights": failed,
            "success_rate": matched / total if total else None,
            "elapsed_seconds": time.perf_counter() - started,
            "batches": summaries,
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if self.visualize and sample_flights:
            open_workbench(
                airport_graph,
                flights=sample_flights,
                paths=sample_paths,
                save_path=self.graph_path,
            )
        return report
