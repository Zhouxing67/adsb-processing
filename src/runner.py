"""Application runner for ZBAA ADS-B map-matching experiments."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

from adsb import Flight
from airport_surface import graph_id, load_graph, save_graph
from matching_inputs import LoadedDataset
from path_map import (
    MapMatchingError,
    MatchConfig,
    Matcher,
    PathRecord,
)

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class Runner:
    """Match prepared datasets and persist the existing batch result format."""

    def __init__(
        self,
        graph_path: Path,
        datasets: tuple[LoadedDataset, ...],
        output_dir: Path,
        *,
        match_config: MatchConfig | None = None,
        limit: int | None = None,
    ) -> None:
        self.graph_path = graph_path
        self.output_dir = output_dir
        self.match_config = match_config or MatchConfig()
        self.limit = limit
        self.datasets = datasets

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

    def _run_batch(
        self,
        dataset: LoadedDataset,
        matcher: Matcher,
        graph_identity: str,
        path_file: TextIO,
        match_file: TextIO,
        path_ids: dict[tuple[tuple[Any, Any, Any], ...], int],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        matched_count = 0
        failed_count = 0
        failure_counts: Counter[str] = Counter()

        for number, flight in enumerate(dataset.iterate(limit=self.limit), start=1):
            flight_id = self._flight_id(flight)
            flight_started = time.perf_counter()
            result: dict[str, Any] = {
                "flight_id": flight_id,
                "movement_type": dataset.movement_type.value,
                "observation_count": len(flight.data),
            }
            try:
                path = matcher.map_flight(flight)
            except MapMatchingError as error:
                reason = str(error)
                failure_type = self._failure_type(reason)
                result.update(path_id=None, failure_type=failure_type, reason=reason)
                failed_count += 1
                failure_counts[failure_type] += 1
            else:
                path_key = path.edge_ids
                path_id = path_ids.get(path_key)
                if path_id is None:
                    path_id = len(path_ids) + 1
                    path_ids[path_key] = path_id
                    path_file.write(
                        json.dumps(
                            {
                                "path_id": path_id,
                                "path": PathRecord(graph_identity, path.edges).to_dict(),
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                result["path_id"] = path_id
                matched_count += 1

            result["elapsed_seconds"] = time.perf_counter() - flight_started
            match_file.write(
                json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            if number % 100 == 0:
                match_file.flush()
                path_file.flush()
                print(
                    f"[{dataset.name}] processed={number} "
                    f"matched={matched_count} failed={failed_count}"
                )

        elapsed = time.perf_counter() - started
        total = matched_count + failed_count
        summary = {
            "batch": dataset.name,
            "input": str(dataset.path),
            "total_flights": total,
            "matched_flights": matched_count,
            "failed_flights": failed_count,
            "success_rate": matched_count / total if total else None,
            "elapsed_seconds": elapsed,
            "average_seconds_per_flight": elapsed / total if total else None,
            "failure_counts": dict(failure_counts),
        }
        elapsed = summary["elapsed_seconds"]
        print(
            f"[{dataset.name}] total={matched_count + failed_count} matched={matched_count} "
            f"failed={failed_count} elapsed={elapsed:.2f}s"
        )
        return summary

    def run(self) -> dict[str, Any]:
        if not self.graph_path.exists():
            raise FileNotFoundError(f"Airport graph does not exist: {self.graph_path}")
        airport_graph = load_graph(self.graph_path)
        matcher = Matcher(airport_graph, self.match_config)
        run_started_at = datetime.now(LOCAL_TIMEZONE)
        run_dir = self.output_dir / run_started_at.strftime("%Y%m%d_%H%M%S")
        run_dir.mkdir(parents=True, exist_ok=False)
        graph_snapshot = run_dir / "graph.json"
        save_graph(airport_graph, graph_snapshot)
        graph_identity = graph_id(airport_graph)

        summaries: list[dict[str, Any]] = []
        path_ids: dict[tuple[tuple[Any, Any, Any], ...], int] = {}
        started = time.perf_counter()
        with (
            (run_dir / "paths.jsonl").open("w", encoding="utf-8") as path_file,
            (run_dir / "matches.jsonl").open("w", encoding="utf-8") as match_file,
        ):
            for dataset in self.datasets:
                summary = self._run_batch(
                    dataset,
                    matcher,
                    graph_identity,
                    path_file,
                    match_file,
                    path_ids,
                )
                summaries.append(summary)

        total = sum(item["total_flights"] for item in summaries)
        matched = sum(item["matched_flights"] for item in summaries)
        failed = sum(item["failed_flights"] for item in summaries)
        report = {
            "started_at": run_started_at.isoformat(),
            "completed_at": datetime.now(LOCAL_TIMEZONE).isoformat(),
            "graph_id": graph_identity,
            "total_flights": total,
            "matched_flights": matched,
            "failed_flights": failed,
            "unique_paths": len(path_ids),
            "success_rate": matched / total if total else None,
            "elapsed_seconds": time.perf_counter() - started,
            "batches": summaries,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return report
