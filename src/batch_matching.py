"""Application runner for ZBAA ADS-B map-matching experiments."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, TextIO
from zoneinfo import ZoneInfo

from airport_surface import graph_id, load_graph, save_graph
from flight import Flight, MovementType
from flight.flight_repository import FlightDatabase, flight_source_name
from path_map import (
    BatchStats,
    MatchConfig,
    Matcher,
    PathRecord,
    match_batch,
)

LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class DatabaseDataset:
    name: str
    movement_type: MovementType
    database: FlightDatabase

    @property
    def source(self) -> str:
        return flight_source_name(self.movement_type.value)

    def iterate(self, limit: int | None = None) -> Iterator[Flight]:
        yield from self.database.observations.iterate(self.movement_type.value, limit)


class BatchMatchingRunner:
    """Match prepared datasets and persist the existing batch result format."""

    def __init__(
        self,
        graph_path: Path,
        datasets: tuple[DatabaseDataset, ...],
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

    def _run_batch(
        self,
        dataset: DatabaseDataset,
        matcher: Matcher,
        graph_identity: str,
        path_file: TextIO,
        match_file: TextIO,
        path_ids: dict[tuple[tuple[Any, Any, Any], ...], int],
    ) -> tuple[dict[str, Any], BatchStats]:
        started = time.perf_counter()
        stats = BatchStats()
        inputs = ((flight.flight_id, flight) for flight in dataset.iterate(limit=self.limit))
        for number, outcome in enumerate(match_batch(matcher, inputs), start=1):
            stats.add(outcome.status, outcome.failure_type, outcome.elapsed_seconds)
            result: dict[str, Any] = {
                "flight_id": outcome.key,
                "movement_type": dataset.movement_type.value,
                "observation_count": outcome.observation_count,
                "elapsed_seconds": outcome.elapsed_seconds,
            }
            path = outcome.path
            if path is None:
                result.update(
                    path_id=None, failure_type=outcome.failure_type, reason=outcome.reason,
                )
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

            match_file.write(
                json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            if number % 100 == 0:
                match_file.flush()
                path_file.flush()
                print(
                    f"[{dataset.name}] processed={number} "
                    f"matched={stats.counts['success']} failed={stats.counts['failed']}"
                )

        elapsed = time.perf_counter() - started
        summary = stats.summary()
        total = summary["total_flights"]
        print(
            f"[{dataset.name}] total={total} matched={summary['matched_flights']} "
            f"failed={summary['failed_flights']} elapsed={elapsed:.2f}s"
        )
        return {
            "batch": dataset.name,
            "input": dataset.source,
            **summary,
            "elapsed_seconds": elapsed,
            "average_seconds_per_flight": elapsed / total if total else None,
        }, stats

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
        stats = BatchStats()
        path_ids: dict[tuple[tuple[Any, Any, Any], ...], int] = {}
        started = time.perf_counter()
        with (
            (run_dir / "paths.jsonl").open("w", encoding="utf-8") as path_file,
            (run_dir / "matches.jsonl").open("w", encoding="utf-8") as match_file,
        ):
            for dataset in self.datasets:
                summary, batch_stats = self._run_batch(
                    dataset,
                    matcher,
                    graph_identity,
                    path_file,
                    match_file,
                    path_ids,
                )
                summaries.append(summary)
                stats.merge(batch_stats)

        report = {
            "started_at": run_started_at.isoformat(),
            "completed_at": datetime.now(LOCAL_TIMEZONE).isoformat(),
            "graph_id": graph_identity,
            **stats.summary(),
            "unique_paths": len(path_ids),
            "elapsed_seconds": time.perf_counter() - started,
            "batches": summaries,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return report
