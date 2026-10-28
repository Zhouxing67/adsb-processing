"""Layered stress tests for the intermittent Windows access violation.

Run one stage per process so a native crash in one layer does not hide the
result of the other layers. Progress is flushed immediately.
"""

from __future__ import annotations

import argparse
import faulthandler
import random
from pathlib import Path
from typing import Any

DEFAULT_GRAPH = Path("data/graphs/zbaa_final.json")
DEFAULT_FLIGHTS = Path("data/ADS-B/more_15_arr.csv")
STAGES = (
    "pure-python",
    "pure-networkx",
    "networkx-internal",
    "real-topology",
    "projected-routing",
    "projection",
    "candidates",
    "full-hmm",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH)
    parser.add_argument("--flights", type=Path, default=DEFAULT_FLIGHTS)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--progress-every", type=int, default=100)
    return parser.parse_args()


def progress(stage: str, current: int, total: int) -> None:
    print(f"[{stage}] {current}/{total}", flush=True)


def stress_routes(graph: Any, iterations: int, progress_every: int, stage: str) -> None:
    import networkx as nx

    nodes = list(graph.nodes)
    if len(nodes) < 2:
        raise ValueError("Routing graph must contain at least two nodes")
    randomizer = random.Random(20261028)
    for iteration in range(1, iterations + 1):
        source = randomizer.choice(nodes)
        nx.dijkstra_predecessor_and_distance(graph, source, weight="length")
        if iteration % progress_every == 0:
            progress(stage, iteration, iterations)


def pure_python(args: argparse.Namespace) -> None:
    """Run a standard-library-only Dijkstra control without NetworkX."""
    from heapq import heappop, heappush

    width = 50
    adjacency: dict[int, dict[int, float]] = {node: {} for node in range(width * width)}
    for row in range(width):
        for column in range(width):
            node = row * width + column
            if column + 1 < width:
                right = node + 1
                adjacency[node][right] = adjacency[right][node] = 1.0
            if row + 1 < width:
                below = node + width
                adjacency[node][below] = adjacency[below][node] = 1.0

    randomizer = random.Random(20261028)
    nodes = list(adjacency)
    for iteration in range(1, args.iterations + 1):
        source = randomizer.choice(nodes)
        distances = {source: 0.0}
        queue = [(0.0, source)]
        while queue:
            distance, node = heappop(queue)
            if distance != distances[node]:
                continue
            for neighbor, weight in adjacency[node].items():
                candidate = distance + weight
                if candidate < distances.get(neighbor, float("inf")):
                    distances[neighbor] = candidate
                    heappush(queue, (candidate, neighbor))
        if len(distances) != len(adjacency):
            raise AssertionError("Dijkstra did not reach the complete grid")
        if iteration % args.progress_every == 0:
            progress("pure-python", iteration, args.iterations)


def pure_networkx(args: argparse.Namespace) -> None:
    import networkx as nx

    # Similar node count to ZBAA, but only Python integers and float weights.
    graph = nx.grid_2d_graph(50, 50)
    nx.set_edge_attributes(graph, 1.0, "length")
    stress_routes(
        graph,
        args.iterations,
        args.progress_every,
        "pure-networkx",
    )


def networkx_internal(args: argparse.Namespace) -> None:
    """Use NetworkX data structures but bypass dispatch/argmap wrappers."""
    import networkx as nx
    from networkx.algorithms.shortest_paths.weighted import _dijkstra, _weight_function

    graph = nx.grid_2d_graph(50, 50)
    nx.set_edge_attributes(graph, 1.0, "length")
    nodes = list(graph.nodes)
    weight = _weight_function(graph, "length")
    randomizer = random.Random(20261028)
    for iteration in range(1, args.iterations + 1):
        source = randomizer.choice(nodes)
        distances = _dijkstra(graph, source, weight)
        if len(distances) != len(nodes):
            raise AssertionError("Dijkstra did not reach the complete grid")
        if iteration % args.progress_every == 0:
            progress("networkx-internal", iteration, args.iterations)


def real_topology(args: argparse.Namespace, *, projected_lengths: bool) -> None:
    import networkx as nx

    from airport_surface import load_graph

    airport_graph = load_graph(args.graph)
    routing_graph = nx.Graph()
    routing_graph.add_nodes_from(airport_graph.graph.nodes)
    for u, v, data in airport_graph.graph.edges(data=True):
        if projected_lengths:
            length = airport_graph.project_shape(data["geometry"]).length
        else:
            # Topology-only control: no geometry/projection calculation.
            length = 1.0
        previous = routing_graph.get_edge_data(u, v)
        if previous is None or length < previous["length"]:
            routing_graph.add_edge(u, v, length=float(length))
    stress_routes(
        routing_graph,
        args.iterations,
        args.progress_every,
        "projected-routing" if projected_lengths else "real-topology",
    )


def load_observation_arrays(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    from adsb import Flights
    from airport_surface import load_graph

    airport_graph = load_graph(args.graph)
    flights = Flights.from_file(args.flights)
    longitude = flights.data["longitude"].to_numpy(dtype=float)
    latitude = flights.data["latitude"].to_numpy(dtype=float)
    return airport_graph, longitude, latitude


def projection(args: argparse.Namespace) -> None:
    airport_graph, longitude, latitude = load_observation_arrays(args)
    for iteration in range(1, args.iterations + 1):
        airport_graph.project.transform(longitude, latitude)
        if iteration % args.progress_every == 0:
            progress("projection", iteration, args.iterations)


def candidates(args: argparse.Namespace) -> None:
    from shapely.geometry import Point

    from path_map.candidates import CandidateIndex

    airport_graph, longitude, latitude = load_observation_arrays(args)
    x, y = airport_graph.project.transform(longitude, latitude)
    points = [Point(float(px), float(py)) for px, py in zip(x, y)]
    index = CandidateIndex(airport_graph)
    for iteration in range(1, args.iterations + 1):
        point = points[(iteration - 1) % len(points)]
        index.candidates(iteration - 1, point, radius=40.0, maximum=40)
        if iteration % args.progress_every == 0:
            progress("candidates", iteration, args.iterations)


def full_hmm(args: argparse.Namespace) -> None:
    from adsb import Flights
    from airport_surface import load_graph
    from path_map import map_flight

    airport_graph = load_graph(args.graph)
    flights = Flights.from_file(args.flights)
    selected = list(flights.iterate(limit=args.limit))
    for index, flight in enumerate(selected, start=1):
        print(f"[full-hmm] {index}/{len(selected)} {flight.flight_id} START", flush=True)
        map_flight(airport_graph, flight)
        print(f"[full-hmm] {index}/{len(selected)} {flight.flight_id} OK", flush=True)


def main() -> None:
    faulthandler.enable(all_threads=True)
    args = parse_args()
    if args.iterations < 1 or args.limit < 1 or args.progress_every < 1:
        raise ValueError("iterations, limit, and progress-every must be positive")

    if args.stage == "pure-python":
        pure_python(args)
    elif args.stage == "pure-networkx":
        pure_networkx(args)
    elif args.stage == "networkx-internal":
        networkx_internal(args)
    elif args.stage == "real-topology":
        real_topology(args, projected_lengths=False)
    elif args.stage == "projected-routing":
        real_topology(args, projected_lengths=True)
    elif args.stage == "projection":
        projection(args)
    elif args.stage == "candidates":
        candidates(args)
    else:
        full_hmm(args)


if __name__ == "__main__":
    main()
