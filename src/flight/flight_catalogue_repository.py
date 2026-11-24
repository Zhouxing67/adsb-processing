"""Flight catalogue and validation-cohort queries."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from db import DuckDBConnection

from .models import FlightSummary, utc_timestamp

STAND_COLUMNS = {
    "departure": ("adsb_dep", "dep_stand_position"),
    "arrival": ("adsb_arr", "arr_stand_position"),
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
                placeholders, parameters = self._database.bind(
                    connection,
                    min_points,
                    max_points,
                    query.lower(),
                    not stands,
                    list(stands),
                    start_date,
                    end_date,
                    display_timezone,
                    BEIJING,
                )
                (
                    minimum,
                    maximum,
                    search,
                    all_stands,
                    stand_values,
                    first_date,
                    last_date,
                    zone,
                    input_zone,
                ) = placeholders
                rows = connection.execute(
                    f"""
                    WITH parameters AS (
                        SELECT {minimum} AS minimum_points,
                               {maximum} AS maximum_points,
                               {search} AS search_text,
                               {all_stands} AS include_all_stands,
                               {stand_values} AS stand_values,
                               {first_date} AS first_date,
                               {last_date} AS last_date,
                               {zone} AS display_zone,
                               {input_zone} AS input_zone
                    ), flights AS (
                        SELECT flight_id, MIN(number) AS number,
                               COUNT(DISTINCT number) AS number_count,
                               MIN(timestamp) AS started, MAX(timestamp) AS ended,
                               COUNT(*) AS points,
                               MIN(NULLIF(TRIM({column}), '')) AS stand,
                               COUNT(DISTINCT NULLIF(TRIM({column}), '')) AS stand_count
                        FROM main.{table}
                        WHERE flight_id IS NOT NULL AND trim(flight_id) <> ''
                        GROUP BY flight_id
                    )
                    SELECT flights.* FROM flights CROSS JOIN parameters
                    WHERE points >= minimum_points
                      AND (maximum_points IS NULL OR points <= maximum_points)
                      AND (search_text = '' OR contains(lower(flight_id), search_text)
                           OR (number_count = 1 AND contains(lower(number), search_text)))
                      AND (include_all_stands OR (stand_count <= 1
                           AND coalesce(stand, '') = ANY(stand_values::VARCHAR[])))
                      AND (first_date IS NULL OR
                           CAST(timezone(display_zone, timezone(input_zone, started)) AS DATE)
                           >= first_date)
                      AND (last_date IS NULL OR
                           CAST(timezone(display_zone, timezone(input_zone, started)) AS DATE)
                           <= last_date)
                    ORDER BY flight_id
                    """,
                    parameters,
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

    def whitelist_flights(self) -> set[tuple[str, str]]:
        with self._database.connection() as connection:
            rows = connection.execute(
                "SELECT movement, flight_id FROM main.flight_whitelist "
                "WHERE movement IS NOT NULL AND flight_id IS NOT NULL"
            ).fetchall()
            return {(str(movement), str(flight_id)) for movement, flight_id in rows}
