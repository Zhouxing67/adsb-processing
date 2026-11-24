"""Archived matching-issue management service for the workbench."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from flight.flight_repository import FlightDatabase, database_flight_key


class MatchIssueService:
    """Archive, list, and remove flights in main.match_issues."""

    def __init__(
        self,
        flight_database: FlightDatabase,
        *,
        graph_id: str,
        lock: Any,
        items: Mapping[str, Any],
        results: Mapping[str, Any],
    ) -> None:
        self.flight_database = flight_database
        self.graph_id = graph_id
        self.lock = lock
        self.items = items
        self.results = results

    def issue_map(self) -> dict[str, str | None]:
        return {
            key: entry.reason
            for entry in self.flight_database.issues.list_all()
            if (key := database_flight_key(entry.movement, entry.flight_id)) in self.items
        }

    def list_issue_keys(self) -> dict[str, Any]:
        with self.lock:
            keys = sorted(self.issue_map())
        return {"flight_keys": keys, "count": len(keys)}

    def add_issues(
        self,
        flight_keys: Sequence[str],
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if self.flight_database.read_only:
            raise ValueError("当前数据库为只读模式，无法归档异常航班")
        keys = list(dict.fromkeys(flight_keys))
        if not keys:
            raise ValueError("至少选择一条航班")
        with self.lock:
            records = []
            for key in keys:
                if key not in self.items:
                    raise KeyError(f"未知 flight_key: {key}")
                item = self.items[key]
                result = self.results[key]
                effective_reason = reason if reason is not None else result.error
                records.append(
                    (item.movement_type, item.flight_id, effective_reason, self.graph_id)
                )
        try:
            inserted, existing = self.flight_database.issues.add(records)
        except self.flight_database.database_error as error:
            raise RuntimeError("异常航班归档失败") from error
        with self.lock:
            issue_keys = sorted(self.issue_map())
        return {
            "inserted": inserted,
            "existing": existing,
            "deleted": 0,
            "issue_flight_keys": issue_keys,
        }

    def remove_issues(self, flight_keys: Sequence[str]) -> dict[str, Any]:
        if self.flight_database.read_only:
            raise ValueError("当前数据库为只读模式，无法移除异常航班")
        keys = list(dict.fromkeys(flight_keys))
        if not keys:
            raise ValueError("至少选择一条航班")
        with self.lock:
            pairs = []
            for key in keys:
                if key not in self.items:
                    raise KeyError(f"未知 flight_key: {key}")
                item = self.items[key]
                pairs.append((item.movement_type, item.flight_id))
        try:
            deleted = self.flight_database.issues.remove(pairs)
        except self.flight_database.database_error as error:
            raise RuntimeError("异常航班移出失败") from error
        with self.lock:
            issue_keys = sorted(self.issue_map())
        return {
            "inserted": 0,
            "existing": 0,
            "deleted": deleted,
            "issue_flight_keys": issue_keys,
        }
