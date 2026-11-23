"""Airport workbench process and browser launcher."""

from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from pathlib import Path as FilePath
from typing import Any

import uvicorn

from airport_surface import DEFAULT_GRAPH_PATH, AirportGraph, load_graph
from flight.flight_repository import FlightDatabase

from .app import create_app
from .editor import EditorSession


def open_workbench(
    airport_graph: AirportGraph,
    *,
    save_path: str | FilePath = DEFAULT_GRAPH_PATH,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    match_config: Any | None = None,
    input_time_semantics: str = "UTC",
    display_timezone: str = "UTC",
    flight_database: FlightDatabase | None = None,
) -> AirportGraph:
    """Serve the workbench and block until it is stopped or finished."""
    session = EditorSession(airport_graph)
    server: uvicorn.Server

    def finish() -> None:
        threading.Timer(0.2, setattr, args=(server, "should_exit", True)).start()

    app = create_app(
        session,
        FilePath(save_path),
        on_finish=finish,
        match_config=match_config,
        input_time_semantics=input_time_semantics,
        display_timezone=display_timezone,
        flight_database=flight_database,
    )
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info"))
    if open_browser:
        url = f"http://{host}:{port}/?session={time.time_ns()}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    server.run()
    return session.airport_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the airport workbench.")
    parser.add_argument("--graph", type=FilePath, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    open_workbench(
        load_graph(args.graph),
        save_path=args.graph,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )
