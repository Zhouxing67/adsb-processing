# `path_map`

The package matches validated ADS-B observations to directed edge sequences on an
airport graph. The [algorithm guide](../../docs/path_map.md) explains the HMM and
its assumptions. The [quickstart and run guide](../../docs/quickstart.md) covers commands,
TOML settings, and report files.

## Python entry point

`match_batch()` is the shared matching interface used by the batch runner and
the flight workbench. It yields one outcome at a time, so callers can write
reports or update task progress without holding the whole batch in memory.

From the repository root, with [local settings](../../config.example.toml) in place:

```python
from airport_surface import load_graph
from config import load_settings
from flight.flight_repository import open_flight_database
from path_map import BatchStats, Matcher, match_batch

settings = load_settings()
database = open_flight_database(settings.database, read_only=True)
matcher = Matcher(load_graph(settings.graph_path), settings.matching)
inputs = ((flight.flight_id, flight) for flight in database.iterate("arrival", limit=10))

stats = BatchStats()
for outcome in match_batch(matcher, inputs):
    stats.add(outcome.status, outcome.failure_type, outcome.elapsed_seconds)
    print(outcome.key, outcome.status, outcome.reason)
print(stats.summary())
```

A work item carries a caller-supplied key and either a loaded flight or a callable
that loads it. Expected matching errors are recorded in the outcome. Workbench
supplies lazy loaders and captures per-item system errors to keep task progress
accurate. The batch runner propagates unexpected exceptions. For a single flight, call `matcher.map_flight(flight)`. The flight must provide its
movement direction (`departure` or `arrival`). The matcher first runs turn-constrained
pure-trajectory decoding (allowing at most one pushback reversal for departures) and
accepts the result immediately when it connects a stand boundary edge to a
runway-interface taxiway edge consistently with any reported `stand_ref`/`runway_ref`.
When trajectory evidence alone is insufficient or conflicts with reported labels, it
falls back to OD-bounded decoding (requiring `stand_ref`, and inferring the runway from
the runway-end observations if `runway_ref` is omitted).

## Surface OD for downstream callers

`from path_map import get_od` exposes `get_od(airport_graph, flight, movetype=None, *, config=MatchConfig())`.
For multiple flights on one graph, reuse `matcher.get_od(flight, movetype)`.
An explicit arrival or departure supplies a missing flight direction and must agree with
an existing direction. Both entry points raise `MapMatchingError` on resolution failure.
OD resolution does not run Viterbi or establish that a taxi path exists.

The immutable `FlightOD` includes ordered `origin` and `destination` labels, movement,
stand and runway references, and a `runway_source` of `reported` or `inferred`.
For inference, `runway_hit_edge` identifies the observed runway edge. The runway
label keeps both ends of a physical runway such as `01/19`, or is `None` for an
unlabelled runway edge. A reported runway uses the supplied designator.

## Responsibilities

| Component | Responsibility |
|---|---|
| `matcher.py` | `MatchConfig` defaults, graph preparation, and HMM matching of one trajectory inside the batch. |
| `batch.py` | Ordered batch execution, outcome timing, failure classification, and shared `BatchStats`. |
| `candidates.py` | Spatial index and candidate generation for observations. |
| `hmm.py` | Directed dual-graph routing, local turn filtering, directed state expansion, and Viterbi decoding. |
| `path.py` | Directed traversal, geometry, and graph-versioned `PathRecord` serialization. |

DuckDB queries and connection lifecycle are in
[`flight/database.py`](../flight/database.py). The batch runner owns files and
console reports. The workbench owns task queues and HTTP responses. Both use the
same configuration model and summary fields.

Workbench routes are registered in [`airport_workbench/app.py`](../airport_workbench/app.py).
Add SQL-backed query methods to `FlightDatabase`; keep HTTP parameter handling
and responses in the route. Session-specific matching state is managed by
[`airport_workbench/flights.py`](../airport_workbench/flights.py).
