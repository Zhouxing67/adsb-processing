# Workbench frontend

Vite + React + TypeScript project. FastAPI owns API routes and serves the built files.

```powershell
pnpm --dir frontend/workbench install --frozen-lockfile
pnpm --dir frontend/workbench dev
pnpm --dir frontend/workbench build
```

Development proxies `/api` to the existing Workbench server on port 8765.
Production builds to `src/airport_workbench/web_dist`; the normal Python command
serves this directory. Missing builds return 503 with build instructions.

## Boundaries

- `src/controllers/map-controller.js`: module-private map, geometry layers, selection,
  graph revision, and editing state; exports the map services used by flight rendering.
- `src/controllers/flight-controller.js`: catalogue queries, applied filters, matching,
  flight geometry, and observations. Imports map services explicitly.
- `src/controllers/workspace-controller.js`: persistent page containers, navigation,
  filtering actions, and drag-to-split layout.
- `src/features/map/MapToolbar.tsx`: typed command boundary and subscribed React toolbar.
- `src/features/flights/FlightTable.tsx`: typed, keyed React flight table.
- `src/shell.js`: application composition and rail resize management.
- `src/styles/tokens.css`: shared design tokens.
- `src/styles/workbench.css`: canonical application rules, including responsive states.

Controllers are bundled ES modules, not classic scripts loaded into shared browser
scope. The `window.workbenchMap`, `window.workbenchFlights`, and navigation facade
remain explicit interoperability boundaries for the existing controller/React split.
This is not a claim that all controllers are TypeScript or all views are React.
Map/rail ResizeObservers track actual geometry changes. DOM mutation observers are
not used to infer application state or wait for layout initialization.

## Regression checks

```powershell
pnpm --dir frontend/workbench test:unit
pnpm --dir frontend/workbench test:browser
```

Unit tests import the actual property and layout modules and verify subscription
cleanup, idempotent disposal, revision validation and attribute whitelisting.
They require Node.js with native TypeScript type stripping (the current Node 24
runtime supports it).

Browser tests run headless Edge on Windows and start two isolated FastAPI fixtures
on ports 8891/8892. They need the project Python environment and a prior frontend
build. Fixtures generate their own graph and 18 flights; they never use user data.
Scenarios cover editing/undo, sidebar visibility/reload, filter drafts, cross-page
selection, detail-to-map navigation and drag-to-split layout. Test traces are retained
on failures under the ignored test-results directory.

## Resource ownership

`controllers/lifecycle.js` owns application listeners, resize observers, scheduled
frames/timers and cleanup callbacks. Views register unmount callbacks; flight queries
abort and polling stops on disposal. The map is removed only after dependent views
are disposed. Browser back/forward-cache pagehide events keep resources intact.
`domain/properties.ts` validates editable fields and revisions;
`domain/popup-layout.ts` calculates placement without modifying map state.
