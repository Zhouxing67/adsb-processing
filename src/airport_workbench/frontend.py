"""Static delivery boundary; domain/API code does not manage frontend assets."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI) -> None:
    built = Path(__file__).with_name("web_dist")
    fallback = Path(__file__).with_name("static")
    directory = built if (built / "index.html").is_file() else fallback

    @app.get("/", include_in_schema=False)
    def frontend_index() -> FileResponse:
        return FileResponse(directory / "index.html", headers={"Cache-Control": "no-store"})

    # Mounted after API routes: missing API endpoints still return JSON 404s.
    app.mount("/", StaticFiles(directory=directory), name="workbench-frontend")
