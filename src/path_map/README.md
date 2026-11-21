# `path_map`

The package matches validated ADS-B observations to directed edge sequences on an
airport graph. The [algorithm guide](../../docs/path_map.md) explains the HMM and
its assumptions. The [run guide](../../docs/path_matching_run.md) covers commands,
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
accurate. The batch runner propagates unexpected exceptions. For a single flight,
call `matcher.map_flight(flight)`. The flight must provide its movement direction,
stand reference, and runway designator. The matcher resolves these to endpoint
candidates and chooses a connected route under the turn constraint.

## Responsibilities

| Component | Responsibility |
|---|---|
| `matcher.py` | `MatchConfig` defaults, graph preparation, and HMM matching of one trajectory inside the batch. |
| `batch.py` | Ordered batch execution, outcome timing, failure classification, and shared `BatchStats`. |
| `candidates.py` | Spatial index and candidate generation for observations. |
| `hmm.py` and `transition_constraints.py` | Network routing, transition scoring and constraints, and Viterbi decoding. |
| `path.py` | Directed traversal, geometry, and graph-versioned `PathRecord` serialization. |

DuckDB queries and connection lifecycle are in
[`flight/database.py`](../flight/database.py). The batch runner owns files and
console reports. The workbench owns task queues and HTTP responses. Both use the
same configuration model and summary fields.

Workbench routes are registered in [`airport_workbench/app.py`](../airport_workbench/app.py).
Add SQL-backed query methods to `FlightDatabase`; keep HTTP parameter handling
and responses in the route. Session-specific matching state is managed by
[`airport_workbench/flights.py`](../airport_workbench/flights.py).
