"""Stateless toy-network algorithm demonstration service backed by real path_map."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from math import inf, isfinite
from typing import Any, Literal, Sequence

import networkx as nx
from pyproj import Proj, Transformer
from shapely.geometry import LineString, Point

from airport_surface import AirportGraph
from flight import Flight
from path_map import MapMatchingError, MatchConfig, Matcher
from path_map.candidates import Candidate
from path_map.edge_dtw import (
    REVERSAL_PENALTY_M,
    ArrivalTransitionStep,
    DepartureState,
    DepartureTransitionStep,
    directed_edge_distances,
    observation_log_score,
)
from path_map.path import DirectedEdge, DirectedEdgeId, EdgeId
from path_map.recovery import project_observations, trim_runway_edges
from path_map.router import ANGLE_COMPARISON_TOLERANCE_DEG, DirectedNetworkRouter

from .api_models import (
    DemoDecodeAttempt,
    DemoDualGraph,
    DemoDualTransition,
    DemoFinalResult,
    DemoGraph,
    DemoGraphBounds,
    DemoGraphEdge,
    DemoGraphNode,
    DemoMatchConfig,
    DemoObservationCandidate,
    DemoObservationTrace,
    DemoPointInput,
    DemoScenarioSummary,
    DemoTraceResponse,
    DemoTrellisLayer,
    DemoTrellisState,
)

_UTM_CRS = "EPSG:32650"
_ORIGIN_X = 465_000.0
_ORIGIN_Y = 4_436_000.0
_TO_WGS84 = Transformer.from_crs(_UTM_CRS, "EPSG:4326", always_xy=True)


@dataclass(frozen=True, slots=True)
class _DemoScenarioSpec:
    id: str
    title: str
    description: str
    movement: Literal["arrival", "departure"]
    stand_ref: str
    runway_ref: str
    default_observations: tuple[tuple[float, float], ...]
    default_config: MatchConfig


_TOY_NODES: tuple[tuple[str, str, float, float], ...] = (
    ("1", "TW", 30.0, 145.0),
    ("2", "T0", 120.0, 145.0),
    ("3", "T1", 230.0, 145.0),
    ("4", "T2", 390.0, 145.0),
    ("5", "B1", 255.0, 220.0),
    ("6", "B2", 365.0, 220.0),
    ("7", "P1", 120.0, 265.0),
    ("8", "P2", 255.0, 295.0),
    ("9", "R0", 40.0, 45.0),
    ("10", "R1", 265.0, 45.0),
    ("11", "R2", 430.0, 45.0),
    ("12", "R3", 530.0, 45.0),
)

_NODE_ID_TO_LABEL: dict[str, str] = {node_id: label for node_id, label, _, _ in _TOY_NODES}
_LABEL_TO_NODE_ID: dict[str, str] = {label: node_id for node_id, label, _, _ in _TOY_NODES}

_TOY_EDGES: tuple[tuple[str, str, str, str | None], ...] = (
    ("R0", "R1", "runway", "01/19"),
    ("R1", "R2", "runway", "01/19"),
    ("R2", "R3", "runway", "01/19"),
    ("R1", "T1", "taxiway", "A1"),
    ("R2", "T2", "taxiway", "A2"),
    ("TW", "T0", "taxiway", "A"),
    ("T0", "T1", "taxiway", "A"),
    ("T1", "T2", "taxiway", "A"),
    ("T1", "B1", "taxiway", "B"),
    ("B1", "B2", "taxiway", "B"),
    ("B2", "T2", "taxiway", "B"),
    ("T0", "P1", "parking_position", "S1"),
    ("B1", "P2", "parking_position", "S2"),
)

_SCENARIOS: tuple[_DemoScenarioSpec, ...] = (
    _DemoScenarioSpec(
        id="arrival_basic",
        title="进港标准匹配与转角剪枝",
        description=(
            "5 个带噪观测点从跑道 01 脱离滑向机位 S1，第 3 点偏向平行滑行道 B，"
            "演示候选召回、130° 转角剪枝、Viterbi 解码与跑道裁剪。"
        ),
        movement="arrival",
        stand_ref="S1",
        runway_ref="01",
        default_observations=(
            (475.0, 48.0),
            (408.0, 98.0),
            (310.0, 198.0),
            (180.0, 150.0),
            (124.0, 232.0),
        ),
        default_config=MatchConfig(
            candidate_radius=120.0,
            max_candidates=6,
            gps_sigma=15.0,
            length_scale_m=50.0,
            max_transition_turn_angle_deg=130.0,
            turn_tangent_sample_m=2.0,
            max_pushback_radius_m=250.0,
        ),
    ),
    _DemoScenarioSpec(
        id="departure_pushback",
        title="离港推机反向与乘积状态",
        description=(
            "飞机从机位 S1 先向西推出至尽头滑行道 TW，再在推机半径内原地反向"
            "正向滑向跑道 01，演示 DepartureState 乘积状态与反向惩罚。"
        ),
        movement="departure",
        stand_ref="S1",
        runway_ref="01",
        default_observations=(
            (122.0, 245.0),
            (118.0, 165.0),
            (62.0, 148.0),
            (178.0, 143.0),
            (248.0, 95.0),
            (340.0, 47.0),
        ),
        default_config=MatchConfig(
            candidate_radius=120.0,
            max_candidates=6,
            gps_sigma=15.0,
            length_scale_m=50.0,
            max_transition_turn_angle_deg=130.0,
            turn_tangent_sample_m=2.0,
            max_pushback_radius_m=200.0,
        ),
    ),
    _DemoScenarioSpec(
        id="phase2_fallback",
        title="Phase 1 失败 → Phase 2 OD 先验回退",
        description=(
            "离港轨迹缺失机位 S1 附近前段观测点，Phase 1 纯轨迹端点校验失败，"
            "自动触发 Phase 2 注入零发射 OD 边界层补齐完整路径。"
        ),
        movement="departure",
        stand_ref="S1",
        runway_ref="01",
        default_observations=(
            (248.0, 148.0),
            (320.0, 146.0),
            (408.0, 98.0),
            (470.0, 47.0),
        ),
        default_config=MatchConfig(
            candidate_radius=120.0,
            max_candidates=6,
            gps_sigma=15.0,
            length_scale_m=50.0,
            max_transition_turn_angle_deg=130.0,
            turn_tangent_sample_m=2.0,
            max_pushback_radius_m=250.0,
        ),
    ),
)

_SCENARIO_MAP: dict[str, _DemoScenarioSpec] = {spec.id: spec for spec in _SCENARIOS}


def _local_to_lonlat(x: float, y: float) -> tuple[float, float]:
    lon, lat = _TO_WGS84.transform(_ORIGIN_X + x, _ORIGIN_Y + y)
    return float(lon), float(lat)


def _projected_to_local(point: Point) -> tuple[float, float]:
    return round(float(point.x - _ORIGIN_X), 2), round(float(point.y - _ORIGIN_Y), 2)


def _node_label(node_id: Any) -> str:
    text = str(node_id)
    return _NODE_ID_TO_LABEL.get(text, text)


def _format_edge_id(edge: DirectedEdgeId | EdgeId) -> str:
    return f"{_node_label(edge[0])}→{_node_label(edge[1])}#{edge[2]}"


def _format_undirected_edge_id(u: Any, v: Any, key: int) -> str:
    return f"{_node_label(u)}-{_node_label(v)}#{key}"


@lru_cache(maxsize=1)
def _toy_airport_graph() -> AirportGraph:
    graph = nx.MultiGraph()
    node_lonlat: dict[str, tuple[float, float]] = {}
    for node_id, _label, x, y in _TOY_NODES:
        lon, lat = _local_to_lonlat(x, y)
        node_lonlat[node_id] = (lon, lat)
        graph.add_node(node_id, pos=(lon, lat))
    for u_label, v_label, aeroway, ref in _TOY_EDGES:
        u = _LABEL_TO_NODE_ID[u_label]
        v = _LABEL_TO_NODE_ID[v_label]
        attrs: dict[str, Any] = {
            "geometry": LineString([node_lonlat[u], node_lonlat[v]]),
            "aeroway": aeroway,
        }
        if ref is not None:
            attrs["ref"] = ref
        graph.add_edge(u, v, **attrs)
    return AirportGraph(graph, Proj(_UTM_CRS))


def _config_to_dto(config: MatchConfig) -> DemoMatchConfig:
    return DemoMatchConfig(
        candidate_radius=config.candidate_radius,
        max_candidates=config.max_candidates,
        gps_sigma=config.gps_sigma,
        length_scale_m=config.length_scale_m,
        max_transition_turn_angle_deg=config.max_transition_turn_angle_deg,
        turn_tangent_sample_m=config.turn_tangent_sample_m,
        max_pushback_radius_m=config.max_pushback_radius_m,
    )


def _dto_to_config(dto: DemoMatchConfig | None, default: MatchConfig) -> MatchConfig:
    if dto is None:
        return default
    return MatchConfig(
        candidate_radius=dto.candidate_radius,
        max_candidates=dto.max_candidates,
        gps_sigma=dto.gps_sigma,
        length_scale_m=dto.length_scale_m,
        max_transition_turn_angle_deg=dto.max_transition_turn_angle_deg,
        turn_tangent_sample_m=dto.turn_tangent_sample_m,
        max_pushback_radius_m=dto.max_pushback_radius_m,
    )


def _scenario_summary(spec: _DemoScenarioSpec) -> DemoScenarioSummary:
    return DemoScenarioSummary(
        id=spec.id,
        title=spec.title,
        description=spec.description,
        movement=spec.movement,
        stand_ref=spec.stand_ref,
        runway_ref=spec.runway_ref,
        default_observations=[DemoPointInput(x=x, y=y) for x, y in spec.default_observations],
        default_config=_config_to_dto(spec.default_config),
    )


def list_demo_scenarios() -> list[DemoScenarioSummary]:
    return [_scenario_summary(spec) for spec in _SCENARIOS]


def _build_flight(
    spec: _DemoScenarioSpec,
    points: Sequence[tuple[float, float]],
) -> Flight:
    if not points:
        raise ValueError("观测点列表不能为空")
    start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    rows: list[dict[str, Any]] = []
    for index, (x, y) in enumerate(points):
        if not (isfinite(x) and isfinite(y)):
            raise ValueError("观测点坐标必须是有限数值")
        lon, lat = _local_to_lonlat(x, y)
        row: dict[str, Any] = {
            "flight_id": f"DEMO_{spec.id}",
            "timestamp": start + timedelta(seconds=index * 10),
            "longitude": lon,
            "latitude": lat,
        }
        if spec.movement == "departure":
            row["dep_stand_position"] = spec.stand_ref
            row["org_runway"] = spec.runway_ref
        else:
            row["arr_stand_position"] = spec.stand_ref
            row["dst_runway"] = spec.runway_ref
        rows.append(row)
    return Flight(rows, movement=spec.movement)


def _serialize_graph(airport_graph: AirportGraph) -> DemoGraph:
    runway_interfaces = set(airport_graph.runway_interfaces)
    node_roles: dict[str, Literal["stand", "taxiway", "runway_interface", "runway"]] = {}
    for u, v, _, data in airport_graph.graph.edges(keys=True, data=True):
        aeroway = str(data.get("aeroway") or "")
        for node in (str(u), str(v)):
            if node in runway_interfaces:
                node_roles[node] = "runway_interface"
            elif aeroway == "parking_position" and airport_graph.graph.degree(node) == 1:
                node_roles[node] = "stand"
            elif aeroway == "runway" and node_roles.get(node) is None:
                node_roles[node] = "runway"
            elif node_roles.get(node) is None:
                node_roles[node] = "taxiway"

    nodes: list[DemoGraphNode] = []
    xs: list[float] = []
    ys: list[float] = []
    for node_id, label, x, y in _TOY_NODES:
        xs.append(x)
        ys.append(y)
        nodes.append(
            DemoGraphNode(
                id=label,
                x=x,
                y=y,
                role=node_roles.get(node_id, "taxiway"),
            )
        )

    edges: list[DemoGraphEdge] = []
    for u, v, key, data in airport_graph.graph.edges(keys=True, data=True):
        projected = airport_graph.project_shape(airport_graph.oriented_edge_geometry(u, v, key))
        coords = [_projected_to_local(Point(cx, cy)) for cx, cy in projected.coords]
        edges.append(
            DemoGraphEdge(
                id=_format_undirected_edge_id(u, v, int(key)),
                u=_node_label(u),
                v=_node_label(v),
                key=int(key),
                aeroway=str(data.get("aeroway") or "taxiway"),
                ref=str(data["ref"]) if data.get("ref") is not None else None,
                length_m=round(float(projected.length), 2),
                coords=coords,
            )
        )

    return DemoGraph(
        bounds=DemoGraphBounds(
            min_x=min(xs) - 30.0,
            min_y=min(ys) - 30.0,
            max_x=max(xs) + 30.0,
            max_y=max(ys) + 30.0,
        ),
        nodes=nodes,
        edges=edges,
    )


def _serialize_dual_graph(router: DirectedNetworkRouter) -> DemoDualGraph:
    transitions: list[DemoDualTransition] = []
    allowed_count = 0
    pruned_count = 0
    for edge in sorted(router.lengths):
        end = edge[1]
        for following in sorted(router.outgoing.get(end, ())):
            angle = router.turn_angle(edge, following)
            allowed = angle <= router.max_turn_angle_deg + ANGLE_COMPARISON_TOLERANCE_DEG
            if allowed:
                allowed_count += 1
            else:
                pruned_count += 1
            transitions.append(
                DemoDualTransition(
                    from_edge=_format_edge_id(edge),
                    to_edge=_format_edge_id(following),
                    via_node=_node_label(end),
                    turn_angle_deg=round(angle, 1),
                    allowed=allowed,
                    length_m=round(router.lengths[following], 2),
                )
            )
    return DemoDualGraph(
        directed_edge_count=len(router.lengths),
        allowed_transition_count=allowed_count,
        pruned_transition_count=pruned_count,
        transitions=transitions,
    )


def _trace_decode(
    observation_candidates: Sequence[Sequence[Candidate]],
    observations: Sequence[Point],
    retained_indices: Sequence[int],
    router: DirectedNetworkRouter,
    config: MatchConfig,
    *,
    is_departure: bool,
    start_edges: frozenset[DirectedEdgeId] | None = None,
    end_edges: frozenset[DirectedEdgeId] | None = None,
    reversal_origin: Point | None = None,
) -> tuple[DemoDecodeAttempt, list[DirectedEdge]]:
    emission_layers: list[dict[DirectedEdgeId, float]] = []
    layer_points: list[Point] = []
    layer_meta: list[
        tuple[Literal["start_boundary", "observation", "end_boundary"], int | None, str]
    ] = []

    if start_edges is not None:
        valid_start = {edge: 0.0 for edge in sorted(start_edges) if edge in router.lengths}
        if not valid_start:
            return (
                DemoDecodeAttempt(
                    status="no_path",
                    rejection_reason="无可用的起点边界边",
                    start_edges=sorted(_format_edge_id(e) for e in start_edges),
                    end_edges=sorted(_format_edge_id(e) for e in (end_edges or ())),
                ),
                [],
            )
        emission_layers.append(valid_start)
        layer_points.append(observations[0])
        layer_meta.append(("start_boundary", None, "起点 OD"))

    for obs_idx, point, candidates in zip(retained_indices, observations, observation_candidates):
        edge_dists = directed_edge_distances(candidates, router)
        if not edge_dists:
            return DemoDecodeAttempt(
                status="no_path", rejection_reason=f"观测点 #{obs_idx + 1} 无可用有向边"
            ), []
        emission_layers.append(
            {
                edge: observation_log_score(dist, config.gps_sigma)
                for edge, dist in edge_dists.items()
            }
        )
        layer_points.append(point)
        layer_meta.append(("observation", obs_idx, f"P{obs_idx + 1}"))

    if end_edges is not None:
        valid_end = {edge: 0.0 for edge in sorted(end_edges) if edge in router.lengths}
        if not valid_end:
            return (
                DemoDecodeAttempt(
                    status="no_path",
                    rejection_reason="无可用的终点边界边",
                    start_edges=sorted(_format_edge_id(e) for e in (start_edges or ())),
                    end_edges=sorted(_format_edge_id(e) for e in end_edges),
                ),
                [],
            )
        emission_layers.append(valid_end)
        layer_points.append(observations[-1])
        layer_meta.append(("end_boundary", None, "终点 OD"))

    origin = reversal_origin if reversal_origin is not None else observations[0]
    origin_local = _projected_to_local(origin) if is_departure else None

    if not is_departure:
        state_layers_arr: list[list[DirectedEdgeId]] = [
            list(layer.keys()) for layer in emission_layers
        ]
        emission_values = [list(layer.values()) for layer in emission_layers]
        step = ArrivalTransitionStep(router=router, length_scale_m=config.length_scale_m)
        scores_per_layer: list[list[float]] = [list(emission_values[0])]
        backrefs: list[list[int]] = []
        for prev_layer, curr_layer, curr_emissions in zip(
            state_layers_arr, state_layers_arr[1:], emission_values[1:]
        ):
            best_prev, refs = step.best_predecessors(prev_layer, scores_per_layer[-1], curr_layer)
            curr_scores = [
                prev + em if prev > -inf else -inf for prev, em in zip(best_prev, curr_emissions)
            ]
            scores_per_layer.append(curr_scores)
            backrefs.append(refs)

        last_scores = scores_per_layer[-1]
        best_index = (
            max(range(len(last_scores)), key=last_scores.__getitem__) if last_scores else -1
        )
        if best_index < 0 or last_scores[best_index] == -inf:
            trellis = _build_arrival_trellis(
                state_layers_arr,
                emission_values,
                scores_per_layer,
                backrefs,
                layer_meta,
                router,
                config,
                None,
            )
            return (
                DemoDecodeAttempt(
                    status="no_path",
                    rejection_reason="无满足转角约束的合法路径",
                    start_edges=sorted(_format_edge_id(e) for e in (start_edges or ())),
                    end_edges=sorted(_format_edge_id(e) for e in (end_edges or ())),
                    layers=trellis,
                ),
                [],
            )

        opt_indices = [best_index]
        for refs in reversed(backrefs):
            best_index = refs[best_index]
            opt_indices.append(best_index)
        opt_indices.reverse()

        chosen_edges = [layer[idx] for layer, idx in zip(state_layers_arr, opt_indices)]
        output: list[DirectedEdge] = [DirectedEdge(*chosen_edges[0])]
        for prev_edge, curr_edge in zip(chosen_edges, chosen_edges[1:]):
            if prev_edge == curr_edge:
                continue
            tail = router.route_tail(prev_edge, curr_edge)
            assert tail is not None
            output.extend(tail)

        trellis = _build_arrival_trellis(
            state_layers_arr,
            emission_values,
            scores_per_layer,
            backrefs,
            layer_meta,
            router,
            config,
            opt_indices,
        )
        return (
            DemoDecodeAttempt(
                status="accepted",
                start_edges=sorted(_format_edge_id(e) for e in (start_edges or ())),
                end_edges=sorted(_format_edge_id(e) for e in (end_edges or ())),
                layers=trellis,
                decoded_edges=[_format_edge_id(e.id) for e in output],
            ),
            output,
        )

    # Departure product-state decoding
    state_layers_dep: list[list[DepartureState]] = [
        [DepartureState(edge, reversed_used=False) for edge in emission_layers[0]]
    ]
    emission_values = [list(emission_layers[0].values())]
    for layer in emission_layers[1:]:
        state_layers_dep.append(
            [DepartureState(edge, reversed_used=False) for edge in layer]
            + [DepartureState(edge, reversed_used=True) for edge in layer]
        )
        vals = list(layer.values())
        emission_values.append(vals + vals)

    allow_flags = [False] + [
        layer_points[step_idx - 1].distance(origin) <= config.max_pushback_radius_m
        for step_idx in range(1, len(state_layers_dep))
    ]
    step_scorers = [
        DepartureTransitionStep(
            router=router,
            length_scale_m=config.length_scale_m,
            allow_reversal=allow_flags[step_idx],
        )
        for step_idx in range(1, len(state_layers_dep))
    ]

    scores_per_layer = [list(emission_values[0])]
    backrefs = []
    for prev_layer, curr_layer, curr_emissions, scorer in zip(
        state_layers_dep, state_layers_dep[1:], emission_values[1:], step_scorers
    ):
        best_prev, refs = scorer.best_predecessors(prev_layer, scores_per_layer[-1], curr_layer)
        curr_scores = [
            prev + em if prev > -inf else -inf for prev, em in zip(best_prev, curr_emissions)
        ]
        scores_per_layer.append(curr_scores)
        backrefs.append(refs)

    last_scores = scores_per_layer[-1]
    best_index = max(range(len(last_scores)), key=last_scores.__getitem__) if last_scores else -1
    if best_index < 0 or last_scores[best_index] == -inf:
        trellis = _build_departure_trellis(
            state_layers_dep,
            emission_values,
            scores_per_layer,
            backrefs,
            allow_flags,
            layer_meta,
            router,
            config,
            None,
        )
        return (
            DemoDecodeAttempt(
                status="no_path",
                rejection_reason="无满足转角与推机约束的合法路径",
                start_edges=sorted(_format_edge_id(e) for e in (start_edges or ())),
                end_edges=sorted(_format_edge_id(e) for e in (end_edges or ())),
                reversal_origin=DemoPointInput(x=origin_local[0], y=origin_local[1])
                if origin_local
                else None,
                pushback_radius_m=config.max_pushback_radius_m,
                layers=trellis,
            ),
            [],
        )

    opt_indices = [best_index]
    for refs in reversed(backrefs):
        best_index = refs[best_index]
        opt_indices.append(best_index)
    opt_indices.reverse()

    chosen_states = [layer[idx] for layer, idx in zip(state_layers_dep, opt_indices)]
    output = [DirectedEdge(*chosen_states[0].directed_edge)]
    for prev_state, curr_state in zip(chosen_states, chosen_states[1:]):
        if (not prev_state.reversed_used) and curr_state.reversed_used:
            u, v, key = prev_state.directed_edge
            start_edge: DirectedEdgeId = (v, u, key)
            output.append(DirectedEdge(*start_edge))
        else:
            start_edge = prev_state.directed_edge
        if start_edge == curr_state.directed_edge:
            continue
        tail = router.route_tail(start_edge, curr_state.directed_edge)
        assert tail is not None
        output.extend(tail)

    trellis = _build_departure_trellis(
        state_layers_dep,
        emission_values,
        scores_per_layer,
        backrefs,
        allow_flags,
        layer_meta,
        router,
        config,
        opt_indices,
    )
    return (
        DemoDecodeAttempt(
            status="accepted",
            start_edges=sorted(_format_edge_id(e) for e in (start_edges or ())),
            end_edges=sorted(_format_edge_id(e) for e in (end_edges or ())),
            reversal_origin=DemoPointInput(x=origin_local[0], y=origin_local[1])
            if origin_local
            else None,
            pushback_radius_m=config.max_pushback_radius_m,
            layers=trellis,
            decoded_edges=[_format_edge_id(e.id) for e in output],
        ),
        output,
    )


def _build_arrival_trellis(
    state_layers: Sequence[Sequence[DirectedEdgeId]],
    emission_values: Sequence[Sequence[float]],
    scores_per_layer: Sequence[Sequence[float]],
    backrefs: Sequence[Sequence[int]],
    layer_meta: Sequence[
        tuple[Literal["start_boundary", "observation", "end_boundary"], int | None, str]
    ],
    router: DirectedNetworkRouter,
    config: MatchConfig,
    opt_indices: Sequence[int] | None,
) -> list[DemoTrellisLayer]:
    layers_out: list[DemoTrellisLayer] = []
    inv_scale = 1.0 / config.length_scale_m
    for layer_idx, (states, emissions, scores, (kind, obs_idx, label)) in enumerate(
        zip(state_layers, emission_values, scores_per_layer, layer_meta)
    ):
        trellis_states: list[DemoTrellisState] = []
        for state_idx, (edge, emission, cum_score) in enumerate(zip(states, emissions, scores)):
            best_prev: int | None = None
            trans_dist: float | None = None
            trans_score: float | None = None
            if layer_idx > 0:
                ref_idx = backrefs[layer_idx - 1][state_idx]
                if ref_idx >= 0:
                    best_prev = ref_idx
                    prev_edge = state_layers[layer_idx - 1][ref_idx]
                    trans_dist = (
                        0.0 if prev_edge == edge else router.distances_from(prev_edge).get(edge)
                    )
                    if trans_dist is not None:
                        trans_score = round(-trans_dist * inv_scale, 3)
                        trans_dist = round(trans_dist, 2)
            trellis_states.append(
                DemoTrellisState(
                    state_index=state_idx,
                    directed_edge=_format_edge_id(edge),
                    u=_node_label(edge[0]),
                    v=_node_label(edge[1]),
                    key=int(edge[2]),
                    reversed_used=False,
                    emission_score=round(emission, 3),
                    best_prev_index=best_prev,
                    transition_distance_m=trans_dist,
                    transition_score=trans_score,
                    used_reversal_step=False,
                    cumulative_score=round(cum_score, 3) if cum_score > -inf else None,
                    is_optimal=bool(
                        opt_indices is not None and opt_indices[layer_idx] == state_idx
                    ),
                )
            )
        layers_out.append(
            DemoTrellisLayer(
                layer_index=layer_idx,
                kind=kind,
                observation_index=obs_idx,
                label=label,
                allow_reversal=False,
                states=trellis_states,
            )
        )
    return layers_out


def _build_departure_trellis(
    state_layers: Sequence[Sequence[DepartureState]],
    emission_values: Sequence[Sequence[float]],
    scores_per_layer: Sequence[Sequence[float]],
    backrefs: Sequence[Sequence[int]],
    allow_flags: Sequence[bool],
    layer_meta: Sequence[
        tuple[Literal["start_boundary", "observation", "end_boundary"], int | None, str]
    ],
    router: DirectedNetworkRouter,
    config: MatchConfig,
    opt_indices: Sequence[int] | None,
) -> list[DemoTrellisLayer]:
    layers_out: list[DemoTrellisLayer] = []
    inv_scale = 1.0 / config.length_scale_m
    for layer_idx, (states, emissions, scores, allow_rev, (kind, obs_idx, label)) in enumerate(
        zip(state_layers, emission_values, scores_per_layer, allow_flags, layer_meta)
    ):
        trellis_states: list[DemoTrellisState] = []
        for state_idx, (state, emission, cum_score) in enumerate(zip(states, emissions, scores)):
            edge = state.directed_edge
            best_prev: int | None = None
            trans_dist: float | None = None
            trans_score: float | None = None
            used_rev = False
            if layer_idx > 0:
                ref_idx = backrefs[layer_idx - 1][state_idx]
                if ref_idx >= 0:
                    best_prev = ref_idx
                    prev_state = state_layers[layer_idx - 1][ref_idx]
                    used_rev = (not prev_state.reversed_used) and state.reversed_used
                    if used_rev:
                        u, v, key = prev_state.directed_edge
                        start_edge: DirectedEdgeId = (v, u, key)
                    else:
                        start_edge = prev_state.directed_edge
                    trans_dist = (
                        0.0 if start_edge == edge else router.distances_from(start_edge).get(edge)
                    )
                    if trans_dist is not None:
                        penalty = -REVERSAL_PENALTY_M * inv_scale if used_rev else 0.0
                        trans_score = round(-trans_dist * inv_scale + penalty, 3)
                        trans_dist = round(trans_dist, 2)
            trellis_states.append(
                DemoTrellisState(
                    state_index=state_idx,
                    directed_edge=_format_edge_id(edge),
                    u=_node_label(edge[0]),
                    v=_node_label(edge[1]),
                    key=int(edge[2]),
                    reversed_used=state.reversed_used,
                    emission_score=round(emission, 3),
                    best_prev_index=best_prev,
                    transition_distance_m=trans_dist,
                    transition_score=trans_score,
                    used_reversal_step=used_rev,
                    cumulative_score=round(cum_score, 3) if cum_score > -inf else None,
                    is_optimal=bool(
                        opt_indices is not None and opt_indices[layer_idx] == state_idx
                    ),
                )
            )
        layers_out.append(
            DemoTrellisLayer(
                layer_index=layer_idx,
                kind=kind,
                observation_index=obs_idx,
                label=label,
                allow_reversal=allow_rev,
                states=trellis_states,
            )
        )
    return layers_out


def _phase1_rejection_reason(
    airport_graph: AirportGraph,
    flight: Flight,
    trimmed: Sequence[DirectedEdge],
    is_departure: bool,
) -> str | None:
    if not trimmed:
        return "裁剪跑道滑跑段后无剩余滑行边"
    stand_edge = trimmed[0] if is_departure else trimmed[-1]
    runway_edge = trimmed[-1] if is_departure else trimmed[0]

    matched_stand = airport_graph.stand_for_edge(stand_edge.id)
    if matched_stand is None:
        side = "起" if is_departure else "终"
        return f"纯轨迹{side}点边 {_format_edge_id(stand_edge.id)} 未命中任何机位"
    if flight.stand_ref and matched_stand != flight.stand_ref:
        return f"纯轨迹命中机位 {matched_stand}，与航班机位 {flight.stand_ref} 不一致"

    matched_runways = airport_graph.runways_for_edge(runway_edge.id)
    if matched_runways is None:
        side = "终" if is_departure else "起"
        return f"纯轨迹{side}点边 {_format_edge_id(runway_edge.id)} 未命中跑道接口"
    interface_node = runway_edge.to_ if is_departure else runway_edge.from_
    interface = airport_graph.runway_interfaces.get(interface_node)
    if interface is None:
        return f"端点 {interface_node} 不是合法跑道接口节点"
    if flight.runway_ref:
        expected_runway = flight.runway_ref.upper()
        node_runways = {
            part.strip()
            for edge_id in interface["runway"]
            for part in str(airport_graph.graph.edges[edge_id].get("ref") or "").upper().split("/")
            if part.strip()
        }
        if expected_runway not in node_runways:
            return f"纯轨迹命中跑道 {sorted(node_runways)}，与目标跑道 {expected_runway} 不一致"
    return None


def trace_demo_scenario(
    scenario_id: str,
    *,
    observations: Sequence[DemoPointInput] | None = None,
    config_override: DemoMatchConfig | None = None,
) -> DemoTraceResponse:
    spec = _SCENARIO_MAP.get(scenario_id)
    if spec is None:
        raise KeyError(f"未知演示场景: {scenario_id}")

    config = _dto_to_config(config_override, spec.default_config)
    raw_points = (
        [(point.x, point.y) for point in observations]
        if observations is not None
        else list(spec.default_observations)
    )
    airport_graph = _toy_airport_graph()
    flight = _build_flight(spec, raw_points)
    matcher = Matcher(airport_graph, config)
    router = matcher._directed_router
    is_departure = spec.movement == "departure"

    projected_points = project_observations(airport_graph, flight)
    obs_traces: list[DemoObservationTrace] = []
    retained_points: list[Point] = []
    retained_layers: list[list[Candidate]] = []
    retained_indices: list[int] = []

    for index, (point, (local_x, local_y)) in enumerate(zip(projected_points, raw_points)):
        candidates = matcher._candidates(index, point)
        retained = bool(candidates)
        if retained:
            retained_points.append(point)
            retained_layers.append(candidates)
            retained_indices.append(index)
        cand_dtos: list[DemoObservationCandidate] = []
        for cand in candidates:
            u, v, key = cand.edge_id
            edge_data = airport_graph.graph.edges[cand.edge_id]
            cand_dtos.append(
                DemoObservationCandidate(
                    edge_id=_format_undirected_edge_id(u, v, int(key)),
                    u=_node_label(u),
                    v=_node_label(v),
                    key=int(key),
                    aeroway=str(edge_data.get("aeroway") or "taxiway"),
                    ref=str(edge_data["ref"]) if edge_data.get("ref") is not None else None,
                    distance_m=round(cand.distance, 2),
                    emission_score=round(observation_log_score(cand.distance, config.gps_sigma), 3),
                )
            )
        obs_traces.append(
            DemoObservationTrace(
                index=index,
                x=round(local_x, 2),
                y=round(local_y, 2),
                retained=retained,
                candidates=cand_dtos,
            )
        )

    # Ground truth execution through real Matcher.map_flight()
    real_edges: list[str] = []
    real_error_code: str | None = None
    real_error_message: str | None = None
    try:
        real_path = matcher.map_flight(flight)
        real_edges = [_format_edge_id(edge.id) for edge in real_path]
    except MapMatchingError as exc:
        real_error_code = str(exc.code)
        real_error_message = str(exc)

    all_runway_roll_edges = matcher._runway_boundary(None, is_departure).roll_edges

    phase1: DemoDecodeAttempt
    phase2: DemoDecodeAttempt | None = None
    used_phase: Literal["phase1", "phase2"] | None = None

    if not retained_layers:
        phase1 = DemoDecodeAttempt(
            status="no_path",
            rejection_reason="所有观测点在 candidate_radius 内均未召回候选边",
        )
    else:
        p1_attempt, p1_edges = _trace_decode(
            retained_layers,
            retained_points,
            retained_indices,
            router,
            config,
            is_departure=is_departure,
        )
        if p1_edges:
            trimmed = trim_runway_edges(p1_edges, all_runway_roll_edges, is_departure=is_departure)
            p1_attempt.trimmed_edges = [_format_edge_id(e.id) for e in trimmed]
            reason = _phase1_rejection_reason(airport_graph, flight, trimmed, is_departure)
            if reason is None:
                p1_attempt.status = "accepted"
                used_phase = "phase1"
            else:
                p1_attempt.status = "rejected"
                p1_attempt.rejection_reason = reason
        phase1 = p1_attempt

        if used_phase is None:
            try:
                _, stand_edges = matcher._flight_stand_edges(flight)
                runway = matcher._flight_runway_spec(
                    flight,
                    retained_layers[-1] if is_departure else retained_layers[0],
                    is_departure,
                )
                start_edges, end_edges = (
                    (stand_edges, runway.boundary_edges)
                    if is_departure
                    else (runway.boundary_edges, stand_edges)
                )
                reversal_origin = router.edge_centroid(stand_edges) if is_departure else None
                p2_attempt, p2_edges = _trace_decode(
                    retained_layers,
                    retained_points,
                    retained_indices,
                    router,
                    config,
                    is_departure=is_departure,
                    start_edges=start_edges,
                    end_edges=end_edges,
                    reversal_origin=reversal_origin,
                )
                if p2_edges:
                    trimmed_p2 = trim_runway_edges(
                        p2_edges, runway.roll_edges, is_departure=is_departure
                    )
                    p2_attempt.trimmed_edges = [_format_edge_id(e.id) for e in trimmed_p2]
                    if trimmed_p2:
                        p2_attempt.status = "accepted"
                        used_phase = "phase2"
                    else:
                        p2_attempt.status = "rejected"
                        p2_attempt.rejection_reason = "裁剪跑道滑跑段后无剩余滑行边"
                phase2 = p2_attempt
            except MapMatchingError as exc:
                phase2 = DemoDecodeAttempt(status="no_path", rejection_reason=str(exc))

    final_result = DemoFinalResult(
        status="success" if real_error_code is None else "failed",
        used_phase=used_phase if real_error_code is None else None,
        edges=real_edges,
        error_code=real_error_code,
        error_message=real_error_message,
    )

    return DemoTraceResponse(
        scenario=_scenario_summary(spec),
        config=_config_to_dto(config),
        graph=_serialize_graph(airport_graph),
        observations=obs_traces,
        dual_graph=_serialize_dual_graph(router),
        phase1=phase1,
        phase2=phase2,
        final_result=final_result,
    )
