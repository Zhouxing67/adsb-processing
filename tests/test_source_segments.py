from pathlib import Path

import networkx as nx
import pandas as pd
import pytest
from pyproj import Proj, Transformer
from shapely.geometry import LineString

from adsb import Flight
from airport_surface import (
    AirportGraph,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
    load_graph,
    save_graph,
    validate_edge_endpoints,
    validate_edge_sources,
)
from airport_workbench import EditorSession
from path_map import MatchConfig, map_flight

PROJECTION = Proj("EPSG:3857")
TO_WGS84 = Transformer.from_proj(PROJECTION, Proj("EPSG:4326"), always_xy=True)


def position(x: float, y: float) -> tuple[float, float]:
    return TO_WGS84.transform(x, y)


def source_edge(source_id: str, node_ids: tuple[int, ...], points: tuple[tuple, ...]) -> SourceEdge:
    return SourceEdge(
        source_id,
        LineString(tuple(position(*point) for point in points)),
        "osm",
        osm_way_id=source_id,
        osm_node_ids=node_ids,
        attributes={"aeroway": "taxiway"},
    )


def add_derived_edge(
    graph: nx.MultiGraph,
    source: SourceEdge,
    u: int,
    v: int,
    start_m: float,
    end_m: float,
    geometry: LineString,
) -> None:
    graph.add_edge(
        u,
        v,
        geometry=geometry,
        first=u,
        last=v,
        source_id=source.source_id,
        source_type="osm",
        source_start_m=start_m,
        source_end_m=end_m,
        aeroway="taxiway",
    )


def crossing_graph() -> AirportGraph:
    positions = {
        1: position(0, 0),
        2: position(10, 0),
        3: position(20, 0),
        4: position(10, -10),
        5: position(10, 10),
    }
    sources = {
        "left": source_edge("left", (1, 2), ((0, 0), (10, 0))),
        "right": source_edge("right", (2, 3), ((10, 0), (20, 0))),
        "vertical": source_edge("vertical", (4, 2, 5), ((10, -10), (10, 0), (10, 10))),
    }
    graph = nx.MultiGraph()
    for node, pos in positions.items():
        graph.add_node(node, pos=pos, source_type="osm")
    add_derived_edge(graph, sources["left"], 1, 2, 0, 10, sources["left"].geometry)
    add_derived_edge(graph, sources["right"], 2, 3, 0, 10, sources["right"].geometry)
    vertical_coords = list(sources["vertical"].geometry.coords)
    add_derived_edge(graph, sources["vertical"], 4, 2, 0, 10, LineString(vertical_coords[:2]))
    add_derived_edge(graph, sources["vertical"], 2, 5, 10, 20, LineString(vertical_coords[1:]))
    source_nodes = {node: SourceNode(node, pos, (node,)) for node, pos in positions.items()}
    return AirportGraph(
        graph,
        PROJECTION,
        source_nodes=source_nodes,
        source_edges=sources,
    )


def near_duplicate_crossing_graph() -> AirportGraph:
    graph = crossing_graph()
    duplicate = 6
    duplicate_position = position(10, 0.04)
    vertical = source_edge(
        "vertical",
        (4, duplicate, 5),
        ((10, -10), (10, 0.04), (10, 10)),
    )
    graph.source_edges["vertical"] = vertical
    graph.source_nodes[duplicate] = SourceNode(duplicate, duplicate_position, (duplicate,))
    graph.graph.add_node(duplicate, pos=duplicate_position, source_type="osm")
    graph.graph.remove_edge(4, 2, 0)
    graph.graph.remove_edge(2, 5, 0)
    coordinates = list(vertical.geometry.coords)
    add_derived_edge(graph.graph, vertical, 4, duplicate, 0, 10.04, LineString(coordinates[:2]))
    add_derived_edge(graph.graph, vertical, duplicate, 5, 10.04, 20, LineString(coordinates[1:]))
    return graph


def pair_id(plan: dict, endpoints: set[str]) -> str:
    return next(
        candidate["pair_id"]
        for candidate in plan["pair_candidates"]
        if set(candidate["endpoints"]) == endpoints
    )


def test_current_single_source_edges_are_normalized_and_round_trip(tmp_path: Path):
    graph = crossing_graph()
    segments = edge_source_segments(graph.graph.edges[1, 2, 0])

    assert segments == (SourceSegment("left", 0, 10),)

    path = tmp_path / "graph.json"
    save_graph(graph, path)
    loaded = load_graph(path)

    assert edge_source_segments(loaded.graph.edges[1, 2, 0]) == segments
    validate_edge_sources(loaded)


