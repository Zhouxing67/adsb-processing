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
[quickstart and run guide](../../docs/quickstart.md). For frontend development, start
the desired Python backend first, then run `pnpm --dir frontend/workbench dev`.
The Vite proxy forwards `/api` to port 8765. If the backend listens elsewhere,
adjust the proxy target in `vite.config.ts` for that development session.

## Module boundaries

The frontend has one React root and one startup path. Startup reads
`GET /api/state` and composes the interface for the current backend mode. React
owns the complete document below `#root`; Leaflet is isolated behind `MapView`
and never owns application state.

| Module | Responsibility |
|---|---|
| `app/WorkbenchContext.tsx` | The single client-state boundary: mode, selection, revision, panels, and graph commands. |
| `app/App.tsx` | Application composition, graph tools, topology, feature details, and mode navigation. |
| `api/client.ts` and `api/types.ts` | Typed access to the unchanged FastAPI contract and uniform error handling. |
| `features/map/MapView.tsx` | Leaflet lifecycle and graph/flight layer rendering. |
| `features/flights/FlightPanel.tsx` | Catalogue filters, selection, matching, geometry, and observation navigation. |
| `domain/properties.ts` and `domain/popup-layout.ts` | Editable-field validation and map popup placement. |
| `styles/*.css` | Design tokens, legacy visual vocabulary, and React layout overrides. |

There are no global controller facades or `window` custom-event buses. Graph
mutations always include the current revision; a 409 cancels the active
operation, refreshes `/api/state`, and leaves conflict resolution to the backend.
Server data stays in the API-facing components while transient UI state lives in
the React context. Leaflet instances and layers stay in refs.

## API contract generation

API contract ownership is moving to Pydantic request and response models.
FastAPI exports separate OpenAPI documents for graph-editing and flight modes,
because each runtime mode deliberately exposes a different route set. New or
changed API shapes must originate in Pydantic rather than in frontend types.

Regenerate the committed OpenAPI documents and TypeScript declarations after
changing an API model or route:

```powershell
pnpm --dir frontend/workbench contracts:generate
```

Generated files under `openapi/` and `src/api/generated/` must be committed and
must not be edited by hand. Check for contract drift with:

```powershell
pnpm --dir frontend/workbench contracts:check
```

`src/api/types.ts` remains a temporary compatibility layer while endpoints are
migrated to generated schemas; existing untyped response shapes remain visible
as `unknown` until their Pydantic response DTO is introduced.

## Regression checks

Build the frontend before running the browser suite:

```powershell
pnpm --dir frontend/workbench test:unit
pnpm --dir frontend/workbench test:browser
```

Unit tests cover editable property validation and popup placement. They use
Node.js with native TypeScript type stripping. Browser tests
use the project Python environment to start isolated graph and flight fixtures on
ports 8891 and 8892, with headless Edge on Windows. They cover mode separation,
editing and undo, flight filters, selection, matching, and map/detail navigation.
Failed runs retain traces in the ignored
`frontend/workbench/test-results` directory.
