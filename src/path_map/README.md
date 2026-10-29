# `path_map`

`path_map` implements a small HMM map matcher for the project's own airport graphs
and validated `adsb.Flight` trajectories.
It does not call `AirportGraph.map_flight()` or `intersection_with_flight()`.

The single CLI entry point is `uv run python src/__main__.py`. It runs selected
datasets in batch mode by default; add `--workbench` to load the same normalized
datasets and `MatchConfig` into the interactive flight workbench without running
the batch matcher first. `python -m airport_workbench` is reserved for graph
viewing and editing.

```python
from path_map import MatchConfig, MovementType, load_data, map_flight

flights = load_data("data/ADS-B/more_15_arr.csv", MovementType.ARRIVAL)

path = map_flight(
    airport_graph,
    flight,
    MatchConfig(search_radius=40, max_candidates=6, gps_sigma=10),
)
print(path.edge_ids)  # directed (u, v, key) tuples
print(path.total_length)  # metres
```

Each observation is projected with the graph's own transformer. An STRtree finds
nearby projected edge geometries. Gaussian distance emissions and an exponential
penalty on `abs(network_distance - observation_distance)` are decoded with
Viterbi in log space. Candidate-to-candidate network distance includes both edge
fractions and all shortest-path intermediate edges.

`Path` references its `AirportGraph`, retains traversal direction, parallel-edge
keys, loops, and reversals, and exposes a WGS84 geometry. `PathRecord` is its
minimal persistent form: a graph content ID plus directed edge IDs. Resolving a
record against a modified graph is rejected.

Current conservative limitations: the network is treated as undirected; heading,
speed, runway/taxiway semantics, uncertainty varying by observation, outlier
repair, and long-gap segmentation are not modeled. A transition uses the shortest
network distance between candidate positions, and defaults must be calibrated for
the airport and ADS-B source.

## ZBAA real-data example

The repository's prepared UTM zone 50 graph and selected flight can be matched
directly:

```powershell
uv run python tests/example_zbaa_map_match.py
```

The example loads `data/graphs/zbaa_final.json` through the project's own
`airport_surface.load_graph()` function and reads
`data/ADS-B/one_flight.csv` into an `adsb.Flight`.