def test_degree_four_node_can_be_removed_with_independent_manual_pairings():
    session = EditorSession(crossing_graph())
    original_sources = {
        source_id: source.geometry.wkb
        for source_id, source in session.airport_graph.source_edges.items()
    }
    plan = session.node_deletion_plan(2)
    horizontal = pair_id(plan, {"1", "3"})
    vertical = pair_id(plan, {"4", "5"})

    session.remove_node_with_pairs(2, [horizontal, vertical])

    assert 2 not in session.graph
    assert session.graph.has_edge(1, 3)
    assert session.graph.has_edge(4, 5)
    horizontal_data = next(iter(session.graph.get_edge_data(1, 3).values()))
    vertical_data = next(iter(session.graph.get_edge_data(4, 5).values()))
    assert [segment.source_id for segment in edge_source_segments(horizontal_data)] == [
        "left",
        "right",
    ]
    assert edge_source_segments(vertical_data) == (SourceSegment("vertical", 0, 20),)
    assert horizontal_data["source_type"] == "composite"
    assert {
        source_id: source.geometry.wkb
        for source_id, source in session.airport_graph.source_edges.items()
    } == original_sources
    validate_edge_endpoints(session.airport_graph)
    validate_edge_sources(session.airport_graph)

    session.undo()
    assert 2 in session.graph
    assert session.graph.number_of_edges() == 4


def test_one_half_edge_can_be_reused_by_multiple_manual_pairings():
    graph = crossing_graph()
    graph.graph.remove_edge(2, 5, 0)
    session = EditorSession(graph)
    plan = session.node_deletion_plan(2)

    session.remove_node_with_pairs(
        2,
        [
            pair_id(plan, {"1", "3"}),
            pair_id(plan, {"1", "4"}),
            pair_id(plan, {"3", "4"}),
        ],
    )

    assert 2 not in session.graph
    assert session.graph.has_edge(1, 3)
    assert session.graph.has_edge(1, 4)
    assert session.graph.has_edge(3, 4)
    assert [
        segment.source_id
        for segment in edge_source_segments(next(iter(session.graph[1][4].values())))
    ] == ["left", "vertical"]
    validate_edge_endpoints(session.airport_graph)
    validate_edge_sources(session.airport_graph)


def test_composite_source_chain_survives_save_and_load(tmp_path: Path):
    session = EditorSession(crossing_graph())
    plan = session.node_deletion_plan(2)
    session.remove_node_with_pairs(
        2,
        [pair_id(plan, {"1", "3"}), pair_id(plan, {"4", "5"})],
    )
    path = tmp_path / "simplified.json"

    save_graph(session.airport_graph, path)
    loaded = load_graph(path)

    data = next(iter(loaded.graph.get_edge_data(1, 3).values()))
    assert edge_source_segments(data) == (
        SourceSegment("left", 0, 10),
        SourceSegment("right", 0, 10),
    )
    validate_edge_sources(loaded)


def test_connection_can_be_restored_across_multiple_source_edges():
    graph = crossing_graph()
    graph.graph.remove_node(2)
    session = EditorSession(graph)

    candidates = session.connection_candidates(1, 3)
    candidate = candidates[0]
    session.restore_source_connection(1, 3, candidate["candidate_id"])

    data = next(iter(session.graph[1][3].values()))
    assert [segment.source_id for segment in edge_source_segments(data)] == ["left", "right"]
    assert session.airport_graph.length(data["geometry"]) == pytest.approx(20, abs=1e-3)
    validate_edge_endpoints(session.airport_graph)
    validate_edge_sources(session.airport_graph)


def test_nearby_source_nodes_are_candidates_and_manual_merge_rewires_edges(tmp_path: Path):
    session = EditorSession(near_duplicate_crossing_graph())
    session.airport_graph.parking_position_nodes.add(2)
    session.airport_graph.runway_access_nodes.add(6)
    candidate = next(
        item for item in session.merge_candidates() if set(item["node_ids"]) == {2, 6}
    )
    assert candidate["max_distance_m"] == pytest.approx(0.04, abs=1e-3)

    session.merge_nodes([2, 6], canonical_node=2)

    assert 6 not in session.graph
    assert session.graph.degree(2) == 4
    assert session.airport_graph.node_aliases[6] == 2
    assert session.airport_graph.node_merge_groups[2].member_node_ids == (2, 6)
    assert session.airport_graph.parking_position_nodes == {2}
    assert session.airport_graph.runway_access_nodes == {2}
    assert session.airport_graph.source_edges["vertical"].geometry.wkb == (
        near_duplicate_crossing_graph().source_edges["vertical"].geometry.wkb
    )
    validate_edge_endpoints(session.airport_graph, 2)
    validate_edge_sources(session.airport_graph, 2)

    path = tmp_path / "merged.json"
    save_graph(session.airport_graph, path)
    loaded = load_graph(path)
    assert loaded.node_aliases[6] == 2
    assert loaded.node_merge_groups[2].original_positions[6] == pytest.approx(position(10, 0.04))

    session.undo()
    assert 6 in session.graph
    assert 6 not in session.airport_graph.node_aliases
    assert session.airport_graph.parking_position_nodes == {2}
    assert session.airport_graph.runway_access_nodes == {6}


def test_internal_osm_node_is_excluded_from_merge_candidates_and_rejected():
    graph = crossing_graph()
    positions = {6: position(10.04, 0), 7: position(10.04, -5), 8: position(10.04, 5)}
    source = source_edge("nearby", (7, 6, 8), ((10.04, -5), (10.04, 0), (10.04, 5)))
    graph.source_edges[source.source_id] = source
    graph.source_nodes.update(
        {
            node: SourceNode(node, node_position, (node,))
            for node, node_position in positions.items()
        }
    )
    graph.graph.add_node(7, pos=positions[7], source_type="osm")
    graph.graph.add_node(8, pos=positions[8], source_type="osm")
    add_derived_edge(
        graph.graph,
        source,
        7,
        8,
        0,
        graph.length(source.geometry),
        source.geometry,
    )
    session = EditorSession(graph)

    assert all(6 not in candidate["node_ids"] for candidate in session.merge_candidates())
    with pytest.raises(ValueError, match="不在图中"):
        session.merge_nodes([2, 6], canonical_node=2)


def test_manual_graph_node_can_be_a_merge_candidate_and_rewires_edges():
    graph = crossing_graph()
    manual = -1
    manual_position = position(10, 0.04)
    graph.graph.add_node(manual, pos=manual_position, source="manual")
    graph.graph.add_edge(
        manual,
        5,
        geometry=LineString((manual_position, graph.graph.nodes[5]["pos"])),
        first=manual,
        last=5,
        source_id="manual-spur",
        source_type="manual",
        source_start_m=0,
        source_end_m=9.96,
    )
    graph.source_edges["manual-spur"] = SourceEdge(
        "manual-spur",
        LineString((manual_position, graph.graph.nodes[5]["pos"])),
        "manual",
    )
    session = EditorSession(graph)

    candidate = next(
        item for item in session.merge_candidates() if set(item["node_ids"]) == {2, manual}
    )
    assert any(node["manual"] for node in candidate["nodes"])

    session.merge_nodes([2, manual], canonical_node=2)

    assert manual not in session.graph
    assert session.graph.has_edge(2, 5)
    assert session.airport_graph.node_aliases[manual] == 2
    assert manual in session.airport_graph.node_merge_groups[2].member_node_ids
    validate_edge_endpoints(session.airport_graph)
    validate_edge_sources(session.airport_graph)


def test_manual_snap_moves_graph_node_splits_target_and_preserves_sources(tmp_path: Path):
    graph = crossing_graph()
    positions = {6: position(10.2, -5), 7: position(20, -5)}
    spur = source_edge("spur", (7, 6), ((20, -5), (10.2, -5)))
    graph.source_edges[spur.source_id] = spur
    graph.source_nodes.update(
        {
            node: SourceNode(node, node_position, (node,))
            for node, node_position in positions.items()
        }
    )
    for node, node_position in positions.items():
        graph.graph.add_node(node, pos=node_position, source_type="osm")
    add_derived_edge(graph.graph, spur, 7, 6, 0, graph.length(spur.geometry), spur.geometry)
    session = EditorSession(graph)
    original_sources = {
        source_id: source.geometry.wkb
        for source_id, source in session.airport_graph.source_edges.items()
    }

    preview = session.manual_snap_preview(6, 4, 2, 0)
    session.manual_snap_node_to_edge(6, 4, 2, 0)

    assert preview["distance_m"] == pytest.approx(0.2, abs=1e-3)
    assert session.graph.degree(6) == 3
    assert session.graph.has_edge(4, 6)
    assert session.graph.has_edge(6, 2)
    assert session.airport_graph.node_snap_records[-1].node_id == 6
    assert {
        source_id: source.geometry.wkb
        for source_id, source in session.airport_graph.source_edges.items()
    } == original_sources
    validate_edge_endpoints(session.airport_graph)
    validate_edge_sources(session.airport_graph)

    path = tmp_path / "snapped.json"
    save_graph(session.airport_graph, path)
    loaded = load_graph(path)
    assert loaded.node_snap_records[-1].distance_m == pytest.approx(0.2, abs=1e-3)

    session.undo()
    assert session.graph.nodes[6]["pos"] == pytest.approx(positions[6])
    assert not session.airport_graph.node_snap_records


