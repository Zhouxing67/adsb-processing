"""Directly ingest monthly raw ADS-B CSV files into PostgreSQL.

Features:
  1. Streams large raw CSVs in chunks (handles multi-GB files with low memory).
  2. Vectorized airport-boundary filtering via Shapely 2 (no PostGIS required).
  3. Converts groundspeed from km/h to kt and filters surface points (<= max_groundspeed_kt).
  4. Idempotent per source_month: safely replaces observations for that month while
     preserving manual stand overrides (stand_override / stand_is_overridden) in public.flights.
  5. Automatically creates monthly UTC partitions on public.adsb_observations before COPY.
"""

from __future__ import annotations

import argparse
import json
import math
import tomllib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import geopandas as gpd
import numpy as np
import pandas as pd
import psycopg
from shapely import contains_xy, unary_union

from db import CORE_SCHEMA_SQL

BEIJING_TZ = ZoneInfo("Asia/Shanghai")
CONFIG_FILE = Path("config.local.toml")
DEFAULT_BOUNDARY_PATH = Path("data/Geojson/airport_boundary.geojson")
DEFAULT_CHUNK_SIZE = 250_000
KMH_TO_KT = 0.54


def _default_pg_dsn() -> str:
    if CONFIG_FILE.is_file():
        data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        dsn = (data.get("database") or {}).get("dsn")
        if dsn:
            return str(dsn)
    raise ValueError("Missing --pg-dsn and no [database].dsn found in config.local.toml")


def _psycopg_dsn(dsn: str) -> str:
    if dsn.startswith("postgresql+psycopg://"):
        return "postgresql://" + dsn.removeprefix("postgresql+psycopg://")
    return dsn


def _load_airport_boundary(geojson_path: Path, iata: str) -> Any:
    frame = gpd.read_file(geojson_path)
    if "iata" in frame.columns:
        matched = frame[frame["iata"].astype(str).str.upper() == iata.upper()]
        if matched.empty:
            raise ValueError(f"Airport IATA {iata!r} not found in {geojson_path}")
        frame = matched
    return unary_union(frame.geometry)


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _to_utc(value: Any) -> datetime | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        dt = value.to_pydatetime()
    elif isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BEIJING_TZ)
    return dt.astimezone(timezone.utc)


def _finite_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _single_or_none(values: set[str]) -> str | None:
    return next(iter(values)) if len(values) == 1 else None


def _single_dt_or_none(values: set[datetime]) -> datetime | None:
    return next(iter(values)) if len(values) == 1 else None


