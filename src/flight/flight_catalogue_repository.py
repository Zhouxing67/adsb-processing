"""Flight catalogue and validation-cohort queries."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .duckdb_connection import DuckDBConnection
from .models import FlightSummary, utc_timestamp

STAND_COLUMNS = {
    "departure": ("adsb_202406_dep", "dep_stand_position"),
    "arrival": ("adsb_202406_arr", "arr_stand_position"),
}
BEIJING = "Asia/Shanghai"


class FlightCatalogueRepository:
    def __init__(self, database: DuckDBConnection) -> None:
        self._database = database

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
        with self._database.connection() as connection:
            for direction, (table, column) in STAND_COLUMNS.items():
                if movement and movement != direction:
                    continue
                rows = connection.execute(
                    f"""
                    WITH flights AS (
                        SELECT flight_id, MIN("NUMBER") AS number,
                               COUNT(DISTINCT "NUMBER") AS number_count,
                               MIN(timestamp) AS started, MAX(timestamp) AS ended,
                               COUNT(*) AS points,
                               MIN(NULLIF(TRIM({column}), '')) AS stand,
                               COUNT(DISTINCT NULLIF(TRIM({column}), '')) AS stand_count
                        FROM main.{table}
                        WHERE flight_id IS NOT NULL AND trim(flight_id) <> ''
                        GROUP BY flight_id
                    )
                    SELECT * FROM flights
                    WHERE points >= $minimum AND ($maximum IS NULL OR points <= $maximum)
                      AND ($query = '' OR contains(lower(flight_id), $query)
                           OR (number_count = 1 AND contains(lower(number), $query)))
                      AND ($all_stands OR (stand_count <= 1
                           AND coalesce(stand, '') = ANY($stands::VARCHAR[])))
                      AND ($start_date IS NULL OR
                           CAST(timezone($zone, timezone($input_zone, started)) AS DATE)
                           >= $start_date)
                      AND ($end_date IS NULL OR
                           CAST(timezone($zone, timezone($input_zone, started)) AS DATE)
                           <= $end_date)
                    ORDER BY flight_id
                    """,
                    {
                        "minimum": min_points,
                        "maximum": max_points,
                        "query": query.lower(),
                        "all_stands": not stands,
                        "stands": list(stands),
                        "start_date": start_date,
                        "end_date": end_date,
                        "zone": display_timezone,
                        "input_zone": BEIJING,
                    },
                ).fetchall()
                for identifier, number, numbers, start, end, points, stand, count in rows:
                    if start is None or end is None:
                        continue
                    yield FlightSummary(
                        movement=direction,
                        flight_id=identifier,
                        flight_number=str(number) if numbers == 1 else None,
                        number_count=numbers,
                        start_time=utc_timestamp(start, ZoneInfo(BEIJING)),
                        end_time=utc_timestamp(end, ZoneInfo(BEIJING)),
                        point_count=points,
                        stand_position=stand if count <= 1 else None,
                        stand_count=count,
                    )

    def validation_flights(self, lower_threshold: int = 30) -> list[dict[str, Any]]:
        if lower_threshold < 1:
            raise ValueError("lower_threshold must be positive")
        with self._database.connection() as connection:
            (threshold,), parameters = self._database.bind(connection, lower_threshold)
            queries = []
            for movement, suffix, runway in (
                ("departure", "dep", "org_runway"),
                ("arrival", "arr", "dst_runway"),
            ):
                table, stand = STAND_COLUMNS[movement]
                queries.append(f"""
                    SELECT flight_id, '{suffix}' AS movement, {stand} AS stand,
                           COUNT(*) AS flight_points
                    FROM main.{table}
                    WHERE {stand} IS NOT NULL
                      AND {stand} NOT IN ('952L', '14', '504', '506', '951L', '952R')
                      AND {runway} IS NOT NULL
                    GROUP BY flight_id, {stand}
                    HAVING COUNT(*) >= {threshold}
                """)
            cohort = " UNION ALL ".join(queries)
            rows = connection.execute(
                f"SELECT *, COUNT(*) OVER () AS total_flights FROM ({cohort}) "
                "ORDER BY movement, flight_id, stand",
                parameters * len(queries),
            )
            return [dict(row) for row in rows.mappings()]
