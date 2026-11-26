"""Flight observation loading and detail queries (PostgreSQL)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timezone
from itertools import groupby
from typing import Any, Iterator

from db import PostgresConnection

from .models import Flight

OBSERVATION_COLUMNS = [
    "timestamp",
    "longitude",
    "latitude",
    "altitude",
    "groundspeed",
    "vertical_rate",
    "track",
    "source_month",
]

FLIGHT_SELECT_SQL = """
    SELECT
        flight_pk,
        movement,
        flight_id,
        number,
        a_num,
        r_type,
        org_name,
        dst_name,
        org_runway,
        dst_runway,
        CASE WHEN stand_is_overridden THEN stand_override ELSE raw_stand_position END
            AS effective_stand,
        stand_is_overridden,
        conflict_fields,
        sche_dep,
        sche_arr,
        actual_dep,
        actual_arr,
        point_count,
        number_count,
        CASE WHEN stand_is_overridden THEN
            CASE WHEN stand_override IS NULL THEN 0 ELSE 1 END
        ELSE stand_count END AS effective_stand_count,
        source_month
    FROM public.flights
"""


def _flight_base_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    movement = str(row["movement"])
    effective_stand = row["effective_stand"]
    return {
        "flight_id": str(row["flight_id"]),
        "number": row["number"],
        "a_num": row["a_num"],
        "r_type": row["r_type"],
        "org_name": row["org_name"],
        "dst_name": row["dst_name"],
        "org_runway": row["org_runway"],
        "dst_runway": row["dst_runway"],
        "dep_stand_position": effective_stand if movement == "departure" else None,
        "arr_stand_position": effective_stand if movement == "arrival" else None,
        "sche_dep": row["sche_dep"],
        "sche_arr": row["sche_arr"],
        "actual_dep": row["actual_dep"],
        "actual_arr": row["actual_arr"],
    }


def _active_conflicts(row: Mapping[str, Any]) -> dict[str, list[Any]]:
    movement = str(row["movement"])
    stand_col = "dep_stand_position" if movement == "departure" else "arr_stand_position"
    stand_overridden = bool(row.get("stand_is_overridden"))
    raw_conflicts = row.get("conflict_fields")
    result: dict[str, list[Any]] = {}
    if isinstance(raw_conflicts, Mapping):
        for field_name, values in raw_conflicts.items():
            if stand_overridden and field_name == stand_col:
                continue
            if isinstance(values, list) and len(values) > 1:
                result[str(field_name)] = list(values)
    if int(row.get("number_count") or 0) > 1 and "number" not in result:
        result["number"] = []
    if (
        not stand_overridden
        and int(row.get("effective_stand_count") or 0) > 1
        and stand_col not in result
    ):
        result[stand_col] = []
    return result


def _apply_od_conflicts(flight: Flight, row: Mapping[str, Any]) -> Flight:
    """Restore od_error when normalized public.flights records conflicting raw OD values."""
    if flight.od_error is not None:
        return flight
    movement = str(row["movement"])
    od_fields = (
        ("dep_stand_position", "org_runway")
        if movement == "departure"
        else ("arr_stand_position", "dst_runway")
    )
    active = _active_conflicts(row)
    conflicting = [field for field in od_fields if field in active]
    if conflicting:
        flight.od_error = f"Conflicting OD fields: {', '.join(conflicting)}"
    return flight


def _merge_observation_row(base: Mapping[str, Any], obs: Mapping[str, Any]) -> dict[str, Any]:
    ts = obs["ts"]
    return {
        **base,
        "timestamp": ts.astimezone(timezone.utc) if ts is not None else None,
        "longitude": obs["longitude"],
        "latitude": obs["latitude"],
        "altitude": obs["altitude"],
        "groundspeed": obs["groundspeed"],
        "vertical_rate": obs["vertical_rate"],
        "track": obs["track"],
        "source_month": obs["source_month"],
    }


class FlightObservationRepository:
    def __init__(self, database: PostgresConnection) -> None:
        self._database = database

    def flight(self, movement: str, identifier: str) -> Flight:
        with self._database.connection() as connection:
            flight_row = connection.execute(
                f"{FLIGHT_SELECT_SQL} WHERE movement = :movement AND flight_id = :flight_id",
                {"movement": movement, "flight_id": identifier},
            ).mappings().fetchone()
            if flight_row is None:
                raise ValueError(f"Flight not found: {movement}/{identifier}")
            base = _flight_base_fields(flight_row)
            obs_rows = connection.execute(
                """
                SELECT ts, longitude, latitude, altitude, groundspeed,
                       vertical_rate, track, source_month
                FROM public.adsb_observations
                WHERE flight_pk = :flight_pk
                ORDER BY ts, ctid
                """,
                {"flight_pk": flight_row["flight_pk"]},
            ).mappings()
            records = [_merge_observation_row(base, obs) for obs in obs_rows]
            flight_obj = Flight(records, movement=movement, input_zone=timezone.utc)
            return _apply_od_conflicts(flight_obj, flight_row)

    def flights_batch(self, movement: str, identifiers: Sequence[str]) -> dict[str, Flight]:
        """Load multiple flights for one movement in two indexed queries."""
        unique_ids = list(dict.fromkeys(identifiers))
        if not unique_ids:
            return {}
        with self._database.connection() as connection:
            flight_rows = connection.execute(
                f"{FLIGHT_SELECT_SQL} "
                "WHERE movement = :movement AND flight_id = ANY(:flight_ids)",
                {"movement": movement, "flight_ids": unique_ids},
            ).mappings().fetchall()
            if not flight_rows:
                return {}
            pk_to_meta: dict[int, tuple[str, dict[str, Any], Mapping[str, Any]]] = {
                int(row["flight_pk"]): (str(row["flight_id"]), _flight_base_fields(row), row)
                for row in flight_rows
            }
            obs_rows = connection.execute(
                """
                SELECT flight_pk, ts, longitude, latitude, altitude, groundspeed,
                       vertical_rate, track, source_month
                FROM public.adsb_observations
                WHERE flight_pk = ANY(:flight_pks)
                ORDER BY flight_pk, ts, ctid
                """,
                {"flight_pks": list(pk_to_meta.keys())},
            ).mappings()
            result: dict[str, Flight] = {}
            for fpk, group in groupby(obs_rows, key=lambda r: int(r["flight_pk"])):
                fid, base, row_meta = pk_to_meta[fpk]
                records = [_merge_observation_row(base, obs) for obs in group]
                if records:
                    flight_obj = Flight(records, movement=movement, input_zone=timezone.utc)
                    result[fid] = _apply_od_conflicts(flight_obj, row_meta)
            return result

    def detail(
        self,
        movement: str,
        identifier: str,
        offset: int,
        limit: int,
        business_fields: set[str],
    ) -> tuple[list[str], dict[str, Any], dict[str, list[Any]], list[dict[str, Any]], int]:
        del business_fields  # Normalized in public.flights
        with self._database.connection() as connection:
            flight_row = connection.execute(
                f"{FLIGHT_SELECT_SQL} WHERE movement = :movement AND flight_id = :flight_id",
                {"movement": movement, "flight_id": identifier},
            ).mappings().fetchone()
            if flight_row is None:
                return list(OBSERVATION_COLUMNS), {}, {}, [], 0

            fields = _flight_base_fields(flight_row)
            fields["source_month"] = flight_row["source_month"]

            total_row = connection.execute(
                "SELECT COUNT(*) FROM public.adsb_observations WHERE flight_pk = :flight_pk",
                {"flight_pk": flight_row["flight_pk"]},
            ).fetchone()
            total = int(total_row[0]) if total_row is not None else 0

            obs_rows = connection.execute(
                """
                SELECT ts, longitude, latitude, altitude, groundspeed,
                       vertical_rate, track, source_month
                FROM public.adsb_observations
                WHERE flight_pk = :flight_pk
                ORDER BY ts, ctid
                LIMIT :limit OFFSET :offset
                """,
                {"flight_pk": flight_row["flight_pk"], "limit": limit, "offset": offset},
            ).mappings()
            observations = [
                {
                    "timestamp": (
                        row["ts"].astimezone(timezone.utc) if row["ts"] is not None else None
                    ),
                    "longitude": row["longitude"],
                    "latitude": row["latitude"],
                    "altitude": row["altitude"],
                    "groundspeed": row["groundspeed"],
                    "vertical_rate": row["vertical_rate"],
                    "track": row["track"],
                    "source_month": row["source_month"],
                }
                for row in obs_rows
            ]
            inconsistent = _active_conflicts(flight_row)
            return list(OBSERVATION_COLUMNS), fields, inconsistent, observations, total

    def iterate(self, movement: str, limit: int | None) -> Iterator[Flight]:
        batch_size = 200
        with self._database.connection() as connection:
            sql = (
                "SELECT flight_id FROM public.flights "
                "WHERE movement = :movement ORDER BY flight_id"
            )
            params: dict[str, Any] = {"movement": movement}
            if limit is not None:
                sql += " LIMIT :limit"
                params["limit"] = limit
            flight_ids = [str(row[0]) for row in connection.execute(sql, params).fetchall()]

        for start in range(0, len(flight_ids), batch_size):
            chunk_ids = flight_ids[start : start + batch_size]
            loaded = self.flights_batch(movement, chunk_ids)
            for fid in chunk_ids:
                flight = loaded.get(fid)
                if flight is not None:
                    yield flight