def ingest_month_csv(
    csv_path: Path,
    source_month: str,
    pg_dsn: str,
    *,
    airport_name: str = "北京首都",
    airport_iata: str = "PEK",
    boundary_path: Path = DEFAULT_BOUNDARY_PATH,
    max_groundspeed_kt: float = 30.0,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    if not boundary_path.is_file():
        raise FileNotFoundError(f"Airport boundary GeoJSON not found: {boundary_path}")

    boundary = _load_airport_boundary(boundary_path, airport_iata)
    min_lon, min_lat, max_lon, max_lat = boundary.bounds

    # Per-flight accumulators
    flight_obs: dict[tuple[str, str], dict[tuple[datetime, float, float], tuple[Any, ...]]] = (
        defaultdict(dict)
    )
    flight_meta: dict[tuple[str, str], dict[str, set[Any]]] = defaultdict(
        lambda: defaultdict(set)
    )

    raw_rows = 0
    in_boundary_rows = 0
    surface_rows = 0

    use_dtypes = {
        "fnum": "string",
        "org_name": "string",
        "dst_name": "string",
        "r_type": "string",
        "a_num": "string",
        "org_runway": "string",
        "dst_runway": "string",
        "dep_stand_position": "string",
        "arr_stand_position": "string",
        "sche_dep": "string",
        "sche_arr": "string",
        "actual_dep": "string",
        "actual_arr": "string",
        "time_": "string",
    }

    print(f"Streaming raw CSV: {csv_path} (source_month={source_month})")
    for chunk_idx, chunk in enumerate(
        pd.read_csv(
            csv_path,
            chunksize=chunk_size,
            dtype=use_dtypes,
            low_memory=False,
            on_bad_lines="warn",
        ),
        start=1,
    ):
        raw_rows += len(chunk)
        lon = pd.to_numeric(chunk["lon"], errors="coerce").to_numpy(dtype=np.float64)
        lat = pd.to_numeric(chunk["lat"], errors="coerce").to_numpy(dtype=np.float64)

        # Fast bbox pre-filter before exact polygon containment
        bbox_mask = (
            np.isfinite(lon)
            & np.isfinite(lat)
            & (lon >= min_lon)
            & (lon <= max_lon)
            & (lat >= min_lat)
            & (lat <= max_lat)
        )
        if not np.any(bbox_mask):
            continue
        sub = chunk.loc[bbox_mask].copy()
        sub_lon = lon[bbox_mask]
        sub_lat = lat[bbox_mask]

        poly_mask = contains_xy(boundary, sub_lon, sub_lat)
        if not np.any(poly_mask):
            continue
        sub = sub.loc[poly_mask].copy()
        in_boundary_rows += len(sub)

        speed_raw = pd.to_numeric(sub["speed"], errors="coerce")
        gs_kt = speed_raw * KMH_TO_KT
        sub["groundspeed"] = gs_kt
        speed_mask = gs_kt.isna() | (gs_kt <= max_groundspeed_kt)
        sub = sub.loc[speed_mask]
        if sub.empty:
            continue
        surface_rows += len(sub)

        # Normalize columns needed for arrival/departure split
        for row in sub.itertuples(index=False):
            number = _clean_text(getattr(row, "fnum", None))
            if not number:
                continue
            dst_name = _clean_text(getattr(row, "dst_name", None))
            org_name = _clean_text(getattr(row, "org_name", None))

            if dst_name == airport_name:
                movement = "arrival"
                actual_raw = _clean_text(getattr(row, "actual_arr", None))
                stand_raw = _clean_text(getattr(row, "arr_stand_position", None))
            elif org_name == airport_name:
                movement = "departure"
                actual_raw = _clean_text(getattr(row, "actual_dep", None))
                stand_raw = _clean_text(getattr(row, "dep_stand_position", None))
            else:
                continue

            if not actual_raw:
                continue
            actual_local = datetime.fromisoformat(actual_raw)
            flight_id = f"{number}_{actual_local.strftime('%Y%m%d%H%M%S')}"

            ts_utc = _to_utc(getattr(row, "time_", None))
            lon_val = _finite_float(getattr(row, "lon", None))
            lat_val = _finite_float(getattr(row, "lat", None))
            if ts_utc is None or lon_val is None or lat_val is None:
                continue

            key = (movement, flight_id)
            obs_key = (ts_utc, lon_val, lat_val)
            if obs_key not in flight_obs[key]:
                flight_obs[key][obs_key] = (
                    ts_utc,
                    lon_val,
                    lat_val,
                    _finite_float(getattr(row, "height", None)),
                    _finite_float(getattr(row, "groundspeed", None)),
                    _finite_float(getattr(row, "vspeed", None)),
                    _finite_float(getattr(row, "angle", None)),
                    source_month,
                )

            meta = flight_meta[key]
            meta["number"].add(number)
            if a_num := _clean_text(getattr(row, "a_num", None)):
                meta["a_num"].add(a_num.upper())
            if r_type := _clean_text(getattr(row, "r_type", None)):
                meta["r_type"].add(r_type)
            if org_name:
                meta["org_name"].add(org_name)
            if dst_name:
                meta["dst_name"].add(dst_name)
            if org_rwy := _clean_text(getattr(row, "org_runway", None)):
                meta["org_runway"].add(org_rwy)
            if dst_rwy := _clean_text(getattr(row, "dst_runway", None)):
                meta["dst_runway"].add(dst_rwy)
            if stand_raw:
                meta["stand"].add(stand_raw)
            if sche_dep := _to_utc(getattr(row, "sche_dep", None)):
                meta["sche_dep"].add(sche_dep)
            if sche_arr := _to_utc(getattr(row, "sche_arr", None)):
                meta["sche_arr"].add(sche_arr)
            if actual_dep := _to_utc(getattr(row, "actual_dep", None)):
                meta["actual_dep"].add(actual_dep)
            if actual_arr := _to_utc(getattr(row, "actual_arr", None)):
                meta["actual_arr"].add(actual_arr)

        if chunk_idx % 20 == 0:
            print(
                f"  Processed {raw_rows:,} raw rows -> "
                f"{in_boundary_rows:,} in boundary -> {surface_rows:,} surface rows..."
            )

    print(
        f"Finished CSV scan: raw={raw_rows:,}, in_boundary={in_boundary_rows:,}, "
        f"surface={surface_rows:,}, flights={len(flight_obs):,}"
    )
    if not flight_obs:
        print("No valid surface flights found; nothing written to PostgreSQL.")
        return

    # Determine UTC monthly partitions needed
    all_ts = [obs[0] for obs_map in flight_obs.values() for obs in obs_map.values()]
    start_month = min(all_ts).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_month = max(all_ts).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    utc_months: list[datetime] = []
    cursor_m = start_month
    while cursor_m <= end_month:
        utc_months.append(cursor_m)
        cursor_m = (cursor_m + timedelta(days=32)).replace(day=1)

    with psycopg.connect(_psycopg_dsn(pg_dsn)) as pg_con:
        schema_sql = CORE_SCHEMA_SQL.read_text(encoding="utf-8")
        with pg_con.cursor() as cur:
            cur.execute(schema_sql)
            for m_start in utc_months:
                cur.execute("SELECT public.ensure_observations_month_partition(%s)", (m_start,))
        pg_con.commit()

        # Single atomic transaction for this source_month
        with pg_con.cursor() as cur:
            cur.execute(
                "DELETE FROM public.adsb_observations WHERE source_month = %s",
                (source_month,),
            )

            flight_pk_map: dict[tuple[str, str], int] = {}
            arr_flights = 0
            dep_flights = 0
            arr_rows = 0
            dep_rows = 0

            for key in sorted(flight_obs):
                movement, flight_id = key
                obs_list = sorted(flight_obs[key].values(), key=lambda item: item[0])
                meta = flight_meta[key]
                stand_col = "arr_stand_position" if movement == "arrival" else "dep_stand_position"
                runway_col = "dst_runway" if movement == "arrival" else "org_runway"

                conflicts: dict[str, list[str]] = {}
                if len(meta["number"]) > 1:
                    conflicts["number"] = sorted(meta["number"])
                if len(meta["stand"]) > 1:
                    conflicts[stand_col] = sorted(meta["stand"])
                if len(meta[runway_col]) > 1:
                    conflicts[runway_col] = sorted(meta[runway_col])

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
                    ON CONFLICT (movement, flight_id) DO UPDATE SET
                        number = EXCLUDED.number,
                        number_count = EXCLUDED.number_count,
                        a_num = EXCLUDED.a_num,
                        r_type = EXCLUDED.r_type,
                        org_name = EXCLUDED.org_name,
                        dst_name = EXCLUDED.dst_name,
                        org_runway = EXCLUDED.org_runway,
                        dst_runway = EXCLUDED.dst_runway,
                        raw_stand_position = EXCLUDED.raw_stand_position,
                        stand_count = EXCLUDED.stand_count,
                        conflict_fields = EXCLUDED.conflict_fields,
                        sche_dep = EXCLUDED.sche_dep,
                        sche_arr = EXCLUDED.sche_arr,
                        actual_dep = EXCLUDED.actual_dep,
                        actual_arr = EXCLUDED.actual_arr,
                        start_time = EXCLUDED.start_time,
                        end_time = EXCLUDED.end_time,
                        point_count = EXCLUDED.point_count,
                        source_month = EXCLUDED.source_month,
                        updated_at = now()
                    RETURNING flight_pk
                    """,
                    (
                        movement,
                        flight_id,
                        _single_or_none(meta["number"]),
                        len(meta["number"]),
                        _single_or_none(meta["a_num"]),
                        _single_or_none(meta["r_type"]),
                        _single_or_none(meta["org_name"]),
                        _single_or_none(meta["dst_name"]),
                        _single_or_none(meta["org_runway"]),
                        _single_or_none(meta["dst_runway"]),
                        _single_or_none(meta["stand"]),
                        len(meta["stand"]),
                        json.dumps(conflicts, ensure_ascii=False),
                        _single_dt_or_none(meta["sche_dep"]),
                        _single_dt_or_none(meta["sche_arr"]),
                        _single_dt_or_none(meta["actual_dep"]),
                        _single_dt_or_none(meta["actual_arr"]),
                        obs_list[0][0],
                        obs_list[-1][0],
                        len(obs_list),
                        source_month,
                    ),
                ).fetchone()
                assert pk_row is not None
                flight_pk_map[key] = int(pk_row[0])
                if movement == "arrival":
                    arr_flights += 1
                    arr_rows += len(obs_list)
                else:
                    dep_flights += 1
                    dep_rows += len(obs_list)

            with cur.copy(
                "COPY public.adsb_observations ("
                "flight_pk, ts, longitude, latitude, "
                "altitude, groundspeed, vertical_rate, track, source_month"
                ") FROM STDIN"
            ) as copy:
                for key in sorted(flight_obs):
                    fpk = flight_pk_map[key]
                    for obs in sorted(flight_obs[key].values(), key=lambda item: item[0]):
                        copy.write_row((fpk, *obs))

            cur.execute(
                """
                INSERT INTO public.ingest_batches (
                    source_month, source_file, imported_at,
                    arr_rows, arr_flights, dep_rows, dep_flights
                ) VALUES (%s, %s, now(), %s, %s, %s, %s)
                ON CONFLICT (source_month) DO UPDATE SET
                    source_file = EXCLUDED.source_file,
                    imported_at = EXCLUDED.imported_at,
                    arr_rows = EXCLUDED.arr_rows,
                    arr_flights = EXCLUDED.arr_flights,
                    dep_rows = EXCLUDED.dep_rows,
                    dep_flights = EXCLUDED.dep_flights
                """,
                (source_month, str(csv_path), arr_rows, arr_flights, dep_rows, dep_flights),
            )
        pg_con.commit()

    print(
        f"Ingested source_month={source_month}: "
        f"arrival=({arr_flights:,} flights, {arr_rows:,} obs), "
        f"departure=({dep_flights:,} flights, {dep_rows:,} obs)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path, help="Path to raw monthly ADS-B CSV file")
    parser.add_argument("--source-month", required=True, help="Batch month label, e.g. 2024-06")
    parser.add_argument(
        "--pg-dsn",
        type=str,
        default=None,
        help="PostgreSQL DSN (defaults to [database].dsn in config.local.toml)",
    )
    parser.add_argument("--airport-name", default="北京首都")
    parser.add_argument("--airport-iata", default="PEK")
    parser.add_argument("--boundary-path", type=Path, default=DEFAULT_BOUNDARY_PATH)
    parser.add_argument("--max-groundspeed-kt", type=float, default=30.0)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    args = parser.parse_args()
    dsn = args.pg_dsn or _default_pg_dsn()
    ingest_month_csv(
        args.csv_path,
        args.source_month,
        dsn,
        airport_name=args.airport_name,
        airport_iata=args.airport_iata,
        boundary_path=args.boundary_path,
        max_groundspeed_kt=args.max_groundspeed_kt,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()
