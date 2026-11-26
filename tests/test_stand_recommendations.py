from datetime import datetime, timedelta, timezone

import networkx as nx
import psycopg
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.stand_recommendations import StandGeometryIndex
from flight import Flight
from flight.flight_repository import FlightDatabase
from tests.flight_database_fixture import reset_test_database


@pytest.mark.parametrize("movement", ["arrival", "departure"])
def test_stand_geometry_uses_event_side_and_distinct_neighbour(movement):
    transform = Transformer.from_crs(32650, 4326, always_xy=True)
    graph = nx.MultiGraph()
    for i, (ref, y) in enumerate([("A", 0), ("A", 1), ("B", 24)]):
        coords = [transform.transform(450000 + x, 4428000 + y) for x in (0, 40)]
        u, v = str(2 * i + 1), str(2 * i + 2)
        graph.add_node(u, pos=coords[0])
        graph.add_node(v, pos=coords[1])
        graph.add_edge(u, v, aeroway="parking_position", ref=ref, geometry=LineString(coords))
    index = StandGeometryIndex(AirportGraph(graph, Proj("EPSG:32650")))
    event = datetime(2024, 6, 1, tzinfo=timezone.utc)

    def candidates(samples):
        rows = []
        for seconds, y in samples:
            lon, lat = transform.transform(450020, 4428000 + y)
            rows.append(dict(flight_id="T", longitude=lon, latitude=lat,
                             timestamp=event + timedelta(seconds=seconds if movement == "departure"
                                                         else -seconds)))
        return index.candidates(Flight(rows, movement=movement), event)

    assert [c.stand for c in candidates([(0, 1)])] == ["A"]
    assert candidates([(0, 12), (1, 12)]) == []
    assert candidates([(-1, 1), (181, 1)]) == []
    assert candidates([(0, 100), (10, 1)]) == []
    assert candidates([(0, 100), (10, 6), (20, 6)])[0].consecutive_points == 2


def test_historical_stands_count_flights_and_exclude_only_known_occupancy():
    dsn = reset_test_database()
    pg_dsn = dsn.replace("postgresql+psycopg://", "postgresql://")
    event = datetime(2024, 6, 1, 4, tzinfo=timezone.utc)  # noon in Beijing
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO public.flights (
                    movement, flight_id, number, a_num, raw_stand_position, actual_dep
                ) VALUES
                ('departure','1','CA1','T1','A', TIMESTAMPTZ '2024-05-01 00:00:00+08'),
                ('departure','2','CA1','T2','A', TIMESTAMPTZ '2024-05-03 00:00:00+08'),
                ('departure','3','CA1','T3','B', TIMESTAMPTZ '2024-05-04 00:00:00+08'),
                ('departure','4','CA1','T4','C', TIMESTAMPTZ '2024-05-05 00:00:00+08'),
                ('departure','5','CA1','T5','D', TIMESTAMPTZ '2024-01-01 00:00:00+08'),
                ('departure','6','CA1','T6','E', TIMESTAMPTZ '2024-06-02 00:00:00+08'),
                ('departure','7','CA2','T7','F', TIMESTAMPTZ '2024-05-01 00:00:00+08'),
                ('departure','8','CA2','OCC','B', TIMESTAMPTZ '2024-06-01 12:15:00+08'),
                ('departure','9','CA2','OTHER','C', TIMESTAMPTZ '2024-06-01 13:00:00+08');
                INSERT INTO public.flights (
                    movement, flight_id, number, a_num, raw_stand_position, actual_arr
                ) VALUES
                ('arrival','10','CA2','OCC','B', TIMESTAMPTZ '2024-06-01 11:45:00+08'),
                ('arrival','11','CA2','DIFFERENT','C', TIMESTAMPTZ '2024-06-01 11:00:00+08');
            """)
        conn.commit()
    database = FlightDatabase(dsn)
    try:
        assert database.stands.historical_candidates("departure", "target", "CA1", event, None) == [
            ("A", 2, 4), ("C", 1, 4)
        ]
    finally:
        database.close()
