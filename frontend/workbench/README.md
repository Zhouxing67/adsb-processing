# Workbench frontend

Independent Vite + React + TypeScript build project. FastAPI remains the API server.

```powershell
pnpm --dir frontend/workbench install --frozen-lockfile
pnpm --dir frontend/workbench dev
pnpm --dir frontend/workbench build
```

Development: start the existing Workbench command on port 8765, then open the Vite URL.
Vite proxies `/api` to that session. Production: build once, then use the existing Python
startup command. FastAPI serves `airport_workbench/web_dist` through a dedicated static
hosting module. React, Ant Design and Leaflet are bundled locally.

Migration status: `public/bridge` is a temporary adapter for existing map and flight
controllers. `src/shell.js` still contains DOM-based adapters; a successful build does
not mean that every view has migrated to React state. Replace these incrementally,
keeping the API contracts and visual behavior stable. The previous static directory is
retained as fallback until that migration is complete.
