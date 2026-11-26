"""Flight catalogue, SQL pagination, and validation-cohort queries (PostgreSQL)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timezone
from typing import Any, Iterator

from db import PostgresConnection

from .models import FlightSummary

STAND_COLUMNS = {
    "departure": ("flights", "dep_stand_position"),
    "arrival": ("flights", "arr_stand_position"),
}
BEIJING = "Asia/Shanghai"
EXCLUDED_VALIDATION_STANDS = ("952L", "14", "504", "506", "951L", "952R")

_EFFECTIVE_STAND_SQL = (
    "CASE WHEN f.stand_is_overridden THEN f.stand_override ELSE f.raw_stand_position END"
)
_EFFECTIVE_STAND_COUNT_SQL = (
    "CASE WHEN f.stand_is_overridden THEN "
    "CASE WHEN f.stand_override IS NULL THEN 0 ELSE 1 END "
    "ELSE f.stand_count END"
)
_FLIGHT_KEY_SQL = "public.flight_key_for(f.movement, f.flight_id)"


def _row_to_summary(row: tuple[Any, ...]) -> FlightSummary:
    direction, identifier, number, numbers, start, end, points, stand, count = row
    return FlightSummary(
        movement=str(direction),
        flight_id=str(identifier),
        flight_number=str(number) if numbers == 1 and number is not None else None,
        number_count=int(numbers),
        start_time=start.astimezone(timezone.utc),
        end_time=end.astimezone(timezone.utc),
        point_count=int(points),
        stand_position=str(stand) if count <= 1 and stand is not None else None,
        stand_count=int(count),
    )


def _build_filter_where(
    *,
    movement: str | None = None,
    query: str = "",
    min_points: int = 0,
    max_points: int | None = None,
    stands: tuple[str, ...] = (),
    start_date: date | None = None,
    end_date: date | None = None,
    validation_only: bool = False,
    issues_only: bool = False,
    include_keys: Sequence[str] | None = None,
    exclude_keys: Sequence[str] | None = None,
    display_timezone: str = BEIJING,
) -> tuple[str, dict[str, Any]]:
    clauses = [
        "f.start_time IS NOT NULL",
        "f.end_time IS NOT NULL",
        "f.point_count >= :min_points",
    ]
    params: dict[str, Any] = {
        "min_points": min_points,
        "display_zone": display_timezone,
    }
    if movement:
        clauses.append("f.movement = :movement")
        params["movement"] = movement
    if max_points is not None:
        clauses.append("f.point_count <= :max_points")
        params["max_points"] = max_points
    search = query.strip().lower()
    if search:
        clauses.append(
            "(strpos(lower(f.flight_id), :search) > 0 "
            "OR (f.number_count = 1 AND f.number IS NOT NULL "
            "AND strpos(lower(f.number), :search) > 0))"
        )
        params["search"] = search
    if stands:
        clauses.append(
            f"({_EFFECTIVE_STAND_COUNT_SQL}) <= 1 "
            f"AND COALESCE({_EFFECTIVE_STAND_SQL}, '') = ANY(:stands)"
        )
        params["stands"] = list(stands)
    if start_date is not None:
        clauses.append("(f.start_time AT TIME ZONE :display_zone)::date >= :start_date")
        params["start_date"] = start_date
    if end_date is not None:
        clauses.append("(f.start_time AT TIME ZONE :display_zone)::date <= :end_date")
        params["end_date"] = end_date
    if validation_only:
        clauses.append("f.point_count >= 30")
        clauses.append(
            "((f.movement = 'departure' AND f.org_runway IS NOT NULL) "
            "OR (f.movement = 'arrival' AND f.dst_runway IS NOT NULL))"
        )
        clauses.append(f"({_EFFECTIVE_STAND_SQL}) IS NOT NULL")
        clauses.append(f"({_EFFECTIVE_STAND_SQL}) <> ALL(:excluded_stands)")
        params["excluded_stands"] = list(EXCLUDED_VALIDATION_STANDS)
    if issues_only:
        clauses.append(
            "EXISTS (SELECT 1 FROM public.match_issues mi "
            "WHERE mi.movement = f.movement AND mi.flight_id = f.flight_id)"
        )
    if include_keys is not None:
        clauses.append(f"{_FLIGHT_KEY_SQL} = ANY(:include_keys)")
        params["include_keys"] = list(include_keys)
    if exclude_keys:
        clauses.append(f"NOT ({_FLIGHT_KEY_SQL} = ANY(:exclude_keys))")
        params["exclude_keys"] = list(exclude_keys)
    return " AND ".join(clauses), params


class FlightCatalogueRepository:
    def __init__(self, database: PostgresConnection) -> None:
        self._database = database

    def dataset_stats(self, *, display_timezone: str = BEIJING) -> dict[str, Any]:
        """Compute lightweight dataset bounds and distinct stand options in PostgreSQL."""
        with self._database.connection() as connection:
            stats_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total_flights,
                    COALESCE(MAX(point_count), 0) AS max_points,
                    MIN((start_time AT TIME ZONE :display_zone)::date) AS min_date,
                    MAX((start_time AT TIME ZONE :display_zone)::date) AS max_date
                FROM public.flights
                WHERE start_time IS NOT NULL AND end_time IS NOT NULL
                """,
                {"display_zone": display_timezone},
            ).fetchone()
            stand_rows = connection.execute(
                f"""
                SELECT DISTINCT {_EFFECTIVE_STAND_SQL} AS stand
                FROM public.flights f
                WHERE f.start_time IS NOT NULL
                  AND f.end_time IS NOT NULL
                  AND ({_EFFECTIVE_STAND_COUNT_SQL}) <= 1
                  AND ({_EFFECTIVE_STAND_SQL}) IS NOT NULL
                ORDER BY stand
                """
            ).fetchall()

        total, max_points, min_date, max_date = (
            stats_row if stats_row is not None else (0, 0, None, None)
        )
        return {
            "total_flights": int(total),
            "dataset_max_points": int(max_points),
            "dataset_min_date": min_date.isoformat() if min_date is not None else None,
            "dataset_max_date": max_date.isoformat() if max_date is not None else None,
            "stand_options": [str(row[0]) for row in stand_rows],
        }

    def get_by_keys(self, flight_keys: Sequence[str]) -> dict[str, FlightSummary]:
        """Resolve flight summaries by deterministic flight_key via idx_flights_flight_key."""
        unique_keys = list(dict.fromkeys(flight_keys))
        if not unique_keys:
            return {}
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    {_FLIGHT_KEY_SQL} AS flight_key,
                    f.movement,
                    f.flight_id,
                    f.number,
                    f.number_count,
                    f.start_time,
                    f.end_time,
                    f.point_count,
                    {_EFFECTIVE_STAND_SQL} AS stand,
                    {_EFFECTIVE_STAND_COUNT_SQL} AS effective_stand_count
                FROM public.flights f
                WHERE {_FLIGHT_KEY_SQL} = ANY(:flight_keys)
                  AND f.start_time IS NOT NULL
                  AND f.end_time IS NOT NULL
                """,
                {"flight_keys": unique_keys},
            ).fetchall()
        return {str(row[0]): _row_to_summary(row[1:]) for row in rows}

    def query_page(
        self,
        *,
        movement: str | None = None,
        query: str = "",
        min_points: int = 0,
        max_points: int | None = None,
        stands: tuple[str, ...] = (),
        start_date: date | None = None,
        end_date: date | None = None,
        validation_only: bool = False,
        issues_only: bool = False,
        include_keys: Sequence[str] | None = None,
        exclude_keys: Sequence[str] | None = None,
        display_timezone: str = BEIJING,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[tuple[str, FlightSummary]], int]:
        """Filter and paginate flights directly in PostgreSQL."""
        if include_keys is not None and len(include_keys) == 0:
            return [], 0
        where_sql, params = _build_filter_where(
            movement=movement,
            query=query,
            min_points=min_points,
            max_points=max_points,
            stands=stands,
            start_date=start_date,
            end_date=end_date,
            validation_only=validation_only,
            issues_only=issues_only,
            include_keys=include_keys,
            exclude_keys=exclude_keys,
            display_timezone=display_timezone,
        )
        with self._database.connection() as connection:
            total_row = connection.execute(
                f"SELECT COUNT(*) FROM public.flights f WHERE {where_sql}",
                params,
            ).fetchone()
            total = int(total_row[0]) if total_row is not None else 0
            if total == 0 or offset >= total:
                return [], total
            rows = connection.execute(
                f"""
                SELECT
                    {_FLIGHT_KEY_SQL} AS flight_key,
                    f.movement,
                    f.flight_id,
                    f.number,
                    f.number_count,
                    f.start_time,
                    f.end_time,
                    f.point_count,
                    {_EFFECTIVE_STAND_SQL} AS stand,
                    {_EFFECTIVE_STAND_COUNT_SQL} AS effective_stand_count
                FROM public.flights f
                WHERE {where_sql}
                ORDER BY f.movement, f.flight_id
                LIMIT :limit OFFSET :offset
                """,
                {**params, "limit": limit, "offset": offset},
            ).fetchall()
        return [(str(row[0]), _row_to_summary(row[1:])) for row in rows], total

    def query_flight_keys(
        self,
        *,
        movement: str | None = None,
        query: str = "",
        min_points: int = 0,
        max_points: int | None = None,
        stands: tuple[str, ...] = (),
        start_date: date | None = None,
        end_date: date | None = None,
        validation_only: bool = False,
        issues_only: bool = False,
        include_keys: Sequence[str] | None = None,
        exclude_keys: Sequence[str] | None = None,
        display_timezone: str = BEIJING,
    ) -> list[str]:
        """Return ordered deterministic flight_keys matching filters directly from PostgreSQL."""
        if include_keys is not None and len(include_keys) == 0:
            return []
        where_sql, params = _build_filter_where(
            movement=movement,
            query=query,
            min_points=min_points,
            max_points=max_points,
            stands=stands,
            start_date=start_date,
            end_date=end_date,
            validation_only=validation_only,
            issues_only=issues_only,
            include_keys=include_keys,
            exclude_keys=exclude_keys,
            display_timezone=display_timezone,
        )
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT {_FLIGHT_KEY_SQL} AS flight_key
                FROM public.flights f
                WHERE {where_sql}
                ORDER BY f.movement, f.flight_id
                """,
                params,
            ).fetchall()
        return [str(row[0]) for row in rows]

    def summaries(
        self,
        *,
        movement: str | None = None,
        query: str = "",
        min_points: int = 0,
        max_points: int | None = None,
        stands: tuple[str, ...] = (),
        start_date: date | None = None,
        end_date: date | None = None,
        display_timezone: str = BEIJING,
    ) -> Iterator[FlightSummary]:
        where_sql, params = _build_filter_where(
            movement=movement,
            query=query,
            min_points=min_points,
            max_points=max_points,
            stands=stands,
            start_date=start_date,
            end_date=end_date,
            display_timezone=display_timezone,
        )
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    f.movement,
                    f.flight_id,
                    f.number,
                    f.number_count,
                    f.start_time,
                    f.end_time,
                    f.point_count,
                    {_EFFECTIVE_STAND_SQL} AS stand,
                    {_EFFECTIVE_STAND_COUNT_SQL} AS effective_stand_count
                FROM public.flights f
                WHERE {where_sql}
                ORDER BY f.movement, f.flight_id
                """,
                params,
            ).fetchall()

        for row in rows:
            yield _row_to_summary(row)

    def validation_flights(self, lower_threshold: int = 30) -> list[dict[str, Any]]:
        if lower_threshold < 1:
            raise ValueError("lower_threshold must be positive")
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                WITH cohort AS (
                    SELECT
                        f.flight_id,
                        CASE WHEN f.movement = 'departure' THEN 'dep' ELSE 'arr' END AS movement,
                        {_EFFECTIVE_STAND_SQL} AS stand,
                        f.point_count AS flight_points
                    FROM public.flights f
                    WHERE f.point_count >= :threshold
                      AND (
                          (f.movement = 'departure' AND f.org_runway IS NOT NULL)
                          OR (f.movement = 'arrival' AND f.dst_runway IS NOT NULL)
                      )
                )
                SELECT
                    flight_id,
                    movement,
                    stand,
                    flight_points,
                    COUNT(*) OVER () AS total_flights
                FROM cohort
                WHERE stand IS NOT NULL
                  AND stand <> ALL(:excluded_stands)
                ORDER BY movement, flight_id, stand
                """,
                {
                    "threshold": lower_threshold,
                    "excluded_stands": list(EXCLUDED_VALIDATION_STANDS),
                },
            )
            return [dict(row) for row in rows.mappings()]
