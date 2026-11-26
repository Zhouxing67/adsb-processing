"""Import deduplicated taxi routes from a BatchMatchingRunner output directory."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from airport_surface import graph_id, load_graph
from path_map import Path as MatchedPath
from path_map import PathRecord

from .models import RouteEntry, RouteFlightMatch, normalize_movement
from .repository import RouteLibraryRepository


@dataclass(frozen=True, slots=True)
class ImportSummary:
    """Counts produced when importing one batch matching output directory."""

    run_dir: Path
    graph_id: str
    total_match_rows: int
    matched_rows: int
    skipped_missing_od: int
    unique_routes: int
    deleted_candidates: int
    inserted_routes: int
    existing_routes: int


def _require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"Required batch output file not found: {path}")
    return path


def import_batch_run(
    run_dir: str | Path,
    repository: RouteLibraryRepository,
    *,
    replace_candidates: bool = True,
) -> ImportSummary:
    """Read graph.json, paths.jsonl, and matches.jsonl and persist unique routes.

    By default replaces existing ``candidate`` routes for the same ``graph_id`` while
    preserving ``verified`` / ``rejected`` / ``manual`` entries. Pass
    ``replace_candidates=False`` to append incrementally without deleting candidates.
    """
    directory = Path(run_dir)
    graph_file = _require_file(directory / "graph.json")
    paths_file = _require_file(directory / "paths.jsonl")
    matches_file = _require_file(directory / "matches.jsonl")

    airport_graph = load_graph(graph_file)
    graph_identity = graph_id(airport_graph)

    resolved_paths: dict[int, MatchedPath] = {}
    with paths_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            path_id = int(item["path_id"])
            record = PathRecord.from_dict(item["path"])
            resolved_paths[path_id] = record.resolve(airport_graph)

    total_match_rows = 0
    matched_rows = 0
    skipped_missing_od = 0
    unique_entries: dict[str, RouteEntry] = {}
    flight_matches: list[RouteFlightMatch] = []

    with matches_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            total_match_rows += 1
            item = json.loads(text)
            path_id = item.get("path_id")
            if path_id is None:
                continue
            matched_rows += 1
            raw_stand = item.get("stand_ref")
            raw_runway = item.get("runway_ref")
            if (
                raw_stand is None
                or not str(raw_stand).strip()
                or raw_runway is None
                or not str(raw_runway).strip()
            ):
                skipped_missing_od += 1
                continue
            movement = normalize_movement(str(item["movement_type"]))
            matched_path = resolved_paths.get(int(path_id))
            if matched_path is None:
                raise ValueError(f"matches.jsonl references unknown path_id: {path_id!r}")
            entry = RouteEntry.from_path(
                airport_graph,
                matched_path,
                movement=movement,
                stand_ref=str(raw_stand),
                runway_ref=str(raw_runway),
                graph_identity=graph_identity,
            )
            unique_entries.setdefault(entry.route_id, entry)
            raw_flight_id = item.get("flight_id")
            if raw_flight_id is not None and str(raw_flight_id).strip():
                flight_matches.append(
                    RouteFlightMatch(
                        route_id=entry.route_id,
                        movement=movement,
                        flight_id=str(raw_flight_id),
                    )
                )

    entries = list(unique_entries.values())
    if replace_candidates:
        deleted, inserted, existing = repository.replace_candidates(
            graph_identity, entries, flight_matches=flight_matches
        )
    else:
        deleted = 0
        inserted, existing = repository.upsert_routes(entries, flight_matches=flight_matches)
    return ImportSummary(
        run_dir=directory,
        graph_id=graph_identity,
        total_match_rows=total_match_rows,
        matched_rows=matched_rows,
        skipped_missing_od=skipped_missing_od,
        unique_routes=len(entries),
        deleted_candidates=deleted,
        inserted_routes=inserted,
        existing_routes=existing,
    )
