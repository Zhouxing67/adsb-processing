"""Build flight trajectory quality metrics and whitelist tables in DuckDB."""

from __future__ import annotations

import argparse
from dataclasses import dataclass

from shapely.geometry import Point

from airport_surface import AirportGraph, load_graph
from config import load_settings
from flight.flight_catalogue_repository import STAND_COLUMNS
from flight.flight_repository import open_flight_database

# Local meter scale around ZBAA (~40.08 deg N)
LON_M = 85200.0
LAT_M = 111320.0
RUNWAY_SAMPLE_STEP_M = 50.0


@dataclass(frozen=True, slots=True)
class QualityThresholds:
    min_points: int = 15
    max_step_m: float = 500.0
    max_avg_step_m: float = 150.0
    max_stand_dist_m: float = 350.0
    max_runway_dist_m: float = 150.0


def _build_graph_distance_helpers(ag: AirportGraph):
    stand_lines: dict[str, list] = {}
    for stand_ref, edges in ag.stand_to_edges.items():
        stand_lines[stand_ref] = [
            ag.project_shape(ag.oriented_edge_geometry(u, v, key)) for u, v, key in edges
        ]

    runway_lines_by_ref: dict[str, list] = {}
    all_runway_lines: list = []
    for u, v, key, data in ag.graph.edges(keys=True, data=True):
        if data.get("aeroway") != "runway":
            continue
        projected = ag.project_shape(ag.oriented_edge_geometry(u, v, key))
        all_runway_lines.append(projected)
        for ref in str(data.get("ref") or "").upper().split("/"):
            clean = ref.strip()
            if clean:
                runway_lines_by_ref.setdefault(clean, []).append(projected)

    def stand_distance(stand_ref: str | None, lon: float, lat: float) -> float | None:
        if not stand_ref:
            return None
        lines = stand_lines.get(stand_ref)
        if not lines:
            return None
        pt = Point(*ag.project.transform(lon, lat))
        return min(pt.distance(line) for line in lines)

    def runway_distance(runway_ref: str | None, lon: float, lat: float) -> float | None:
        lines = runway_lines_by_ref.get(runway_ref.upper()) if runway_ref else all_runway_lines
        if not lines:
            return None
        pt = Point(*ag.project.transform(lon, lat))
        return min(pt.distance(line) for line in lines)

    return stand_distance, runway_distance


def _resolve_prefix(conn) -> tuple[str, dict[str, str]]:
    tables = conn.execute("SHOW ALL TABLES").fetchall()
    resolved: dict[str, str] = {}
    prefix = "main"
    for movement, (default_name, _) in STAND_COLUMNS.items():
        suffix = "_dep" if movement == "departure" else "_arr"
        match = next((t for t in tables if t[2] == default_name), None) or next(
            (t for t in tables if t[2].endswith(suffix) and t[2].startswith("adsb")),
            None,
        )
        if match is None:
            raise RuntimeError(f"Could not find ADS-B table for {movement} in {tables}")
        prefix = f"{match[0]}.{match[1]}"
        resolved[movement] = f"{match[0]}.{match[1]}.{match[2]}"
    return prefix, resolved


def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.4f}"


def _insert_rows(conn, table: str, rows: list[tuple], batch_size: int = 500) -> None:
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        values_sql = ", ".join(
            "(" + ", ".join(_sql_literal(v) for v in row) + ")" for row in chunk
        )
        conn.execute(f"INSERT INTO {table} VALUES {values_sql}")


