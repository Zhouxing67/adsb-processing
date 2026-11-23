"""Schema-v2 JSON persistence and content identity hashing for AirportGraph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import networkx as nx
from pyproj import Proj
from shapely.geometry import LineString, mapping, shape

from utils.json_value import to_json_value

from .models import AirportGraph, GraphMetadata, SourceEdge, SourceNode, edge_source_segments

DEFAULT_GRAPH_PATH = Path("data/graphs/zbaa_final.json")
GRAPH_SCHEMA_VERSION = 2


def _graph_document(airport_graph: AirportGraph) -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "airport": airport_graph.metadata.airport,
        "projection": airport_graph.projection.srs,
        "build_issues": list(airport_graph.metadata.build_issues),
        "source_nodes": {
            str(node_id): {
                "node_id": to_json_value(source.node_id),
                "position": to_json_value(source.position),
                "osm_node_ids": to_json_value(source.osm_node_ids),
                "attributes": to_json_value(dict(source.attributes)),
            }
            for node_id, source in airport_graph.source_nodes.items()
        },
        "node_aliases": [
            [to_json_value(alias), to_json_value(canonical)]
            for alias, canonical in airport_graph.node_aliases.items()
        ],
        "source_edges": {
            source_id: {
                "geometry": mapping(source.geometry),
                "source_type": source.source_type,
                "osm_way_id": to_json_value(source.osm_way_id),
                "osm_node_ids": to_json_value(source.osm_node_ids),
                "attributes": to_json_value(dict(source.attributes)),
            }
            for source_id, source in airport_graph.source_edges.items()
        },
        "nodes": [
            {
                "id": to_json_value(node),
                "pos": to_json_value(data["pos"]),
                "attributes": to_json_value(
                    {key: value for key, value in data.items() if key != "pos"}
                ),
            }
            for node, data in airport_graph.graph.nodes(data=True)
        ],
        "edges": [
            {
                "u": to_json_value(u),
                "v": to_json_value(v),
                "key": to_json_value(key),
                "geometry": mapping(data["geometry"]),
                "attributes": to_json_value(
                    {name: value for name, value in data.items() if name != "geometry"}
                ),
            }
            for u, v, key, data in airport_graph.graph.edges(keys=True, data=True)
        ],
    }


def _document_graph_id(document: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in document.items() if key != "graph_id"}
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def graph_id(airport_graph: AirportGraph) -> str:
    """Return the content identity of the graph in its persistent representation."""
    return _document_graph_id(_graph_document(airport_graph))


def save_graph(airport_graph: AirportGraph, path: str | Path = DEFAULT_GRAPH_PATH) -> Path:
    """Write ``airport_graph`` atomically as a schema-v2 JSON document."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    document = _graph_document(airport_graph)
    document["graph_id"] = _document_graph_id(document)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def load_graph(path: str | Path = DEFAULT_GRAPH_PATH) -> AirportGraph:
    """Load and hash-verify a schema-v2 AirportGraph JSON document."""
    source_path = Path(path)
    document = json.loads(source_path.read_text(encoding="utf-8"))
    schema_version = document.get("schema_version")
    if schema_version != GRAPH_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported airport graph schema version: {schema_version!r}; "
            f"expected {GRAPH_SCHEMA_VERSION}"
        )
    declared_graph_id = document.get("graph_id")
    if declared_graph_id is not None:
        actual_graph_id = _document_graph_id(document)
        if declared_graph_id != actual_graph_id:
            raise ValueError(
                f"Airport graph content does not match graph_id: "
                f"expected {declared_graph_id!r}, got {actual_graph_id!r}"
            )

    # Legacy top-level business collections are deliberately ignored after hash validation.
    # Semantic attributes are authoritative; old collections must not create new labels.
    graph = nx.MultiGraph()
    for node in document["nodes"]:
        graph.add_node(node["id"], pos=tuple(node["pos"]), **node["attributes"])
    for edge in document["edges"]:
        attributes = dict(edge["attributes"])
        if "source_segments" in attributes:
            attributes["source_segments"] = edge_source_segments(attributes)
        graph.add_edge(
            edge["u"],
            edge["v"],
            key=edge["key"],
            geometry=shape(edge["geometry"]),
            **attributes,
        )

    source_nodes = {
        item["node_id"]: SourceNode(
            item["node_id"],
            tuple(item["position"]),
            tuple(item.get("osm_node_ids", (item["node_id"],))),
            item.get("attributes", {}),
        )
        for item in document.get("source_nodes", {}).values()
    }
    source_edges: dict[str, SourceEdge] = {}
    for source_id, item in document.get("source_edges", {}).items():
        geometry = shape(item["geometry"])
        if not isinstance(geometry, LineString):
            raise ValueError(
                f"Source {source_id!r} requires LineString geometry, got {geometry.geom_type}"
            )
        source_edges[source_id] = SourceEdge(
            source_id,
            geometry,
            item["source_type"],
            item.get("osm_way_id"),
            tuple(item.get("osm_node_ids", ())),
            item.get("attributes", {}),
        )
    metadata = GraphMetadata(
        airport=document.get("airport", "ZBAA"),
        build_issues=tuple(document.get("build_issues", ())),
    )
    projection_value = document.get("projection", "UTM zone 50")
    projection = Proj("EPSG:32650") if projection_value == "UTM zone 50" else Proj(projection_value)
    return AirportGraph(
        graph,
        projection,
        source_nodes=source_nodes,
        source_edges=source_edges,
        node_aliases=dict(document.get("node_aliases", ())),
        metadata=metadata,
    )
