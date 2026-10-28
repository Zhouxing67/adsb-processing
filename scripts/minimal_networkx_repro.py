"""Minimal NetworkX stress test with no project imports."""

from __future__ import annotations

import argparse
import faulthandler
import random

import networkx as nx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")

    faulthandler.enable(all_threads=True)
    graph = nx.grid_2d_graph(50, 50)
    nx.set_edge_attributes(graph, 1.0, "length")
    nodes = list(graph.nodes)
    randomizer = random.Random(20261028)

    for _ in range(args.iterations):
        source = randomizer.choice(nodes)
        predecessors, distances = nx.dijkstra_predecessor_and_distance(
            graph,
            source,
            weight="length",
        )
        if len(predecessors) != len(nodes) or len(distances) != len(nodes):
            raise AssertionError("Dijkstra did not reach every grid node")

    print(f"OK: {args.iterations} iterations", flush=True)


if __name__ == "__main__":
    main()
