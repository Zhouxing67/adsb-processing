"""Canonical identifier types for airport surface graphs."""

from __future__ import annotations

import re
from numbers import Integral
from typing import Any

type NodeId = str
type OsmId = str
type EdgeKey = int
type EdgeId = tuple[NodeId, NodeId, EdgeKey]

NODE_ID_PATTERN = r"^-?[1-9][0-9]*$"
OSM_ID_PATTERN = r"^[1-9][0-9]*$"
_NODE_ID = re.compile(NODE_ID_PATTERN)
_OSM_ID = re.compile(OSM_ID_PATTERN)


def validate_node_id(value: Any) -> NodeId:
    """Require the canonical decimal string used inside persisted graphs."""
    if not isinstance(value, str) or _NODE_ID.fullmatch(value) is None:
        raise ValueError(f"NodeId must be a canonical nonzero decimal string: {value!r}")
    return value


def normalize_osm_id(value: Any) -> OsmId:
    """Normalize an OSM 64-bit integer at the import boundary."""
    if isinstance(value, bool):
        raise TypeError("Boolean values are not OSM identifiers")
    if isinstance(value, Integral):
        value = str(int(value))
    if not isinstance(value, str) or _OSM_ID.fullmatch(value) is None:
        raise ValueError(f"OSM ID must be a positive canonical decimal integer: {value!r}")
    return value


def validate_edge_key(value: Any) -> EdgeKey:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"EdgeKey must be a nonnegative integer: {value!r}")
    return value