def _fetch_movement_stats(conn, table: str, stand_col: str, runway_col: str) -> list[tuple]:
    return conn.execute(
        f"""
        WITH ordered AS (
            SELECT
                flight_id,
                NULLIF(trim(CAST({stand_col} AS VARCHAR)), '') AS stand_val,
                NULLIF(trim(CAST({runway_col} AS VARCHAR)), '') AS runway_val,
                longitude,
                latitude,
                timestamp,
                LAG(longitude) OVER (PARTITION BY flight_id ORDER BY timestamp) AS prev_lon,
                LAG(latitude)  OVER (PARTITION BY flight_id ORDER BY timestamp) AS prev_lat
            FROM {table}
            WHERE flight_id IS NOT NULL AND trim(flight_id) <> ''
        ),
        steps AS (
            SELECT
                flight_id,
                stand_val,
                runway_val,
                longitude,
                latitude,
                timestamp,
                CASE
                    WHEN prev_lon IS NULL THEN NULL
                    ELSE sqrt(
                        pow((longitude - prev_lon) * {LON_M}, 2)
                        + pow((latitude - prev_lat) * {LAT_M}, 2)
                    )
                END AS step_m
            FROM ordered
        )
        SELECT
            flight_id,
            COUNT(DISTINCT stand_val) AS stand_distinct,
            COUNT(DISTINCT runway_val) AS runway_distinct,
            CASE WHEN COUNT(DISTINCT stand_val) = 1 THEN MAX(stand_val) END AS stand_ref,
            CASE WHEN COUNT(DISTINCT runway_val) = 1 THEN MAX(runway_val) END AS runway_ref,
            COUNT(*) AS point_count,
            COALESCE(MAX(step_m), 0.0) AS max_step_m,
            CASE
                WHEN COUNT(*) > 1 THEN COALESCE(SUM(step_m), 0.0) / (COUNT(*) - 1)
                ELSE 0.0
            END AS avg_step_m,
            COALESCE(SUM(step_m), 0.0) AS total_track_m,
            arg_min(longitude, timestamp) AS first_lon,
            arg_min(latitude, timestamp) AS first_lat,
            arg_max(longitude, timestamp) AS last_lon,
            arg_max(latitude, timestamp) AS last_lat
        FROM steps
        GROUP BY flight_id
        """
    ).fetchall()


