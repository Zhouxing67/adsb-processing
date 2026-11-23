"""Build, validate, save, and load airport surface graphs."""

from .identifiers import EdgeId, EdgeKey, NodeId, OsmId
from .models import (
    AirportGraph,
    GraphMetadata,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
    mutable_source_attributes,
)
from .persistence import DEFAULT_GRAPH_PATH, graph_id, load_graph, save_graph
from .source_chain import cumulative_distances, geometry_from_source_segments
from .validation import (
    validate_edge_endpoints,
    validate_edge_sources,
    validate_source_intervals,
)

__all__ = [
    "AirportGraph",
    "DEFAULT_GRAPH_PATH",
    "GraphMetadata",
    "EdgeId",
    "EdgeKey",
    "NodeId",
    "OsmId",
    "SourceEdge",
    "SourceNode",
    "SourceSegment",
    "cumulative_distances",
    "edge_source_segments",
    "mutable_source_attributes",
    "geometry_from_source_segments",
    "graph_id",
    "load_graph",
    "save_graph",
    "validate_edge_endpoints",
    "validate_edge_sources",
    "validate_source_intervals",
]