def test_unpaired_half_edges_require_explicit_discard_confirmation():
    graph = crossing_graph()
    graph.graph.remove_edge(2, 5, 0)
    session = EditorSession(graph)
    plan = session.node_deletion_plan(2)
    selected = next(candidate["pair_id"] for candidate in plan["pair_candidates"])

    with pytest.raises(ValueError, match="未配对半边"):
        session.remove_node_with_pairs(2, [selected])


def test_cross_source_pair_preserves_each_sources_traversal_direction():
    graph = crossing_graph()
    graph.source_edges["right"] = source_edge("right", (3, 2), ((20, 0), (10, 0)))
    right = graph.graph.edges[2, 3, 0]
    right.update(
        geometry=graph.source_edges["right"].geometry,
        first=3,
        last=2,
        source_segments=(SourceSegment("right", 0, 10),),
    )
    graph.graph.remove_edge(4, 2, 0)
    graph.graph.remove_edge(2, 5, 0)
    session = EditorSession(graph)
    plan = session.node_deletion_plan(2)

    session.remove_node_with_pairs(2, [pair_id(plan, {"1", "3"})])

    merged = next(iter(session.graph.get_edge_data(1, 3).values()))
    assert edge_source_segments(merged) == (
        SourceSegment("left", 0, 10),
        SourceSegment("right", 0, 10, reversed=True),
    )
    validate_edge_sources(session.airport_graph)


def test_composite_edge_can_be_split_again_at_an_original_osm_node():
    session = EditorSession(crossing_graph())
    session.graph.remove_edge(4, 2, 0)
    session.graph.remove_edge(2, 5, 0)
    plan = session.node_deletion_plan(2)
    session.remove_node_with_pairs(2, [pair_id(plan, {"1", "3"})])
    key = next(iter(session.graph.get_edge_data(1, 3)))
    split_position = session.airport_graph.get_source_node(2).position

    session.split_source_edge(1, 3, key, *split_position, osm_node_id=2)

    assert 2 in session.graph
    assert session.graph.has_edge(1, 2)
    assert session.graph.has_edge(2, 3)
    assert edge_source_segments(session.graph.edges[1, 2, 0]) == (SourceSegment("left", 0, 10),)
    assert edge_source_segments(session.graph.edges[2, 3, 0]) == (SourceSegment("right", 0, 10),)
    validate_edge_sources(session.airport_graph)


def test_hmm_geometry_and_length_remain_stable_after_safe_manual_simplification():
    graph = crossing_graph()
    graph.graph.remove_edge(4, 2, 0)
    graph.graph.remove_edge(2, 5, 0)
    flight = Flight(
        pd.DataFrame(
            {
                "flight_id": ["test"] * 6,
                "timestamp": pd.date_range("2026-01-01", periods=6, freq="1s"),
                "longitude": [position(x, 0)[0] for x in (1, 5, 9, 11, 15, 19)],
                "latitude": [position(x, 0)[1] for x in (1, 5, 9, 11, 15, 19)],
            }
        )
    )
    config = MatchConfig(search_radius=5, max_candidates=4, gps_sigma=2, transition_beta=5)
    before = map_flight(graph, flight, config)

    session = EditorSession(graph)
    plan = session.node_deletion_plan(2)
    session.remove_node_with_pairs(2, [pair_id(plan, {"1", "3"})])
    after = map_flight(session.airport_graph, flight, config)

    assert after.total_length == pytest.approx(before.total_length, abs=1e-6)
    assert (
        session.airport_graph.project_shape(after.geometry).hausdorff_distance(
            graph.project_shape(before.geometry)
        )
        < 1e-6
    )
    assert len(after) < len(before)
