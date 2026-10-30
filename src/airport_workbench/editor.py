"""Topology editing operations and browser workbench launch helpers."""

from __future__ import annotations

import threading
import time
import webbrowser
from contextlib import contextmanager
from copy import deepcopy
from itertools import combinations
from math import acos, degrees
from pathlib import Path as FilePath
from threading import RLock
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import networkx as nx
from shapely.geometry import LineString, Point, mapping
from shapely.ops import nearest_points, substring, transform

from adsb import Flight
from airport_surface import (
    AirportGraph,
    NodeMergeGroup,
    NodeSnapRecord,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
)
from airport_surface.graph import (
    DEFAULT_GRAPH_PATH,
    apply_source_segments,
    compact_source_segments,
    geometry_from_source_interval,
    geometry_from_source_segments,
    rebuild_source_edges,
    reverse_source_segments,
    source_boundaries,
    source_registry,
    validate_edge_endpoints,
    validate_edge_sources,
)

if TYPE_CHECKING:
    from path_map import Path

MANUAL_SOURCE_TOLERANCE_M = 0.5
MERGE_CANDIDATE_TOLERANCE_M = 0.5
MANUAL_MERGE_MAX_DISTANCE_M = 2.0
MANUAL_NODE_TO_EDGE_MAX_DISTANCE_M = 10.0
RESTORE_CANDIDATE_LIMIT = 5
RESTORE_MAX_SOURCE_EDGES = 8


