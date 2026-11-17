"""Static delivery boundary; domain/API code does not manage frontend assets."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI) -> None:
    built = Path(__file__).with_name("web_dist")
    directory = built

    @app.get("/", include_in_schema=False)
    def frontend_index():
        if not (directory / "index.html").is_file():
            return HTMLResponse(
                "<h1>Workbench 前端尚未构建</h1>"
                "<p>请在项目根目录执行，然后重启服务：</p>"
                "<pre>pnpm --dir frontend/workbench install --frozen-lockfile\n"
                "pnpm --dir frontend/workbench build</pre>",
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )
        return FileResponse(directory / "index.html", headers={"Cache-Control": "no-store"})

    # Mounted after API routes: missing API endpoints still return JSON 404s.
    if directory.is_dir():
        app.mount("/", StaticFiles(directory=directory), name="workbench-frontend")
