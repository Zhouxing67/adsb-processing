# Workbench frontend

Vite bundles the React, TypeScript, and Leaflet frontend. FastAPI provides the
API and serves the production build.

## Build and run

Run these commands from the repository root:

```powershell
pnpm --dir frontend/workbench install --frozen-lockfile
pnpm --dir frontend/workbench build
```

The build writes `src/airport_workbench/web_dist`. Both Python workbenches serve
this directory at `/`. A missing build returns HTTP 503 with build instructions.

| Mode | Backend command | Browser behavior |
|---|---|---|
| Airport graph editor | `uv run python -m airport_workbench` | Loads map and editing tools. Flight tabs and flight requests are absent. |
| Flight workbench | `uv run --extra stand-editing python -m src --workbench` | Loads flight catalogue, map comparisons, and observation details. The graph is read-only. |

Configure the flight backend in `config.local.toml` as described in the
[run guide](../../docs/path_matching_run.md). For frontend development, start
the desired Python backend first, then run `pnpm --dir frontend/workbench dev`.
The Vite proxy forwards `/api` to port 8765. If the backend listens elsewhere,
adjust the proxy target in `vite.config.ts` for that development session.

## Module boundaries

Startup reads `GET /api/state` and composes the interface for that session's mode.
The shared map controller owns Leaflet layers, graph selection and revision
state. The shell manages navigation layout and side rails. Only flight mode
loads the flight and workspace controllers and mounts the React flight table.

| Module | Responsibility |
|---|---|
| `controllers/map-controller.js` | Map layers, search, topology, and graph editing commands. |
| `controllers/flight-controller.js` | Committed catalogue filters, task submission and polling, flight geometry, and observations. The task progress display uses the backend summary. |
| `controllers/workspace-controller.js` | Flight-mode page containers, navigation, and drag-to-split behavior. |
| `features/map/MapToolbar.tsx` and `features/flights/FlightTable.tsx` | React views that subscribe to controller snapshots and issue commands. |
| `domain/properties.ts` and `domain/popup-layout.ts` | Editable-field validation and map popup placement. |
| `styles/tokens.css` and `styles/workbench.css` | Design tokens, layout, and responsive styles. |

The `window.workbenchMap`, `window.workbenchFlights`, and navigation facades
connect the ES module controllers to the mounted views. Resize observers track
map and rail dimensions. The application lifecycle owns listeners, scheduled
frames and timers, request aborts, and view unmounts. It disposes dependent views
before removing the map and preserves resources when the page enters the browser
back/forward cache.

## Regression checks

Build the frontend before running the browser suite:

```powershell
pnpm --dir frontend/workbench test:unit
pnpm --dir frontend/workbench test:browser
```

Unit tests cover lifecycle disposal, editable property validation, and popup
placement. They use Node.js with native TypeScript type stripping. Browser tests
use the project Python environment to start isolated graph and flight fixtures on
ports 8891 and 8892, with headless Edge on Windows. They cover mode separation,
editing and undo, rail visibility, flight filters, selection, matching progress,
and map/detail navigation. Failed runs retain traces in the ignored
`frontend/workbench/test-results` directory.
