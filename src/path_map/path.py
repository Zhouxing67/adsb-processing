"""A compact representation of a directed walk through an airport graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Hashable, Iterator, Sequence

from shapely.geometry import LineString
from shapely.ops import linemerge

from airport_surface import AirportGraph, graph_id


@dataclass(frozen=True, slots=True)
class DirectedEdge:
    """
    路径中的一条由u到v的边。
    ``from_`` 和 ``to_`` 是边两端的节点 ID；``key_`` 用于区分 MultiGraph 中
    连接同一对节点的多条平行边。三者共同确定一条具体的边。
    """

    from_: Hashable
    to_: Hashable
    key_: Hashable

    @property
    def id(self) -> tuple[Hashable, Hashable, Hashable]:
        return self.from_, self.to_, self.key_


class Path(Sequence[DirectedEdge]):
    """AirportGraph 上有顺序、有方向且拓扑连续的路径。

    ``Path`` 只保存对机场图的引用，不复制整个图。``edges`` 按飞机实际经过
    的先后顺序保存。允许空路径，也允许重复经过同一条边，以表达折返或环路。
    """

    def __init__(
        self,
        airport_graph: AirportGraph,
        edges: Sequence[DirectedEdge | tuple[Hashable, Hashable, Hashable]],
    ) -> None:
        self.airport_graph = airport_graph
        self._edges = tuple(e if isinstance(e, DirectedEdge) else DirectedEdge(*e) for e in edges)
        self.validate()

    def __len__(self) -> int:
        return len(self._edges)

    def __getitem__(self, index: int | slice) -> DirectedEdge | tuple[DirectedEdge, ...]:
        return self._edges[index]

    def __iter__(self) -> Iterator[DirectedEdge]:
        return iter(self._edges)

    @property
    def edges(self) -> tuple[DirectedEdge, ...]:
        """按实际遍历顺序返回有向边序列。"""
        return self._edges

    @property
    def edge_ids(self) -> tuple[tuple[Hashable, Hashable, Hashable], ...]:
        """返回每条边的完整标识 ``(from_, to_, key_)``。"""
        return tuple(edge.id for edge in self)

    @property
    def nodes(self) -> tuple[Any, ...]:
        """根据边序列生成按遍历顺序排列的节点序列。"""
        if not self._edges:
            return ()
        return (self._edges[0].from_, *(edge.to_ for edge in self._edges))

    def validate(self) -> None:
        """检查所有边存在于图中，并检查相邻边是否首尾相接。"""
        for edge in self._edges:
            if not self.airport_graph.graph.has_edge(edge.from_, edge.to_, edge.key_):
                raise ValueError(f"Unknown graph edge: {(edge.from_, edge.to_, edge.key_)!r}")
        for left, right in zip(self._edges, self._edges[1:]):
            if left.to_ != right.from_:
                raise ValueError(f"Discontinuous path between {left!r} and {right!r}")

    def oriented_geometry(self, edge: DirectedEdge) -> LineString:
        """返回坐标顺序与 ``edge.from_ -> edge.to_`` 遍历方向一致的边几何。"""
        graph = self.airport_graph.graph
        geometry = graph.edges[edge.from_, edge.to_, edge.key_]["geometry"]
        node_position = graph.nodes[edge.from_].get("pos")
        if node_position is None:
            data: dict[str, Any] = graph.edges[edge.from_, edge.to_, edge.key_]
            forward = data.get("first") == edge.from_
        else:
            forward = geometry.coords[0][:2] == tuple(node_position)[:2]
            if not forward:
                # OSM coordinates can differ by tiny floating point noise.
                from shapely.geometry import Point

                forward = Point(geometry.coords[0]).distance(Point(node_position)) <= Point(
                    geometry.coords[-1]
                ).distance(Point(node_position))
        return geometry if forward else LineString(reversed(geometry.coords))

    @property
    def geometry(self) -> LineString:
        """将所有有向边按遍历顺序拼接为一条完整路径几何。"""
        if not self._edges:
            return LineString()
        pieces = [self.oriented_geometry(edge) for edge in self._edges]
        merged = linemerge(pieces)
        if isinstance(merged, LineString):
            return merged
        # A valid walk may retrace an edge; concatenation preserves that order.
        coords = list(pieces[0].coords)
        for piece in pieces[1:]:
            coords.extend(list(piece.coords)[1:])
        return LineString(coords)

    @property
    def total_length(self) -> float:
        """返回路径总长度；重复经过的边会重复计入。单位为米。"""
        return sum(
            self.airport_graph.length(
                self.airport_graph.graph.edges[e.from_, e.to_, e.key_]["geometry"]
            )
            for e in self._edges
        )


class PathGraphMismatch(ValueError):
    """Raised when a persisted path is resolved against a different graph."""


@dataclass(frozen=True, slots=True)
class PathRecord:
    """Minimal persistent representation of a path tied to one exact graph."""

    graph_id: str
    edges: tuple[DirectedEdge, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "edges",
            tuple(
                edge if isinstance(edge, DirectedEdge) else DirectedEdge(*edge)
                for edge in self.edges
            ),
        )

    @classmethod
    def from_path(cls, path: Path) -> PathRecord:
        return cls(graph_id(path.airport_graph), path.edges)

    def resolve(self, airport_graph: AirportGraph) -> Path:
        actual_graph_id = graph_id(airport_graph)
        if actual_graph_id != self.graph_id:
            raise PathGraphMismatch(
                f"Path requires graph {self.graph_id!r}, got {actual_graph_id!r}"
            )
        return Path(airport_graph, self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "edges": [[edge.from_, edge.to_, edge.key_] for edge in self.edges],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PathRecord:
        return cls(
            graph_id=str(value["graph_id"]),
            edges=tuple(DirectedEdge(*edge) for edge in value["edges"]),
        )
