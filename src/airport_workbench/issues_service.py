"""Archived matching-issue management service for the workbench."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from flight.flight_repository import FlightDatabase, database_flight_key

logger = logging.getLogger(__name__)


class MatchIssueService:
    """Archive, list, and remove flights in public.match_issues."""

    def __init__(
        self,
        flight_database: FlightDatabase,
        *,
        graph_id: str,
        lock: Any,
        items: Mapping[str, Any],
        results: Mapping[str, Any],
        resolve_items: Callable[[Sequence[str]], dict[str, Any]] | None = None,
    ) -> None:
        self.flight_database = flight_database
        self.graph_id = graph_id
        self.lock = lock
        self.items = items
        self.results = results
        self._resolve_items_batch = resolve_items

    def _resolve_items(self, keys: Sequence[str]) -> dict[str, Any]:
        if self._resolve_items_batch is not None:
            return self._resolve_items_batch(keys)
        return {key: self.items[key] for key in dict.fromkeys(keys) if key in self.items}

    def issue_map(self) -> dict[str, str | None]:
        entries = self.flight_database.issues.list_all()
        if not entries:
            return {}
        keyed = [
            (database_flight_key(entry.movement, entry.flight_id), entry.reason)
            for entry in entries
        ]
        known = self._resolve_items([key for key, _ in keyed])
        return {key: reason for key, reason in keyed if key in known}

    def list_issue_keys(self) -> dict[str, Any]:
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
        resolved = self._resolve_items(keys)
        for key in keys:
            if key not in resolved:
                raise KeyError(f"未知 flight_key: {key}")
        with self.lock:
            records = []
            for key in keys:
                item = resolved[key]
                result = self.results.get(key)
                effective_reason = (
                    reason if reason is not None else (result.error if result is not None else None)
                )
                records.append(
                    (item.movement_type, item.flight_id, effective_reason, self.graph_id)
                )
        try:
            inserted, existing = self.flight_database.issues.add(records)
        except self.flight_database.database_error as error:
            logger.exception("Failed to archive %d match issues", len(records))
            raise RuntimeError("异常航班归档失败") from error
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
        resolved = self._resolve_items(keys)
        for key in keys:
            if key not in resolved:
                raise KeyError(f"未知 flight_key: {key}")
        pairs = [(resolved[key].movement_type, resolved[key].flight_id) for key in keys]
        try:
            deleted = self.flight_database.issues.remove(pairs)
        except self.flight_database.database_error as error:
            logger.exception("Failed to remove %d match issues", len(pairs))
            raise RuntimeError("异常航班移出失败") from error
        issue_keys = sorted(self.issue_map())
        return {
            "inserted": 0,
            "existing": 0,
            "deleted": deleted,
            "issue_flight_keys": issue_keys,
        }
