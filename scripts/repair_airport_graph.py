"""Open an existing airport graph in the workbench for validation and repair."""

from __future__ import annotations

import argparse
from pathlib import Path

from airport_surface import load_graph
from airport_workbench import open_workbench


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair an existing airport graph")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace the output file if it already exists",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start the workbench without opening a browser automatically",
    )
    args = parser.parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input graph does not exist: {input_path}")
    if output_path.exists() and not args.force:
        raise SystemExit(
            f"Output already exists: {output_path}\n"
            "Pass --force to replace it, or choose another --output path."
        )
    open_workbench(
        load_graph(input_path),
        save_path=output_path,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    main()
