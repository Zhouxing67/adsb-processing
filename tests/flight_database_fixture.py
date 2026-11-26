"""Build isolated PostgreSQL test databases (adsb_test) for workbench and matching tests."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import psycopg

from db import apply_core_schema
from flight import Flight
from flight.flight_repository import FlightDatabase

DEFAULT_TEST_DATABASE_DSN = "postgresql+psycopg://postgres:123456@127.0.0.1:5432/adsb_test"


def test_database_dsn() -> str:
    return os.environ.get("ADSB_TEST_DATABASE_DSN", DEFAULT_TEST_DATABASE_DSN)


def _psycopg_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return "postgresql://" + dsn.removeprefix("postgresql+psycopg://")
    return dsn


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _utc_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def reset_test_database(dsn: str | None = None) -> str:
    resolved = dsn or test_database_dsn()
    with psycopg.connect(_psycopg_dsn(resolved)) as connection:
        apply_core_schema(connection)
        with connection.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE public.adsb_observations, public.flights, "
                "public.ingest_batches, public.match_issues, public.route_library "
                "RESTART IDENTITY CASCADE"
            )
        connection.commit()
    return resolved


def create_flight_database(
    flights: Sequence[Flight],
    movement_types: Sequence[str] | None = None,
    *,
    dsn: str | None = None,
) -> FlightDatabase:
    resolved = reset_test_database(dsn)
    movements = list(movement_types or ())

    with psycopg.connect(_psycopg_dsn(resolved)) as connection:
        with connection.cursor() as cur:
            for index, flight in enumerate(flights):
                movement = (
                    movements[index]
                    if index < len(movements)
                    else (flight.movement or "departure")
                )
                if movement not in ("arrival", "departure"):
                    raise ValueError(f"Unsupported fixture movement: {movement}")

                stand_key = "arr_stand_position" if movement == "arrival" else "dep_stand_position"
                runway_key = "dst_runway" if movement == "arrival" else "org_runway"
                distinct_numbers = sorted(
                    {
                        cleaned
                        for obs in flight.observations
                        if (
                            cleaned := _clean_text(
                                obs.metadata.get("number") or obs.metadata.get("NUMBER")
                            )
                        )
                    }
                )
                distinct_stands = sorted(
                    {
                        cleaned
                        for obs in flight.observations
                        if (cleaned := _clean_text(obs.metadata.get(stand_key)))
                    }
                )
                distinct_runways = sorted(
                    {
                        cleaned
                        for obs in flight.observations
                        if (cleaned := _clean_text(obs.metadata.get(runway_key)))
                    }
                )
                conflicts: dict[str, list[str]] = {}
                if len(distinct_numbers) > 1:
                    conflicts["number"] = distinct_numbers
                if len(distinct_stands) > 1:
                    conflicts[stand_key] = distinct_stands
                if len(distinct_runways) > 1:
                    conflicts[runway_key] = distinct_runways
                raw_stand = distinct_stands[0] if len(distinct_stands) == 1 else None
                number_val = distinct_numbers[0] if len(distinct_numbers) == 1 else None
                timestamps = [obs.timestamp.astimezone(timezone.utc) for obs in flight.observations]
                start_time = min(timestamps) if timestamps else None
                end_time = max(timestamps) if timestamps else None
                source_months = {
                    cleaned
                    for obs in flight.observations
                    if (cleaned := _clean_text(obs.metadata.get("source_month")))
                }
                source_month = next(iter(source_months)) if source_months else "2024-01"

                pk_row = cur.execute(
                    """
                    INSERT INTO public.flights (
                        movement, flight_id, number, number_count, a_num, r_type,
                        org_name, dst_name, org_runway, dst_runway,
                        raw_stand_position, stand_count, conflict_fields,
                        sche_dep, sche_arr, actual_dep, actual_arr,
                        start_time, end_time, point_count, source_month
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s::jsonb,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    RETURNING flight_pk
                    """,
                    (
                        movement,
                        flight.flight_id,
                        number_val,
                        len(distinct_numbers),
                        flight.a_num.upper() if flight.a_num else None,
                        flight.r_type,
                        flight.org_name,
                        flight.dst_name,
                        flight.org_runway,
                        flight.dst_runway,
                        raw_stand,
                        len(distinct_stands),
                        json.dumps(conflicts, ensure_ascii=False),
                        _utc_or_none(flight.sche_dep),
                        _utc_or_none(flight.sche_arr),
                        _utc_or_none(flight.actual_dep),
                        _utc_or_none(flight.actual_arr),
                        start_time,
                        end_time,
                        len(flight.observations),
                        source_month,
                    ),
                ).fetchone()
                assert pk_row is not None
                flight_pk = int(pk_row[0])

                for obs in flight.observations:
                    cur.execute(
                        """
                        INSERT INTO public.adsb_observations (
                            flight_pk, ts, longitude, latitude,
                            altitude, groundspeed, vertical_rate, track, source_month
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            flight_pk,
                            obs.timestamp.astimezone(timezone.utc),
                            float(obs.longitude),
                            float(obs.latitude),
                            _finite_float(obs.metadata.get("altitude")),
                            _finite_float(obs.metadata.get("groundspeed")),
                            _finite_float(obs.metadata.get("vertical_rate")),
                            _finite_float(obs.metadata.get("track")),
                            _clean_text(obs.metadata.get("source_month")) or source_month,
                        ),
                    )
        connection.commit()

    return FlightDatabase(resolved)