class EditorSession:
    """Own and directly mutate one AirportGraph during an editing session."""

    def __init__(self, airport_graph: AirportGraph, tolerance_m: float = 8) -> None:
        self.tolerance_m = tolerance_m
        self.airport_graph = AirportGraph(
            airport_graph.graph.copy(),
            airport_graph.projection,
            source_nodes=airport_graph.source_nodes,
            source_edges=airport_graph.source_edges,
            node_aliases=airport_graph.node_aliases,
            node_merge_groups=airport_graph.node_merge_groups,
            node_snap_records=airport_graph.node_snap_records,
            parking_position_nodes=airport_graph.parking_position_nodes,
            runway_access_nodes=airport_graph.runway_access_nodes,
            metadata=airport_graph.metadata,
        )
        self._history: list[tuple[AirportGraph, bool]] = []
        self.revision = 0
        self.topology_revision = 0
        self.lock = RLock()
        self._source_path_graph = self._build_source_path_graph()

    @property
    def graph(self) -> nx.MultiGraph:
        return self.airport_graph.graph

    def _refresh(self) -> None:
        current = self.airport_graph
        self.airport_graph = AirportGraph(
            self.graph,
            current.projection,
            source_nodes=current.source_nodes,
            source_edges=current.source_edges,
            node_aliases=current.node_aliases,
            node_merge_groups=current.node_merge_groups,
            node_snap_records=current.node_snap_records,
            parking_position_nodes=current.parking_position_nodes,
            runway_access_nodes=current.runway_access_nodes,
            metadata=current.metadata,
        )

    @property
    def can_undo(self) -> bool:
        return bool(self._history)

    @contextmanager
    def _edit(self, *, topology_change: bool = True) -> Any:
        """Make one graph edit atomic and record it only after success."""
        with self.lock:
            backup = self.airport_graph.copy()
            try:
                yield
                self._refresh()
            except Exception:
                self.airport_graph = backup
                raise
            self._history.append((backup, topology_change))
            self.revision += 1
            if topology_change:
                self.topology_revision += 1
            if len(self._history) > 50:
                self._history.pop(0)

    def undo(self) -> None:
        with self.lock:
            if not self._history:
                raise ValueError("没有可以撤销的操作")
            self.airport_graph, topology_change = self._history.pop()
            self.revision += 1
            if topology_change:
                self.topology_revision += 1
            self._source_path_graph = self._build_source_path_graph()

    def _new_node_id(self) -> int:
        integer_nodes = [node for node in self.graph if isinstance(node, int)]
        candidate = min([0, *integer_nodes]) - 1
        while candidate in self.graph:
            candidate -= 1
        return candidate

    def add_node(self, longitude: float, latitude: float, **attributes: Any) -> Any:
        with self._edit():
            node = self._new_node_id()
            self.graph.add_node(node, pos=(longitude, latitude), source="manual", **attributes)
        return node

    def delete_node(self, node: Any) -> None:
        with self._edit():
            self.graph.remove_node(node)
            self.airport_graph.parking_position_nodes.discard(node)
            self.airport_graph.runway_access_nodes.discard(node)

    def set_business_node_annotations(
        self, node: Any, *, parking_position: bool, runway_access: bool
    ) -> None:
        if node not in self.graph:
            raise ValueError(f"未知节点: {node!r}")
        with self._edit(topology_change=False):
            for enabled, collection in (
                (parking_position, self.airport_graph.parking_position_nodes),
                (runway_access, self.airport_graph.runway_access_nodes),
            ):
                if enabled:
                    collection.add(node)
                else:
                    collection.discard(node)

    def add_edge(self, u: Any, v: Any, **attributes: Any) -> Any:
        with self._edit():
            geometry = LineString([self.graph.nodes[u]["pos"][:2], self.graph.nodes[v]["pos"][:2]])
            data = {
                "geometry": geometry,
                "first": u,
                "last": v,
                "aeroway": attributes.pop("aeroway", "taxiway"),
                "parking_position": attributes.pop("parking_position", None),
                "ref": attributes.pop("ref", None),
                "name": attributes.pop("name", None),
                "source_type": "manual",
                **attributes,
            }
            key = self.graph.add_edge(u, v, **data)
            registry = source_registry(self.airport_graph)
            source_id = f"manual-{u}-{v}-{key}"
            suffix = 2
            while source_id in registry:
                source_id = f"manual-{u}-{v}-{key}-{suffix}"
                suffix += 1
            source = SourceEdge(
                source_id,
                geometry,
                "manual",
                attributes={name: value for name, value in data.items() if name != "geometry"},
            )
            registry[source_id] = source
            data.update(
                source_id=source_id,
                source_start_m=0.0,
                source_end_m=self.airport_graph.length(geometry),
                source_segments=(
                    SourceSegment(source_id, 0.0, self.airport_graph.length(geometry)),
                ),
            )
            self.graph.edges[u, v, key].update(data)
        return key

    def delete_edge(self, u: Any, v: Any, key: Any) -> None:
        with self._edit():
            self.graph.remove_edge(u, v, key)

    def remove_derived_edge(self, u: Any, v: Any, key: Any) -> dict[str, Any]:
        """Remove only one derived topology edge; its SourceEdge is untouched."""
        data = self.graph.edges[u, v, key]
        preview = {
            "edge": repr((u, v, key)),
            "endpoints": [repr(u), repr(v)],
            "source_id": data.get("source_id"),
            "source_interval": [data.get("source_start_m"), data.get("source_end_m")],
        }
        self.delete_edge(u, v, key)
        return preview

    def _build_source_path_graph(self) -> nx.Graph:
        """Build an immutable-OSM routing index used only for manual restoration."""
        graph = nx.Graph()
        for source_id, source in self.airport_graph.source_edges.items():
            projected = self.airport_graph.project_shape(source.geometry)
            distances = [0.0]
            for left, right in zip(projected.coords, projected.coords[1:]):
                distances.append(distances[-1] + Point(left).distance(Point(right)))
            canonical = [
                self.airport_graph.canonical_node_id(node) for node in source.osm_node_ids
            ]
            for index, (left, right) in enumerate(zip(canonical, canonical[1:])):
                length = distances[index + 1] - distances[index]
                if left == right or length <= 1e-3:
                    continue
                option = {
                    "source_id": source_id,
                    "left": left,
                    "right": right,
                    "source_start_m": distances[index],
                    "source_end_m": distances[index + 1],
                    "length_m": length,
                }
                if graph.has_edge(left, right):
                    graph[left][right]["options"].append(option)
                    graph[left][right]["weight"] = min(
                        graph[left][right]["weight"], length
                    )
                else:
                    graph.add_edge(left, right, weight=length, options=[option])
        return graph

    def _segments_for_source_path(self, nodes: list[Any]) -> tuple[SourceSegment, ...]:
        segments = []
        for left, right in zip(nodes, nodes[1:]):
            options = self._source_path_graph[left][right]["options"]
            option = min(options, key=lambda item: item["length_m"])
            segments.append(
                SourceSegment(
                    option["source_id"],
                    option["source_start_m"],
                    option["source_end_m"],
                    option["left"] != left,
                )
            )
        return compact_source_segments(segments)

    def connection_candidates(self, u: Any, v: Any) -> list[dict[str, Any]]:
        """Find short continuous paths through one or more immutable SourceEdges."""
        canonical_u = self.airport_graph.canonical_node_id(u)
        canonical_v = self.airport_graph.canonical_node_id(v)
        if canonical_u not in self._source_path_graph or canonical_v not in self._source_path_graph:
            return []
        start_point = Point(self.airport_graph.project.transform(*self.graph.nodes[u]["pos"][:2]))
        end_point = Point(self.airport_graph.project.transform(*self.graph.nodes[v]["pos"][:2]))
        maximum_length = max(100.0, start_point.distance(end_point) * 4)
        candidates: list[dict[str, Any]] = []
        try:
            paths = nx.shortest_simple_paths(
                self._source_path_graph,
                canonical_u,
                canonical_v,
                weight="weight",
            )
            for path in paths:
                segments = self._segments_for_source_path(path)
                source_ids = tuple(dict.fromkeys(segment.source_id for segment in segments))
                length_m = sum(
                    segment.source_end_m - segment.source_start_m for segment in segments
                )
                if length_m > maximum_length:
                    break
                if len(source_ids) > RESTORE_MAX_SOURCE_EDGES:
                    continue
                geometry = geometry_from_source_segments(self.airport_graph, segments, u, v)
                candidates.append(
                    {
                        "candidate_id": f"r{len(candidates)}",
                        "source_ids": source_ids,
                        "osm_way_ids": tuple(
                            self.airport_graph.get_source_edge(source_id).osm_way_id
                            for source_id in source_ids
                        ),
                        "refs": tuple(
                            self.airport_graph.get_source_edge(source_id).attributes.get("ref")
                            for source_id in source_ids
                        ),
                        "length_m": length_m,
                        "first": u,
                        "last": v,
                        "segments": segments,
                        "geometry": geometry,
                    }
                )
                if len(candidates) >= RESTORE_CANDIDATE_LIMIT:
                    break
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return candidates

    def restore_source_connection(self, u: Any, v: Any, candidate_id: str) -> Any:
        candidates = [
            candidate
            for candidate in self.connection_candidates(u, v)
            if candidate["candidate_id"] == candidate_id
        ]
        if len(candidates) != 1:
            raise ValueError("恢复候选已失效，请重新预览")
        candidate = candidates[0]
        if any(
            edge_source_segments(data) == candidate["segments"]
            for _eu, _ev, _key, data in self.graph.edges(keys=True, data=True)
        ):
            raise ValueError("该来源路径已经存在于图中")
        first_source = self.airport_graph.get_source_edge(candidate["source_ids"][0])
        data = dict(first_source.attributes)
        data.update(
            geometry=candidate["geometry"],
            first=candidate["first"],
            last=candidate["last"],
            source_type="composite",
        )
        apply_source_segments(data, candidate["segments"])
        if len(candidate["segments"]) == 1:
            data["source_type"] = first_source.source_type
            data["osm_node_ids"] = self._source_nodes_in_interval(
                candidate["segments"][0].source_id,
                candidate["segments"][0].source_start_m,
                candidate["segments"][0].source_end_m,
            )
        with self._edit():
            key = self.graph.add_edge(candidate["first"], candidate["last"], **data)
            edge_ids = [(candidate["first"], candidate["last"], key)]
            validate_edge_endpoints(self.airport_graph, edge_ids=edge_ids)
            validate_edge_sources(self.airport_graph, edge_ids=edge_ids)
        return key

    def merge_candidates(
        self, tolerance_m: float = MERGE_CANDIDATE_TOLERANCE_M
    ) -> list[dict[str, Any]]:
        """Return complete-link groups of nearby graph nodes; never merge automatically."""
        nodes = list(self.graph)
        positions = {
            node: Point(
                self.airport_graph.project.transform(
                    *self.graph.nodes[node]["pos"][:2]
                )
            )
            for node in nodes
        }
        cells: dict[tuple[int, int], list[Any]] = {}
        proximity = nx.Graph()
        proximity.add_nodes_from(nodes)
        for node, point in positions.items():
            cell = (int(point.x // tolerance_m), int(point.y // tolerance_m))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other in cells.get((cell[0] + dx, cell[1] + dy), ()):
                        if point.distance(positions[other]) <= tolerance_m:
                            proximity.add_edge(node, other)
            cells.setdefault(cell, []).append(node)
        groups = []
        for members in nx.find_cliques(proximity):
            if len(members) < 2:
                continue
            members = sorted(members, key=repr)
            maximum = max(
                positions[left].distance(positions[right])
                for left, right in combinations(members, 2)
            )
            groups.append(
                {
                    "candidate_id": f"m{len(groups)}",
                    "node_ids": members,
                    "max_distance_m": maximum,
                    "nodes": [
                        {
                            "node_id": node,
                            "position": self.graph.nodes[node]["pos"][:2],
                            "is_graph_node": True,
                            "manual": node not in self.airport_graph.source_nodes,
                            "degree": self.graph.degree(node),
                        }
                        for node in members
                    ],
                }
            )
        return sorted(groups, key=lambda item: item["max_distance_m"])

    def _merge_nodes(self, node_ids: Sequence[Any]) -> tuple[Any, ...]:
        canonical = tuple(
            dict.fromkeys(self.airport_graph.canonical_node_id(node) for node in node_ids)
        )
        if len(canonical) < 2:
            raise ValueError("至少需要两个尚未合并的图节点")
        internal = [node for node in canonical if node not in self.graph]
        if internal:
            raise ValueError(f"合并工具只处理现有图节点，以下节点不在图中: {internal!r}")
        return canonical

    def merge_nodes_preview(
        self, node_ids: Sequence[Any], canonical_node: Any | None = None
    ) -> dict[str, Any]:
        members = self._merge_nodes(node_ids)
        points = {
            node: Point(
                self.airport_graph.project.transform(
                    *self.graph.nodes[node]["pos"][:2]
                )
            )
            for node in members
        }
        maximum = max(
            points[left].distance(points[right]) for left, right in combinations(members, 2)
        )
        if maximum > MANUAL_MERGE_MAX_DISTANCE_M:
            raise ValueError(
                f"节点最大距离 {maximum:.3f} m，超过人工合并上限 "
                f"{MANUAL_MERGE_MAX_DISTANCE_M:.3f} m"
            )
        if canonical_node is None:
            canonical_node = min(
                members,
                key=lambda node: sum(points[node].distance(points[other]) for other in members),
            )
        canonical_node = self.airport_graph.canonical_node_id(canonical_node)
        if canonical_node not in members:
            raise ValueError("规范节点必须属于待合并节点")
        source_membership = {
            node: [
                source_id
                for source_id, source in self.airport_graph.source_edges.items()
                if node in {
                    self.airport_graph.canonical_node_id(item) for item in source.osm_node_ids
                }
            ]
            for node in members
        }
        for attribute in ("layer", "bridge", "tunnel"):
            values = {
                self.airport_graph.get_source_edge(source_id).attributes.get(attribute)
                for source_ids in source_membership.values()
                for source_id in source_ids
                if self.airport_graph.get_source_edge(source_id).attributes.get(attribute)
                is not None
            }
            if len(values) > 1:
                raise ValueError(
                    f"来源的 {attribute} 属性冲突，不能合并: "
                    f"{sorted(values, key=repr)!r}"
                )
        direct_edges = [
            (u, v, key)
            for u, v, key in self.graph.edges(keys=True)
            if u in members and v in members
        ]
        affected = [
            (u, v, key)
            for u, v, key in self.graph.edges(keys=True)
            if u in members or v in members
        ]
        warnings = []
        if direct_edges:
            warnings.append("成员节点之间存在直接边；合并时这些边会成为自环并被移除")
        if maximum > MERGE_CANDIDATE_TOLERANCE_M:
            warnings.append("节点距离超过普通候选范围，请重点检查")
        common_sources = set.intersection(
            *(set(source_membership[node]) for node in members)
        )
        if common_sources:
            warnings.append(
                "成员节点位于同一个 SourceEdge 上，请确认它们不是两个真实的相邻形状点"
            )
        aeroways = {
            self.airport_graph.get_source_edge(source_id).attributes.get("aeroway")
            for source_ids in source_membership.values()
            for source_id in source_ids
        }
        if len(aeroways - {None}) > 1:
            warnings.append("成员节点关联的道路类型不同，请检查是否确实属于同一拓扑点")
        return {
            "node_ids": list(members),
            "canonical_node_id": canonical_node,
            "max_distance_m": maximum,
            "nodes": [
                {
                    "node_id": node,
                    "position": self.graph.nodes[node]["pos"][:2],
                    "source_ids": source_membership[node],
                    "is_graph_node": True,
                    "manual": node not in self.airport_graph.source_nodes,
                    "degree": self.graph.degree(node),
                }
                for node in members
            ],
            "affected_edges": [repr(edge) for edge in affected],
            "removed_self_loop_edges": [repr(edge) for edge in direct_edges],
            "warnings": warnings,
            "source_edges_unchanged": True,
        }

    def merge_nodes(
        self, node_ids: Sequence[Any], canonical_node: Any | None = None
    ) -> Any:
        preview = self.merge_nodes_preview(node_ids, canonical_node)
        members = tuple(preview["node_ids"])
        canonical = preview["canonical_node_id"]
        original_positions = {
            member: tuple(self.graph.nodes[member]["pos"][:2]) for member in members
        }
        with self._edit():
            parking = any(
                member in self.airport_graph.parking_position_nodes
                for member in members
            )
            runway_access = any(
                member in self.airport_graph.runway_access_nodes for member in members
            )
            incident = [
                (u, v, key, deepcopy(data))
                for u, v, key, data in self.graph.edges(keys=True, data=True)
                if u in members or v in members
            ]
            canonical_data = deepcopy(self.graph.nodes[canonical])
            for member in members:
                if member in self.graph:
                    self.graph.remove_node(member)
            merged_osm_ids = tuple(
                dict.fromkeys(
                    osm_id
                    for member in members
                    for osm_id in (
                        self.airport_graph.source_nodes[member].osm_node_ids
                        if member in self.airport_graph.source_nodes
                        else ()
                    )
                )
            )
            canonical_data.update(
                pos=original_positions[canonical],
                source_type="osm" if merged_osm_ids else "manual",
                osm_node_ids=merged_osm_ids,
                merge_type="manual",
            )
            self.graph.add_node(canonical, **canonical_data)
            self.airport_graph.parking_position_nodes.difference_update(members)
            self.airport_graph.runway_access_nodes.difference_update(members)
            if parking:
                self.airport_graph.parking_position_nodes.add(canonical)
            if runway_access:
                self.airport_graph.runway_access_nodes.add(canonical)
            added_edges = []
            for u, v, _key, data in incident:
                first = canonical if data.get("first", u) in members else data.get("first", u)
                last = canonical if data.get("last", v) in members else data.get("last", v)
                if first == last:
                    continue
                segments = edge_source_segments(data)
                data.update(
                    first=first,
                    last=last,
                    geometry=geometry_from_source_segments(
                        self.airport_graph, segments, first, last
                    ),
                )
                length_m = self.airport_graph.length(data["geometry"])
                if "length" in data:
                    data["length"] = length_m
                if "length_m" in data:
                    data["length_m"] = length_m
                key = self.graph.add_edge(first, last, **data)
                added_edges.append((first, last, key))
            attributes = deepcopy(
                dict(self.airport_graph.source_nodes[canonical].attributes)
                if canonical in self.airport_graph.source_nodes
                else {}
            )
            attributes["manual_merge_original_positions"] = original_positions
            self.airport_graph.source_nodes[canonical] = SourceNode(
                canonical,
                original_positions[canonical],
                merged_osm_ids,
                attributes,
            )
            for member in members:
                if member != canonical:
                    self.airport_graph.source_nodes.pop(member, None)
            for alias, target in list(self.airport_graph.node_aliases.items()):
                if target in members:
                    self.airport_graph.node_aliases[alias] = canonical
            for member in members:
                if member != canonical:
                    self.airport_graph.node_aliases[member] = canonical
            self.airport_graph.node_merge_groups[canonical] = NodeMergeGroup(
                canonical, members, original_positions, "manual"
            )
            validate_edge_endpoints(self.airport_graph, edge_ids=added_edges)
            validate_edge_sources(self.airport_graph, edge_ids=added_edges)
        self._source_path_graph = self._build_source_path_graph()
        return canonical

    def _incident_records(self, node: Any) -> list[dict[str, Any]]:
        records = []
        for index, (u, v, key, data) in enumerate(self.graph.edges(node, keys=True, data=True)):
            outer = v if u == node else u
            records.append(
                {
                    "half_id": f"h{index}",
                    "outer": outer,
                    "u": u,
                    "v": v,
                    "key": key,
                    "data": data,
                }
            )
        return records

    def _segments_between(self, record: dict[str, Any], start: Any) -> tuple[SourceSegment, ...]:
        segments = edge_source_segments(record["data"])
        if not segments:
            raise ValueError(f"边 {(record['u'], record['v'], record['key'])!r} 没有来源片段")
        return (
            segments
            if record["data"].get("first", record["u"]) == start
            else reverse_source_segments(segments)
        )

    def _pair_angle(self, node: Any, left: dict[str, Any], right: dict[str, Any]) -> float:
        center = Point(self.airport_graph.project.transform(*self.graph.nodes[node]["pos"][:2]))

        def outward(record: dict[str, Any]) -> tuple[float, float]:
            line = self.airport_graph.project_shape(record["data"]["geometry"])
            start = Point(line.coords[0])
            coordinates = list(line.coords)
            if start.distance(center) > Point(line.coords[-1]).distance(center):
                coordinates.reverse()
            for coordinate in coordinates[1:]:
                dx, dy = coordinate[0] - center.x, coordinate[1] - center.y
                if dx * dx + dy * dy > 1e-8:
                    return dx, dy
            return 0.0, 0.0

        lx, ly = outward(left)
        rx, ry = outward(right)
        denominator = (lx * lx + ly * ly) ** 0.5 * (rx * rx + ry * ry) ** 0.5
        if denominator == 0:
            return 0.0
        cosine = max(-1.0, min(1.0, (lx * rx + ly * ry) / denominator))
        return degrees(acos(cosine))

    def _pair_segments(
        self, node: Any, left: dict[str, Any], right: dict[str, Any]
    ) -> tuple[SourceSegment, ...]:
        left_segments = self._segments_between(left, left["outer"])
        right_segments = self._segments_between(right, node)
        return compact_source_segments((*left_segments, *right_segments))

    def node_deletion_plan(self, node: Any) -> dict[str, Any]:
        records = self._incident_records(node)
        candidates = []
        for index, (left, right) in enumerate(combinations(records, 2)):
            if left["outer"] == right["outer"]:
                continue
            try:
                segments = self._pair_segments(node, left, right)
                geometry = geometry_from_source_segments(
                    self.airport_graph, segments, left["outer"], right["outer"]
                )
            except ValueError:
                continue
            source_ids = [segment.source_id for segment in segments]
            candidates.append(
                {
                    "pair_id": f"p{index}",
                    "left": left["half_id"],
                    "right": right["half_id"],
                    "endpoints": [repr(left["outer"]), repr(right["outer"])],
                    "source_ids": source_ids,
                    "same_source": len(set(source_ids)) == 1,
                    "angle_degrees": round(self._pair_angle(node, left, right), 1),
                    "geometry": mapping(geometry),
                    "recommended": False,
                }
            )
        used: set[str] = set()
        for candidate in candidates:
            if candidate["same_source"]:
                candidate["recommended"] = True
                used.update((candidate["left"], candidate["right"]))
        for candidate in sorted(candidates, key=lambda item: abs(180 - item["angle_degrees"])):
            if (
                not candidate["same_source"]
                and candidate["left"] not in used
                and candidate["right"] not in used
            ):
                candidate["recommended"] = True
                used.update((candidate["left"], candidate["right"]))
        return {
            "node": repr(node),
            "degree": self.graph.degree[node],
            "half_edges": [
                {
                    "half_id": record["half_id"],
                    "edge": repr((record["u"], record["v"], record["key"])),
                    "outer_node": repr(record["outer"]),
                    "source_ids": [
                        segment.source_id for segment in edge_source_segments(record["data"])
                    ],
                }
                for record in records
            ],
            "pair_candidates": candidates,
            "recommended_unpaired": [
                record["half_id"] for record in records if record["half_id"] not in used
            ],
        }

    def remove_node_with_pairs(
        self, node: Any, pair_ids: Sequence[str], discard_unpaired: bool = False
    ) -> None:
        record_list = self._incident_records(node)
        records = {record["half_id"]: record for record in record_list}
        candidates = {
            f"p{index}": {
                "pair_id": f"p{index}",
                "left": left["half_id"],
                "right": right["half_id"],
            }
            for index, (left, right) in enumerate(combinations(record_list, 2))
            if left["outer"] != right["outer"]
        }
        selected = []
        selected_ids: set[str] = set()
        used: set[str] = set()
        for pair_id in pair_ids:
            if pair_id not in candidates:
                raise ValueError(f"未知的半边配对: {pair_id}")
            if pair_id in selected_ids:
                raise ValueError(f"半边配对被重复提交: {pair_id}")
            candidate = candidates[pair_id]
            selected_ids.add(pair_id)
            used.update((candidate["left"], candidate["right"]))
            selected.append(candidate)
        unpaired = set(records) - used
        if unpaired and not discard_unpaired:
            raise ValueError(f"仍有未配对半边 {sorted(unpaired)!r}；请取消删除或明确丢弃")

        additions: list[tuple[Any, Any, dict[str, Any]]] = []
        protected = {
            "geometry",
            "first",
            "last",
            "source_id",
            "source_type",
            "source_start_m",
            "source_end_m",
            "source_segments",
            "osm_node_ids",
            "split_from",
            "length",
            "length_m",
        }
        for candidate in selected:
            left, right = records[candidate["left"]], records[candidate["right"]]
            first, last = left["outer"], right["outer"]
            segments = self._pair_segments(node, left, right)
            data = {
                name: deepcopy(value)
                for name, value in left["data"].items()
                if name not in protected
            }
            data.update(
                geometry=geometry_from_source_segments(self.airport_graph, segments, first, last),
                first=first,
                last=last,
            )
            length_m = self.airport_graph.length(data["geometry"])
            if "length" in left["data"] or "length" in right["data"]:
                data["length"] = length_m
            if "length_m" in left["data"] or "length_m" in right["data"]:
                data["length_m"] = length_m
            apply_source_segments(data, segments)
            if len(segments) == 1:
                source = self.airport_graph.get_source_edge(segments[0].source_id)
                data["source_type"] = source.source_type
                data["osm_node_ids"] = self._source_nodes_in_interval(
                    segments[0].source_id,
                    segments[0].source_start_m,
                    segments[0].source_end_m,
                )
            additions.append((first, last, data))
        with self._edit():
            self.graph.remove_node(node)
            self.airport_graph.parking_position_nodes.discard(node)
            self.airport_graph.runway_access_nodes.discard(node)
            added_edges = []
            for first, last, data in additions:
                key = self.graph.add_edge(first, last, **data)
                added_edges.append((first, last, key))
            validate_edge_endpoints(self.airport_graph, edge_ids=added_edges)
            validate_edge_sources(self.airport_graph, edge_ids=added_edges)

    def update_node_attributes(self, node: Any, attributes: dict[str, Any]) -> None:
        attributes = deepcopy(attributes)
        attributes.pop("pos", None)
        with self._edit(topology_change=False):
            position = self.graph.nodes[node]["pos"]
            self.graph.nodes[node].clear()
            self.graph.nodes[node].update(pos=position, **attributes)

    def update_edge_attributes(self, u: Any, v: Any, key: Any, attributes: dict[str, Any]) -> None:
        attributes = deepcopy(attributes)
        with self._edit(topology_change=False):
            data = self.graph.edges[u, v, key]
            protected_names = {
                "geometry",
                "first",
                "last",
                "source_id",
                "source_type",
                "source_start_m",
                "source_end_m",
                "source_segments",
                "osm_node_ids",
                "split_from",
            }
            protected = {name: data[name] for name in protected_names if name in data}
            for name in protected:
                attributes.pop(name, None)
            data.clear()
            data.update(**protected, **attributes)

    def insert_node_at(self, longitude: float, latitude: float) -> Any:
        with self.lock:
            return self._insert_node_at(longitude, latitude)

    def _insert_node_at(self, longitude: float, latitude: float) -> Any:
        click = self.airport_graph.project_shape(Point(longitude, latitude))
        candidates = []
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            geometry = data.get("geometry")
            if geometry is None:
                continue
            projected = self.airport_graph.project_shape(geometry)
            distance = projected.distance(click)
            if distance <= self.tolerance_m:
                candidates.append((distance, u, v, key, data, projected))
        if not candidates:
            raise ValueError(f"{self.tolerance_m:g} 米范围内没有可切分的边")

        split_point = None
        for left, right in combinations(candidates, 2):
            for point in self._intersection_points(left[5].intersection(right[5])):
                if point.distance(click) <= self.tolerance_m and (
                    split_point is None or point.distance(click) < split_point.distance(click)
                ):
                    split_point = point
        if split_point is None:
            nearest = min(candidates, key=lambda item: item[0])
            split_point = nearest_points(nearest[5], click)[0]

        affected = [item for item in candidates if item[5].distance(split_point) < 0.05]
        node = self._new_node_id()
        wgs84_point = transform(self.airport_graph.to_wgs84.transform, split_point)
        with self._edit():
            self.graph.add_node(node, pos=wgs84_point.coords[0], source="manual")
            for _, u, v, key, data, projected in affected:
                self._split_edge(u, v, key, data, projected, split_point, node)
        return node

    def split_edges_at_node(self, node: Any) -> int:
        with self.lock:
            return self._split_edges_at_node(node)

    def _split_edges_at_node(self, node: Any) -> int:
        longitude, latitude = self.graph.nodes[node]["pos"][:2]
        point = self.airport_graph.project_shape(Point(longitude, latitude))
        affected = []
        for u, v, key, data in self.graph.edges(keys=True, data=True):
            if node in {u, v}:
                continue
            geometry = data.get("geometry")
            if geometry is None:
                continue
            projected = self.airport_graph.project_shape(geometry)
            if projected.distance(point) > self.tolerance_m:
                continue
            distance = projected.project(point)
            if 0.05 < distance < projected.length - 0.05:
                affected.append((u, v, key, deepcopy(data), projected))

        if not affected:
            raise ValueError(f"{self.tolerance_m:g} 米范围内没有可在此节点切分的边")

        with self._edit():
            for u, v, key, data, projected in affected:
                snapped = projected.interpolate(projected.project(point))
                self._split_edge(u, v, key, data, projected, snapped, node)
        return len(affected)

    def source_split_preview(
        self, u: Any, v: Any, key: Any, longitude: float, latitude: float
    ) -> dict[str, Any]:
        data = self.graph.edges[u, v, key]
        click = Point(self.airport_graph.project.transform(longitude, latitude))
        projected_edge = self.airport_graph.project_shape(data["geometry"])
        edge_station = projected_edge.project(click)
        if not 0.05 < edge_station < projected_edge.length - 0.05:
            raise ValueError("切分位置必须位于当前派生边内部")
        segments = edge_source_segments(data)
        if not segments:
            raise ValueError("该派生边没有可用于切分的 SourceSegment")
        segment_candidates = []
        for segment_index, segment in enumerate(segments):
            piece = self.airport_graph.project_shape(
                geometry_from_source_interval(
                    self.airport_graph,
                    segment.source_id,
                    segment.source_start_m,
                    segment.source_end_m,
                )
            )
            segment_candidates.append((piece.distance(click), segment_index, segment, piece))
        _distance, segment_index, segment, _piece = min(segment_candidates)
        source_id = segment.source_id
        source = self.airport_graph.get_source_edge(source_id)
        projected_source = self.airport_graph.project_shape(source.geometry)
        station = projected_source.project(click)
        start_m, end_m = segment.source_start_m, segment.source_end_m
        station = max(start_m, min(end_m, station))
        candidates = []
        for index, (osm_node_id, coordinate) in enumerate(
            zip(source.osm_node_ids, projected_source.coords)
        ):
            node_station = projected_source.project(Point(coordinate))
            if not start_m - 1e-3 <= node_station <= end_m + 1e-3:
                continue
            distance = Point(coordinate).distance(click)
            if distance <= self.tolerance_m:
                candidates.append(
                    {
                        "osm_node_id": osm_node_id,
                        "canonical_node_id": self.airport_graph.canonical_node_id(osm_node_id),
                        "source_index": index,
                        "distance_m": distance,
                        "source_station_m": node_station,
                        "position": source.geometry.coords[index],
                    }
                )
        candidates.sort(key=lambda item: item["distance_m"])
        snapped = projected_source.interpolate(station)
        manual_position = self.airport_graph.to_wgs84.transform(*snapped.coords[0])
        return {
            "source_id": source_id,
            "segment_index": segment_index,
            "source_reversed": segment.reversed,
            "edge": repr((u, v, key)),
            "candidates": candidates,
            "recommended_node": candidates[0]["canonical_node_id"] if candidates else None,
            "manual_position": manual_position,
            "manual_station_m": station,
        }

    def manual_snap_preview(self, node: Any, u: Any, v: Any, key: Any) -> dict[str, Any]:
        """Preview an explicit user-selected graph-node to source-edge snap."""
        if node not in self.graph:
            raise ValueError("待吸附节点不存在")
        if node in {u, v}:
            raise ValueError("该节点已经是目标边的拓扑端点")
        longitude, latitude = self.graph.nodes[node]["pos"][:2]
        split = self.source_split_preview(u, v, key, longitude, latitude)
        source = self.airport_graph.get_source_edge(split["source_id"])
        projected_source = self.airport_graph.project_shape(source.geometry)
        station = float(split["manual_station_m"])
        snapped = projected_source.interpolate(station)
        original = Point(self.airport_graph.project.transform(longitude, latitude))
        distance_m = original.distance(snapped)
        if distance_m > MANUAL_NODE_TO_EDGE_MAX_DISTANCE_M:
            raise ValueError(
                f"节点距离目标边 {distance_m:.3f} m，超过人工吸附上限 "
                f"{MANUAL_NODE_TO_EDGE_MAX_DISTANCE_M:.3f} m"
            )
        snapped_position = tuple(self.airport_graph.to_wgs84.transform(*snapped.coords[0]))
        return {
            "node": repr(node),
            "edge": repr((u, v, key)),
            "original_position": (longitude, latitude),
            "snapped_position": snapped_position,
            "distance_m": distance_m,
            "target_source_id": split["source_id"],
            "target_station_m": station,
            "segment_index": split["segment_index"],
            "target_geometry": mapping(self.graph.edges[u, v, key]["geometry"]),
            "connector_geometry": mapping(
                LineString([(longitude, latitude), snapped_position])
            ),
            "source_edge_unchanged": True,
        }

    def _split_source_chain_with_existing_node(
        self,
        u: Any,
        v: Any,
        key: Any,
        node: Any,
        segment_index: int,
        station: float,
    ) -> list[tuple[Any, Any, Any]]:
        data = deepcopy(self.graph.edges[u, v, key])
        segments = edge_source_segments(data)
        segment = segments[segment_index]
        before, after = list(segments[:segment_index]), list(segments[segment_index + 1 :])
        if segment.reversed:
            if station < segment.source_end_m - 1e-3:
                before.append(SourceSegment(segment.source_id, station, segment.source_end_m, True))
            if station > segment.source_start_m + 1e-3:
                after.insert(
                    0,
                    SourceSegment(segment.source_id, segment.source_start_m, station, True),
                )
        else:
            if station > segment.source_start_m + 1e-3:
                before.append(SourceSegment(segment.source_id, segment.source_start_m, station))
            if station < segment.source_end_m - 1e-3:
                after.insert(0, SourceSegment(segment.source_id, station, segment.source_end_m))
        left_segments = compact_source_segments(before)
        right_segments = compact_source_segments(after)
        if not left_segments or not right_segments:
            raise ValueError("人工吸附位置不能与目标边端点重合")
        first, last = data.get("first", u), data.get("last", v)
        left_data, right_data = deepcopy(data), deepcopy(data)
        left_data.update(
            geometry=geometry_from_source_segments(
                self.airport_graph, left_segments, first, node
            ),
            first=first,
            last=node,
        )
        right_data.update(
            geometry=geometry_from_source_segments(
                self.airport_graph, right_segments, node, last
            ),
            first=node,
            last=last,
        )
        apply_source_segments(left_data, left_segments)
        apply_source_segments(right_data, right_segments)
        for edge_data, chain in ((left_data, left_segments), (right_data, right_segments)):
            if len(chain) == 1:
                only = chain[0]
                edge_data["source_type"] = self.airport_graph.get_source_edge(
                    only.source_id
                ).source_type
                edge_data["osm_node_ids"] = self._source_nodes_in_interval(
                    only.source_id, only.source_start_m, only.source_end_m
                )
            length_m = self.airport_graph.length(edge_data["geometry"])
            if "length" in edge_data:
                edge_data["length"] = length_m
            if "length_m" in edge_data:
                edge_data["length_m"] = length_m
        self.graph.remove_edge(u, v, key)
        left_key = self.graph.add_edge(first, node, **left_data)
        right_key = self.graph.add_edge(node, last, **right_data)
        return [(first, node, left_key), (node, last, right_key)]

    def manual_snap_node_to_edge(self, node: Any, u: Any, v: Any, key: Any) -> None:
        preview = self.manual_snap_preview(node, u, v, key)
        original_position = tuple(self.graph.nodes[node]["pos"][:2])
        incident = [
            (eu, ev, edge_key)
            for eu, ev, edge_key in self.graph.edges(node, keys=True)
            if (eu, ev, edge_key) != (u, v, key)
        ]
        with self._edit():
            self.graph.nodes[node]["pos"] = tuple(preview["snapped_position"])
            changed_edges = []
            for eu, ev, edge_key in incident:
                data = self.graph.edges[eu, ev, edge_key]
                segments = edge_source_segments(data)
                first, last = data.get("first", eu), data.get("last", ev)
                data["geometry"] = geometry_from_source_segments(
                    self.airport_graph, segments, first, last
                )
                length_m = self.airport_graph.length(data["geometry"])
                if "length" in data:
                    data["length"] = length_m
                if "length_m" in data:
                    data["length_m"] = length_m
                changed_edges.append((eu, ev, edge_key))
            changed_edges.extend(
                self._split_source_chain_with_existing_node(
                    u,
                    v,
                    key,
                    node,
                    int(preview["segment_index"]),
                    float(preview["target_station_m"]),
                )
            )
            self.airport_graph.node_snap_records.append(
                NodeSnapRecord(
                    node,
                    original_position,
                    tuple(preview["snapped_position"]),
                    preview["target_source_id"],
                    preview["target_station_m"],
                    preview["distance_m"],
                )
            )
            validate_edge_endpoints(self.airport_graph, edge_ids=changed_edges)
            validate_edge_sources(self.airport_graph, edge_ids=changed_edges)

    def split_source_edge(
        self,
        u: Any,
        v: Any,
        key: Any,
        longitude: float,
        latitude: float,
        osm_node_id: Any | None = None,
    ) -> Any:
        preview = self.source_split_preview(u, v, key, longitude, latitude)
        data = deepcopy(self.graph.edges[u, v, key])
        segments = edge_source_segments(data)
        if osm_node_id is not None:
            canonical = self.airport_graph.canonical_node_id(osm_node_id)
            candidate = next(
                (item for item in preview["candidates"] if item["canonical_node_id"] == canonical),
                None,
            )
            if candidate is None:
                raise ValueError("所选 OSM Node 不属于当前 SourceEdge 切分候选")
            node = canonical
            position = tuple(candidate["position"][:2])
            split_station = float(candidate["source_station_m"])
            attributes = {
                "source_type": "osm",
                "osm_node_ids": self.airport_graph.get_source_node(node).osm_node_ids,
            }
        else:
            if preview["candidates"]:
                raise ValueError("当前位置已有可用 OSM Node，必须优先使用它切分")
            node = self._new_node_id()
            position = tuple(preview["manual_position"][:2])
            split_station = float(preview["manual_station_m"])
            attributes = {"source_type": "manual", "source": "manual"}
        segment_index = int(preview["segment_index"])
        segment = segments[segment_index]
        station = split_station
        before, after = list(segments[:segment_index]), list(segments[segment_index + 1 :])
        if segment.reversed:
            if station < segment.source_end_m - 1e-3:
                before.append(SourceSegment(segment.source_id, station, segment.source_end_m, True))
            if station > segment.source_start_m + 1e-3:
                after.insert(
                    0,
                    SourceSegment(segment.source_id, segment.source_start_m, station, True),
                )
        else:
            if station > segment.source_start_m + 1e-3:
                before.append(SourceSegment(segment.source_id, segment.source_start_m, station))
            if station < segment.source_end_m - 1e-3:
                after.insert(0, SourceSegment(segment.source_id, station, segment.source_end_m))
        left_segments = compact_source_segments(before)
        right_segments = compact_source_segments(after)
        if not left_segments or not right_segments:
            raise ValueError("切分位置不能与派生边端点重合")
        with self._edit():
            if node not in self.graph:
                self.graph.add_node(node, pos=position, **attributes)
            first, last = data.get("first", u), data.get("last", v)
            left_data, right_data = deepcopy(data), deepcopy(data)
            left_data.update(
                geometry=geometry_from_source_segments(
                    self.airport_graph, left_segments, first, node
                ),
                first=first,
                last=node,
            )
            right_data.update(
                geometry=geometry_from_source_segments(
                    self.airport_graph, right_segments, node, last
                ),
                first=node,
                last=last,
            )
            apply_source_segments(left_data, left_segments)
            apply_source_segments(right_data, right_segments)
            for edge_data, chain in ((left_data, left_segments), (right_data, right_segments)):
                if len(chain) == 1:
                    only = chain[0]
                    edge_data["source_type"] = self.airport_graph.get_source_edge(
                        only.source_id
                    ).source_type
                    edge_data["osm_node_ids"] = self._source_nodes_in_interval(
                        only.source_id, only.source_start_m, only.source_end_m
                    )
            self.graph.remove_edge(u, v, key)
            self.graph.add_edge(first, node, **left_data)
            self.graph.add_edge(node, last, **right_data)
            validate_edge_endpoints(self.airport_graph)
            validate_edge_sources(self.airport_graph)
        return node

    @staticmethod
    def _intersection_points(geometry: Any) -> list[Point]:
        if geometry.geom_type == "Point":
            return [geometry]
        if geometry.geom_type == "MultiPoint":
            return list(geometry.geoms)
        if geometry.geom_type in {"GeometryCollection", "MultiLineString"}:
            return [part for part in geometry.geoms if part.geom_type == "Point"]
        return []

    def _split_edge(
        self,
        u: Any,
        v: Any,
        key: Any,
        data: dict[str, Any],
        projected: LineString,
        point: Point,
        node: Any,
    ) -> None:
        first = data.get("first", u)
        last = data.get("last", v)
        snapped = projected.interpolate(projected.project(point))
        distance = projected.project(snapped)
        left = substring(projected, 0, distance)
        right = substring(projected, distance, projected.length)
        if (
            not isinstance(left, LineString)
            or not isinstance(right, LineString)
            or left.length == 0
            or right.length == 0
        ):
            raise ValueError("切分位置不能与原边端点重合")
        source_id = data.get("source_id")
        if source_id in source_registry(self.airport_graph):
            source_line = self.airport_graph.project_shape(
                source_registry(self.airport_graph)[source_id].geometry
            )
            source_distance = source_line.project(point)
            start_m = float(data["source_start_m"])
            end_m = float(data["source_end_m"])
            left_wgs84 = geometry_from_source_interval(
                self.airport_graph, source_id, start_m, source_distance, first, node
            )
            right_wgs84 = geometry_from_source_interval(
                self.airport_graph, source_id, source_distance, end_m, node, last
            )
        else:
            source_distance = distance
            start_m = 0.0
            end_m = projected.length
            left_wgs84 = transform(self.airport_graph.to_wgs84.transform, left)
            right_wgs84 = transform(self.airport_graph.to_wgs84.transform, right)
        original_id = repr((u, v, key))
        left_data = deepcopy(data)
        right_data = deepcopy(data)
        left_data.update(
            geometry=left_wgs84,
            first=first,
            last=node,
            split_from=source_id or original_id,
            source_start_m=start_m,
            source_end_m=source_distance,
        )
        right_data.update(
            geometry=right_wgs84,
            first=node,
            last=last,
            split_from=source_id or original_id,
            source_start_m=source_distance,
            source_end_m=end_m,
        )
        if source_id in source_registry(self.airport_graph):
            apply_source_segments(left_data, (SourceSegment(source_id, start_m, source_distance),))
            apply_source_segments(right_data, (SourceSegment(source_id, source_distance, end_m),))
            left_data["osm_node_ids"] = self._source_nodes_in_interval(
                source_id, start_m, source_distance
            )
            right_data["osm_node_ids"] = self._source_nodes_in_interval(
                source_id, source_distance, end_m
            )
        for name in ("length", "length_m"):
            if name in data:
                left_data[name] = left.length
                right_data[name] = right.length
        self.graph.remove_edge(u, v, key)
        self.graph.add_edge(first, node, **left_data)
        self.graph.add_edge(node, last, **right_data)

    def _source_nodes_in_interval(
        self, source_id: str, start_m: float, end_m: float
    ) -> tuple[Any, ...]:
        """Return the original OSM nodes covered by one source interval."""
        source = self.airport_graph.get_source_edge(source_id)
        projected = self.airport_graph.project_shape(source.geometry)
        result = []
        for node_id, coordinate in zip(source.osm_node_ids, projected.coords):
            station = projected.project(Point(coordinate))
            if start_m - 1e-3 <= station <= end_m + 1e-3:
                result.append(node_id)
        return tuple(result)

    def reconnect_preview(
        self, u: Any, v: Any, key: Any, replace_node: Any, target_node: Any
    ) -> dict[str, Any]:
        data = self.graph.edges[u, v, key]
        source_id = data.get("source_id")
        if source_id not in source_registry(self.airport_graph):
            raise ValueError("该边没有可用于重连的原始 SourceEdge")
        boundaries = source_boundaries(self.airport_graph, source_id)
        boundary_nodes = {node for _, node in boundaries}
        if replace_node not in {u, v} or replace_node not in boundary_nodes:
            raise ValueError("所选端点不是源边端点或现有切分点")
        source_line = self.airport_graph.project_shape(
            source_registry(self.airport_graph)[source_id].geometry
        )
        target_position = self.graph.nodes[target_node]["pos"][:2]
        target_point = Point(self.airport_graph.project.transform(*target_position))
        if source_line.distance(target_point) > MANUAL_SOURCE_TOLERANCE_M:
            raise ValueError("目标节点不在原始 LineString 的允许误差内")
        return {
            "source_id": source_id,
            "source_geometry": mapping(source_registry(self.airport_graph)[source_id].geometry),
            "source_endpoints": [
                source_registry(self.airport_graph)[source_id].geometry.coords[0],
                source_registry(self.airport_graph)[source_id].geometry.coords[-1],
            ],
            "current_endpoints": [repr(u), repr(v)],
            "new_endpoints": [
                repr(target_node if u == replace_node else u),
                repr(target_node if v == replace_node else v),
            ],
            "replace_node": replace_node,
            "target_node": target_node,
        }

    def reconnect_source_edge(
        self, u: Any, v: Any, key: Any, replace_node: Any, target_node: Any
    ) -> None:
        preview = self.reconnect_preview(u, v, key, replace_node, target_node)
        source_id = preview["source_id"]
        source_line = self.airport_graph.project_shape(
            source_registry(self.airport_graph)[source_id].geometry
        )
        target_position = self.graph.nodes[target_node]["pos"][:2]
        target_point = Point(self.airport_graph.project.transform(*target_position))
        target_station = source_line.project(target_point)
        boundaries = [
            item
            for item in source_boundaries(self.airport_graph, source_id)
            if item[1] != replace_node
        ]
        if target_node not in {node for _, node in boundaries}:
            boundaries.append((target_station, target_node))
        with self._edit():
            rebuild_source_edges(self.airport_graph, source_id, sorted(boundaries))
            validate_edge_endpoints(self.airport_graph, MANUAL_SOURCE_TOLERANCE_M)


def _serve_workbench(
    airport_graph: AirportGraph,
    *,
    flights: Sequence[Flight] = (),
    paths_by_flight_key: Mapping[str, Path] | None = None,
    save_path: str | FilePath = DEFAULT_GRAPH_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    read_only: bool = False,
    match_config: Any | None = None,
    flight_sources: Sequence[str] | None = None,
    movement_types: Sequence[str] | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
) -> AirportGraph:
    """Serve the shared workbench UI in editing or read-only mode."""
    import uvicorn

    from .app import create_app

    session = EditorSession(airport_graph)
    server: uvicorn.Server

    def finish() -> None:
        threading.Timer(0.2, setattr, args=(server, "should_exit", True)).start()

    app = create_app(
        session,
        FilePath(save_path),
        on_finish=finish,
        flights=flights,
        paths_by_flight_key=paths_by_flight_key,
        read_only=read_only,
        match_config=match_config,
        flight_sources=flight_sources,
        movement_types=movement_types,
        input_time_semantics=input_time_semantics,
        display_timezone=display_timezone,
    )
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    if open_browser:
        url = f"http://{host}:{port}/?session={time.time_ns()}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    server.run()
    return session.airport_graph


def open_workbench(
    airport_graph: AirportGraph,
    *,
    flights: Sequence[Flight] = (),
    paths_by_flight_key: Mapping[str, Path] | None = None,
    save_path: str | FilePath = DEFAULT_GRAPH_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    match_config: Any | None = None,
    flight_sources: Sequence[str] | None = None,
    movement_types: Sequence[str] | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
) -> AirportGraph:
    """Open the editable workbench and block until it is stopped or finished."""
    return _serve_workbench(
        airport_graph,
        flights=flights,
        paths_by_flight_key=paths_by_flight_key,
        save_path=save_path,
        host=host,
        port=port,
        open_browser=open_browser,
        match_config=match_config,
        flight_sources=flight_sources,
        movement_types=movement_types,
        input_time_semantics=input_time_semantics,
        display_timezone=display_timezone,
    )


def visualize(
    airport_graph: AirportGraph,
    *,
    flights: Sequence[Flight] = (),
    paths_by_flight_key: Mapping[str, Path] | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    match_config: Any | None = None,
    flight_sources: Sequence[str] | None = None,
    movement_types: Sequence[str] | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
) -> None:
    """Open a read-only graph viewer with search and topology inspection tools."""
    _serve_workbench(
        airport_graph,
        flights=flights,
        paths_by_flight_key=paths_by_flight_key,
        host=host,
        port=port,
        open_browser=open_browser,
        read_only=True,
        match_config=match_config,
        flight_sources=flight_sources,
        movement_types=movement_types,
        input_time_semantics=input_time_semantics,
        display_timezone=display_timezone,
    )


def edit_graph(
    airport_graph: AirportGraph,
    *,
    save_path: str | FilePath = DEFAULT_GRAPH_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> AirportGraph:
    """Backward-compatible graph-only editing entry point."""
    return open_workbench(
        airport_graph,
        save_path=save_path,
        host=host,
        port=port,
        open_browser=open_browser,
    )
