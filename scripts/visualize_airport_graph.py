"""Open an existing airport graph in the read-only workbench viewer."""

from __future__ import annotations

import argparse
from pathlib import Path

from airport_surface import load_graph
from airport_workbench import visualize


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize an existing airport graph")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start the viewer without opening a browser automatically",
    )
    args = parser.parse_args()
    input_path = args.input.resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input graph does not exist: {input_path}")

    visualize(
        load_graph(input_path),
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
