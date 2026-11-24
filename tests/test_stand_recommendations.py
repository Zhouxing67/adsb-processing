from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import networkx as nx
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from airport_surface import AirportGraph
from airport_workbench.stand_recommendations import StandGeometryIndex
from flight import Flight
from flight.flight_repository import FlightDatabase


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


def test_historical_stands_count_flights_and_exclude_only_known_occupancy(tmp_path):
    path = tmp_path / "history.duckdb"
    schema = Path(__file__).resolve().parents[1] / "sql/schema/01_core_tables.sql"
    event = datetime(2024, 6, 1, 4, tzinfo=timezone.utc)  # noon in Beijing
    with duckdb.connect(str(path)) as conn:
        conn.execute(schema.read_text(encoding="utf-8"))
        conn.execute("""
            INSERT INTO adsb_dep (flight_id, number, a_num, dep_stand_position, actual_dep) VALUES
            ('1','CA1','T1','A','2024-05-01'), ('1','CA1','T1','A','2024-05-01'),
            ('2','CA1','T2','A','2024-05-03'), ('3','CA1','T3','B','2024-05-04'),
            ('4','CA1','T4','C','2024-05-05'), ('5','CA1','T5','D','2024-01-01'),
            ('6','CA1','T6','E','2024-06-02'), ('7','CA2','T7','F','2024-05-01'),
            ('8','CA2','OCC','B','2024-06-01 12:15'), ('9','CA2','OTHER','C','2024-06-01 13:00');
            INSERT INTO adsb_arr (flight_id, number, a_num, arr_stand_position, actual_arr) VALUES
            ('10','CA2','OCC','B','2024-06-01 11:45'),
            ('11','CA2','DIFFERENT','C','2024-06-01 11:00');
        """)
    stands = FlightDatabase(path).stands
    assert stands.historical_candidates("departure", "target", "CA1", event, None) == [
        ("A", 2, 4), ("C", 1, 4)
    ]
