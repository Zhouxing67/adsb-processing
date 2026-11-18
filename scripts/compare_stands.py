from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

# 项目根目录
ROOT = Path(__file__).resolve().parents[1]

ADSB_PATH = ROOT / "data/ADS-B/stand.csv"
OSM_PATH = ROOT / "data/Geojson/parking_position.geojson"
OUTPUT_DIR = ROOT / "data/processed/stand_comparison"


def normalize_stand(value: Any) -> str | None:
    """统一停机位编号格式。"""
    if pd.isna(value):
        return None
    value = str(value).strip().upper()
    if not value:
        return None
    return value


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 读取 ADS-B 停机位
    adsb = pd.read_csv(ADSB_PATH, dtype={"stand": "string"})
    adsb["stand"] = adsb["stand"].map(normalize_stand)
    adsb_stands = set(adsb["stand"].dropna())

    # 2. 读取 OSM 停机位
    osm = gpd.read_file(OSM_PATH)

    print("OSM 字段：", osm.columns.tolist())
    print("OSM 几何类型分布：")
    print(osm.geometry.geom_type.value_counts())

    # OSM 通常使用 ref 记录停机位编号
    osm["stand"] = osm["ref"].map(normalize_stand)

    osm_stands = set(osm["stand"].dropna())

    # 3. 集合比较
    common = adsb_stands & osm_stands
    adsb_only = adsb_stands - osm_stands
    osm_only = osm_stands - adsb_stands

    # 4. 输出统计
    print("\n===== 停机位统计 =====")
    print(f"ADS-B 停机位数量：{len(adsb_stands)}")
    print(f"OSM Feature 数量：{len(osm)}")
    print(f"OSM 唯一停机位数量：{len(osm_stands)}")
    print(f"双方共有停机位数量：{len(common)}")
    print(f"仅 ADS-B 存在：{len(adsb_only)}")
    print(adsb_only)
    print(f"仅 OSM 存在：{len(osm_only)}")

    if adsb_stands:
        print(f"ADS-B 编号匹配率：{len(common) / len(adsb_stands):.2%}")

    # 5. 导出比较结果
    all_stands = sorted(adsb_stands | osm_stands)

    comparison = pd.DataFrame(
        {
            "stand": all_stands,
        }
    )

    comparison["in_adsb"] = comparison["stand"].isin(adsb_stands)
    comparison["in_osm"] = comparison["stand"].isin(osm_stands)

    comparison["status"] = "both"
    comparison.loc[
        comparison["in_adsb"] & ~comparison["in_osm"],
        "status",
    ] = "adsb_only"
    comparison.loc[
        ~comparison["in_adsb"] & comparison["in_osm"],
        "status",
    ] = "osm_only"

    comparison.to_csv(
        OUTPUT_DIR / "stand_comparison.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 6. 检查 OSM 中同一个 ref 是否对应多个 Feature
    duplicates = osm[osm["stand"].notna() & osm.duplicated(subset=["stand"], keep=False)].copy()

    duplicates.drop(columns="geometry").to_csv(
        OUTPUT_DIR / "osm_duplicates.csv",
        index=False,
        encoding="utf-8-sig",
    )


    print(f"\nOSM 中重复编号的 Feature 数量：{len(duplicates)}")
    print(f"结果已保存至：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
