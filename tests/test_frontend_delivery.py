"""Verify built assets and API routing share one server safely."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from airport_workbench import frontend


def test_built_frontend_takes_priority_without_shadowing_api(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend, "__file__", str(tmp_path / "frontend.py"))
    for directory, text in [("static", "fallback"), ("web_dist", "built")]:
        folder = tmp_path / directory
        folder.mkdir()
        (folder / "index.html").write_text(text)
    (tmp_path / "web_dist" / "asset.js").write_text("built-asset")
    app = FastAPI()

    @app.get("/api/state")
    def state():
        return {"ready": True}

    frontend.mount_frontend(app)
    with TestClient(app) as client:
        assert client.get("/").text == "built"
        assert client.get("/asset.js").text == "built-asset"
        assert client.get("/api/state").json() == {"ready": True}
        assert client.get("/api/missing").status_code == 404
        assert client.get("/../frontend.py").status_code == 404


def test_source_fallback_when_frontend_is_not_built(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend, "__file__", str(tmp_path / "frontend.py"))
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "index.html").write_text("source")
    app = FastAPI()
    frontend.mount_frontend(app)
    with TestClient(app) as client:
        assert client.get("/").text == "source"
