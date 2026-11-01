"""Download airport surface features from OpenStreetMap as GeoJSON.

Generated files are written to ``data/Geojson``. Before downloading, all
existing entries are moved into a timestamped backup directory.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "data" / "Geojson"

# BBOX format: south,west,north,east.
BBOX = "40.04417,116.55584,40.11510,116.63240"
BBOX_WIDE = "39.9,116.3,40.3,116.9"

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SLEEP_BETWEEN_REQUESTS = 3
MAX_RETRIES = 3
REQUEST_TIMEOUT_SECONDS = 180

GeometryType = Literal["node", "way", "relation"]
BboxMode = Literal["normal", "wide"]
GeoJson = dict[str, Any]


@dataclass(frozen=True, slots=True)
class DownloadSpec:
    tag_key: str
    tag_value: str
    filename: str
    geometry_types: tuple[GeometryType, ...]
    bbox_mode: BboxMode = "normal"


DOWNLOADS = (
    DownloadSpec("aeroway", "aerodrome", "airport_boundary.geojson", ("way", "relation"), "wide"),
    DownloadSpec("aeroway", "terminal", "terminal.geojson", ("way",)),
    DownloadSpec("aeroway", "stopway", "stopway.geojson", ("way",)),
    DownloadSpec("aeroway", "runway", "runway_taxiway.geojson", ("way",)),
    DownloadSpec("aeroway", "taxiway", "taxiway.geojson", ("way",)),
    DownloadSpec("aeroway", "apron", "apron.geojson", ("way",)),
    DownloadSpec(
        "aeroway", "parking_position", "parking_position.geojson", ("node", "way")
    ),
    DownloadSpec("aeroway", "gate", "gate.geojson", ("node", "way")),
    DownloadSpec("aeroway", "hangar", "hangar.geojson", ("way",)),
    DownloadSpec("building", "hangar", "hangar_building.geojson", ("way",)),
    DownloadSpec("aeroway", "windsock", "windsock.geojson", ("node", "way")),
    DownloadSpec("aeroway", "jet_bridge", "jet_bridge.geojson", ("node", "way")),
    DownloadSpec("aeroway", "tower", "tower.geojson", ("node", "way")),
    DownloadSpec(
        "aeroway", "navigationaid", "navigationaid.geojson", ("node", "way")
    ),
)


def backup_existing_data(output_directory: Path = OUTPUT_DIRECTORY) -> Path:
    """Move existing output entries into a newly created timestamped directory."""
    output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_directory = output_directory / timestamp
    suffix = 1
    while backup_directory.exists():
        backup_directory = output_directory / f"{timestamp}_{suffix:02d}"
        suffix += 1
    backup_directory.mkdir()

    for entry in tuple(output_directory.iterdir()):
        if entry != backup_directory:
            shutil.move(str(entry), backup_directory / entry.name)

    return backup_directory


def overpass_to_geojson(overpass_json: dict[str, Any]) -> GeoJson:
    """Convert Overpass ``out geom`` output into a GeoJSON FeatureCollection."""
    features: list[GeoJson] = []
    for element in overpass_json.get("elements", []):
        if not element.get("tags"):
            continue

        properties = dict(element["tags"])
        properties["osm_id"] = element.get("id")
        properties["osm_type"] = element.get("type")
        geometry: GeoJson | None = None

        if element["type"] == "node":
            geometry = {
                "type": "Point",
                "coordinates": [element["lon"], element["lat"]],
            }
        elif element["type"] == "way":
            coordinates = [
                [point["lon"], point["lat"]] for point in element.get("geometry", [])
            ]
            if len(coordinates) >= 4 and coordinates[0] == coordinates[-1]:
                geometry = {"type": "Polygon", "coordinates": [coordinates]}
            elif len(coordinates) >= 2:
                geometry = {"type": "LineString", "coordinates": coordinates}
            elif len(coordinates) == 1:
                geometry = {"type": "Point", "coordinates": coordinates[0]}

        # Relations require multipolygon member assembly, which is not performed here.
        if geometry is not None:
            features.append(
                {"type": "Feature", "geometry": geometry, "properties": properties}
            )

    return {"type": "FeatureCollection", "features": features}


def build_query(spec: DownloadSpec) -> str:
    """Build an Overpass QL query for one download specification."""
    bbox = BBOX_WIDE if spec.bbox_mode == "wide" else BBOX
    selectors = [
        f'{geometry_type}["{spec.tag_key}"="{spec.tag_value}"]({bbox});'
        for geometry_type in spec.geometry_types
    ]
    if len(selectors) > 1:
        selectors = ["(", *(f"  {selector}" for selector in selectors), ");"]
    return "\n".join(["[out:json][timeout:120];", *selectors, "out geom;"])


def request_overpass(query: str) -> dict[str, Any]:
    """Submit one Overpass query and decode its JSON response."""
    request = Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode(),
        headers={
            "User-Agent": "PEK-Aero-Data-Downloader/1.0 (airport trajectory research)",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def download_aero_data(spec: DownloadSpec, output_directory: Path = OUTPUT_DIRECTORY) -> bool:
    """Download and save one feature collection, retrying transient failures."""
    query = build_query(spec)
    for attempt in range(1, MAX_RETRIES + 1):
        print(
            f"正在请求 {spec.filename} ({spec.tag_key}={spec.tag_value}) "
            f"[尝试 {attempt}/{MAX_RETRIES}]"
        )
        try:
            response = request_overpass(query)
            geojson = overpass_to_geojson(response)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            print(f"  [警告] 第 {attempt} 次失败：{error}")
            if attempt == MAX_RETRIES:
                print(f"[错误] {spec.filename} 下载失败，已跳过\n")
                return False
            wait_seconds = 10 * attempt
            print(f"  等待 {wait_seconds} 秒后重试……")
            time.sleep(wait_seconds)
            continue
        break

    output_file = output_directory / spec.filename
    output_file.write_text(
        json.dumps(geojson, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{output_file} 下载完成（{len(geojson['features'])} 个要素）\n")
    return True


def main() -> None:
    backup_directory = backup_existing_data()
    print(f"已有数据已备份到：{backup_directory}")

    succeeded = 0
    failed_files: list[str] = []
    for index, spec in enumerate(DOWNLOADS):
        if download_aero_data(spec):
            succeeded += 1
        else:
            failed_files.append(spec.filename)
        if index < len(DOWNLOADS) - 1:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"===== 下载完毕：成功 {succeeded} 个，失败 {len(failed_files)} 个 =====")
    if failed_files:
        print("失败文件列表：")
        for filename in failed_files:
            print(f"  - {filename}")


if __name__ == "__main__":
    main()