def build_whitelist(thresholds: QualityThresholds) -> None:
    settings = load_settings()
    ag = load_graph(settings.graph_path)
    stand_distance, runway_distance = _build_graph_distance_helpers(ag)
    db = open_flight_database(settings.database, read_only=False)

    with db.observations._database.connection(write=True) as conn:
        prefix, source_tables = _resolve_prefix(conn)
        metrics_tbl = f"{prefix}.flight_quality_metrics"
        whitelist_tbl = f"{prefix}.flight_whitelist"

        # Clean up temporary ref tables if created by an earlier failed run
        conn.execute(f"DROP TABLE IF EXISTS {prefix}.graph_stand_refs")
        conn.execute(f"DROP TABLE IF EXISTS {prefix}.graph_runway_refs")

        metrics_rows: list[tuple] = []
        whitelist_rows: list[tuple] = []

        for movement, stand_col, runway_col in (
            ("departure", "dep_stand_position", "org_runway"),
            ("arrival", "arr_stand_position", "dst_runway"),
        ):
            raw_rows = _fetch_movement_stats(conn, source_tables[movement], stand_col, runway_col)
            for (
                flight_id,
                stand_distinct,
                runway_distinct,
                stand_ref,
                runway_ref,
                point_count,
                max_step_m,
                avg_step_m,
                total_track_m,
                first_lon,
                first_lat,
                last_lon,
                last_lat,
            ) in raw_rows:
                if movement == "departure":
                    s_dist = stand_distance(stand_ref, first_lon, first_lat)
                    r_dist = runway_distance(runway_ref, last_lon, last_lat)
                else:
                    s_dist = stand_distance(stand_ref, last_lon, last_lat)
                    r_dist = runway_distance(runway_ref, first_lon, first_lat)

                metrics_rows.append(
                    (
                        movement,
                        flight_id,
                        stand_ref,
                        runway_ref,
                        int(stand_distinct),
                        int(point_count),
                        float(max_step_m),
                        float(avg_step_m),
                        float(total_track_m),
                        s_dist,
                        r_dist,
                    )
                )
                if (
                    stand_distinct == 1
                    and runway_distinct <= 1
                    and stand_ref is not None
                    and s_dist is not None
                    and s_dist <= thresholds.max_stand_dist_m
                    and r_dist is not None
                    and r_dist <= thresholds.max_runway_dist_m
                    and point_count >= thresholds.min_points
                    and max_step_m <= thresholds.max_step_m
                    and avg_step_m <= thresholds.max_avg_step_m
                ):
                    whitelist_rows.append((movement, flight_id, stand_ref, runway_ref))

        conn.execute(f"DROP TABLE IF EXISTS {metrics_tbl}")
        conn.execute(
            f"""
            CREATE TABLE {metrics_tbl} (
                movement VARCHAR,
                flight_id VARCHAR,
                stand_ref VARCHAR,
                runway_ref VARCHAR,
                stand_distinct INTEGER,
                point_count INTEGER,
                max_step_m DOUBLE,
                avg_step_m DOUBLE,
                total_track_m DOUBLE,
                stand_dist_m DOUBLE,
                runway_dist_m DOUBLE
            )
            """
        )
        _insert_rows(conn, metrics_tbl, metrics_rows)

        conn.execute(f"DROP TABLE IF EXISTS {whitelist_tbl}")
        conn.execute(
            f"""
            CREATE TABLE {whitelist_tbl} (
                movement VARCHAR,
                flight_id VARCHAR,
                stand_ref VARCHAR,
                runway_ref VARCHAR
            )
            """
        )
        _insert_rows(conn, whitelist_tbl, whitelist_rows)

        summary = conn.execute(
            f"""
            SELECT
                movement,
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE stand_distinct = 1) AS valid_stand,
                quantile_cont(stand_dist_m, [0.50, 0.75, 0.90, 0.95])
                    FILTER (WHERE stand_dist_m IS NOT NULL) AS stand_q,
                quantile_cont(runway_dist_m, [0.50, 0.75, 0.90, 0.95])
                    FILTER (WHERE runway_dist_m IS NOT NULL) AS rwy_q
            FROM {metrics_tbl}
            GROUP BY movement
            ORDER BY movement
            """
        ).fetchall()
        wl_counts = dict(
            conn.execute(
                f"SELECT movement, COUNT(*) FROM {whitelist_tbl} GROUP BY movement"
            ).fetchall()
        )
        print(f"Created tables under {prefix}:")
        print(f"  - {metrics_tbl} ({len(metrics_rows)} rows)")
        print(f"  - {whitelist_tbl} ({len(whitelist_rows)} rows)")
        for movement, total, valid_stand, stand_q, rwy_q in summary:
            wl = wl_counts.get(movement, 0)
            pct = 100.0 * wl / total if total else 0.0
            print(
                f"[{movement}] total={total}, valid_stand={valid_stand}, "
                f"whitelisted={wl} ({pct:.1f}%)"
            )
            print("  stand_dist_m  [P50,P75,P90,P95]:", [round(x, 1) for x in stand_q])
            print("  runway_dist_m [P50,P75,P90,P95]:", [round(x, 1) for x in rwy_q])


def main() -> None:
    parser = argparse.ArgumentParser(description="Build DuckDB flight quality whitelist tables")
    parser.add_argument("--min-points", type=int, default=15)
    parser.add_argument("--max-step-m", type=float, default=500.0)
    parser.add_argument("--max-avg-step-m", type=float, default=150.0)
    parser.add_argument("--max-stand-dist-m", type=float, default=350.0)
    parser.add_argument("--max-runway-dist-m", type=float, default=150.0)
    args = parser.parse_args()
    build_whitelist(
        QualityThresholds(
            min_points=args.min_points,
            max_step_m=args.max_step_m,
            max_avg_step_m=args.max_avg_step_m,
            max_stand_dist_m=args.max_stand_dist_m,
            max_runway_dist_m=args.max_runway_dist_m,
        )
    )


if __name__ == "__main__":
    main()
