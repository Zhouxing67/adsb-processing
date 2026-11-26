"""Cached GeoJSON and topology state builder for the airport graph workbench."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path as FilePath
from typing import Any

import networkx as nx
from shapely.geometry import LineString, mapping

from utils.json_value import to_json_value

from .editor import EditorSession

VALIDATION_EDGE_COLORS = (
    "#406c80",
    "#9a684d",
    "#5f7660",
    "#765f7f",
    "#9a7b3f",
    "#4f6287",
    "#8a5968",
    "#4f7b78",
)


def _edge_colors(graph: Any) -> dict[tuple[Any, Any, Any], str]:
    """Greedily give incident edges strongly contrasting validation colors."""
    used_at_node: dict[Any, set[int]] = defaultdict(set)
    result: dict[tuple[Any, Any, Any], str] = {}
    for u, v, key in graph.edges(keys=True):
        unavailable = used_at_node[u] | used_at_node[v]
        color_index = 0
        while color_index in unavailable:
            color_index += 1
        used_at_node[u].add(color_index)
        used_at_node[v].add(color_index)
        result[(u, v, key)] = (
            VALIDATION_EDGE_COLORS[color_index]
            if color_index < len(VALIDATION_EDGE_COLORS)
            else f"hsl({(18 + color_index * 47) % 360} 38% 42%)"
        )
    return result


class BrowserState:
    """Build and cache revision-keyed graph GeoJSON & topology snapshots."""

    def __init__(self, session: EditorSession) -> None:
        self.session = session
        self._cache_key: tuple[int, bool, str] | None = None
        self._cached_state: dict[str, Any] | None = None

    def state(self, can_finish: bool, save_path: FilePath) -> dict[str, Any]:
        with self.session.lock:
            revision = getattr(self.session, "revision", 0)
            key = (revision, can_finish, str(save_path))
            if self._cache_key == key and self._cached_state is not None:
                return dict(self._cached_state)
            snapshot = self._state(can_finish, save_path)
            self._cache_key = key
            self._cached_state = snapshot
            return dict(snapshot)

    def _state(self, can_finish: bool, save_path: FilePath) -> dict[str, Any]:
        graph = self.session.graph
        components: list[set[Any]] = sorted(
            nx.connected_components(graph), key=len, reverse=True
        )
        component_by_node = {
            node: index + 1 for index, members in enumerate(components) for node in members
        }
        isolated_nodes = [node for node, degree in graph.degree if degree == 0]
        dangling_nodes = [node for node, degree in graph.degree if degree == 1]
        parallel_groups = [
            (u, v, tuple(keyed_edges))
            for u, neighbours in graph.adjacency()
            for v, keyed_edges in neighbours.items()
            if repr(u) <= repr(v) and len(keyed_edges) > 1
        ]
        node_features = []
        runway_interfaces = getattr(self.session.airport_graph, "runway_interfaces", {})
        for node, data in graph.nodes(data=True):
            longitude, latitude = data["pos"][:2]
            degree = graph.degree(node)
            color = (
                "#a34f6a"
                if degree == 0
                else "#808080"
                if data.get("source") == "manual"
                else "#b56f38"
                if degree == 1
                else "#416878"
            )
            node_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                    "properties": {
                        "id": node,
                        "node_type": (
                            "runway_interface"
                            if node in runway_interfaces
                            else "unclassified"
                        ),
                        "longitude": longitude,
                        "latitude": latitude,
                        "degree": degree,
                        "component": component_by_node[node],
                        "topology_role": (
                            "isolated"
                            if degree == 0
                            else "dangling"
                            if degree == 1
                            else "connected"
                        ),
                        "neighbours": ", ".join(graph.neighbors(node)),
                        "editable_attributes": to_json_value(
                            {key: value for key, value in data.items() if key != "pos"}
                        ),
                        "manual": data.get("source") == "manual",
                        "color": color,
                        "radius": 5 if degree == 0 else 4 if degree == 1 else 2.75,
                    },
                }
            )

        edge_features = []
        edge_colors = _edge_colors(graph)
        cluster_for_edge = getattr(self.session.airport_graph, "cluster_for_edge", None)
        for u, v, key, data in graph.edges(keys=True, data=True):
            geometry = data.get("geometry") or LineString(
                [graph.nodes[u]["pos"][:2], graph.nodes[v]["pos"][:2]]
            )
            cluster = cluster_for_edge((u, v, key)) if cluster_for_edge is not None else None
            edge_features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {
                        "id": {"u": u, "v": v, "key": key},
                        "u": u,
                        "v": v,
                        "key": key,
                        "validation_color": edge_colors[(u, v, key)],
                        "geometry_length_m": round(self.session.airport_graph.length(geometry), 2),
                        "source_type": data.get("source_type"),
                        "aeroway": data.get("aeroway"),
                        "name": data.get("name"),
                        "ref": data.get("ref"),
                        "cluster_id": cluster.c_id if cluster is not None else None,
                        "editable_attributes": to_json_value(
                            {
                                name: value
                                for name, value in data.items()
                                if name not in {"geometry", "first", "last"}
                            }
                        ),
                    },
                }
            )
        raw_clusters = getattr(self.session.airport_graph, "stand_clusters", {})
        stand_clusters = [
            {
                "c_id": cluster.c_id,
                "name": cluster.name,
                "stands": [
                    {"u": u, "v": v, "key": edge_key}
                    for u, v, edge_key in cluster.stands
                ],
                "stand_refs": list(self.session.airport_graph.stand_refs_in_cluster(cluster.c_id)),
            }
            for cluster in sorted(
                raw_clusters.values(),
                key=lambda item: item.c_id,
            )
        ]
        return {
            "nodes": {"type": "FeatureCollection", "features": node_features},
            "edges": {"type": "FeatureCollection", "features": edge_features},
            "stand_clusters": stand_clusters,
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "flight_count": 0,
            "topology": {
                "component_count": len(components),
                "largest_component": max((len(item) for item in components), default=0),
                "isolated_count": len(isolated_nodes),
                "dangling_count": len(dangling_nodes),
                "parallel_pair_count": len(parallel_groups),
                "isolated_nodes": isolated_nodes[:100],
                "dangling_nodes": dangling_nodes[:100],
                "components": [
                    {
                        "index": index,
                        "size": len(members),
                        "node_ids": list(members),
                    }
                    for index, members in enumerate(components, start=1)
                ],
                "parallel_groups": [
                    {
                        "u": u,
                        "v": v,
                        "edge_ids": [
                            {"u": u, "v": v, "key": edge_key}
                            for edge_key in keys
                        ],
                    }
                    for u, v, keys in parallel_groups
                ],
            },
            "can_undo": self.session.can_undo,
            "can_finish": can_finish,
            "revision": getattr(self.session, "revision", 0),
            "topology_revision": getattr(self.session, "topology_revision", 0),
            "save_path": str(save_path),
        }
