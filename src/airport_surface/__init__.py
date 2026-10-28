"""Build, save, and load the ZBAA airport surface graph."""

from typing import Any

from .graph import (
    DEFAULT_GRAPH_PATH,
    geometry_from_source_segments,
    graph_id,
    load_graph,
    save_graph,
    source_registry,
    validate_edge_endpoints,
    validate_edge_sources,
    validate_source_intervals,
)
from .models import (
    AirportGraph,
    GraphMetadata,
    NodeMergeGroup,
    NodeSnapRecord,
    SourceEdge,
    SourceNode,
    SourceSegment,
    edge_source_segments,
)


def edit_graph(*args: Any, **kwargs: Any) -> Any:
    """Compatibility wrapper for :func:`airport_workbench.edit_graph`."""
    from airport_workbench import edit_graph as workbench_edit_graph

    return workbench_edit_graph(*args, **kwargs)


def __getattr__(name: str) -> Any:
    if name == "EditorSession":
        from airport_workbench import EditorSession

        return EditorSession
    raise AttributeError(name)


__all__ = [
    "AirportGraph",
    "DEFAULT_GRAPH_PATH",
    "GraphMetadata",
    "NodeMergeGroup",
    "NodeSnapRecord",
    "SourceEdge",
    "SourceNode",
    "SourceSegment",
    "EditorSession",
    "edit_graph",
    "edge_source_segments",
    "geometry_from_source_segments",
    "graph_id",
    "load_graph",
    "save_graph",
    "source_registry",
    "validate_edge_endpoints",
    "validate_edge_sources",
    "validate_source_intervals",
]
