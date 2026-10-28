# ADS-B processing

使用 `uv` 管理 Python 依赖，包含 ADS-B 数据处理与首都机场（ZBAA）地面网络构建。

## HMM 批量路径匹配

```powershell
uv run python src/__main__.py `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv `
    --departures data/ADS-B/more_15_dep.csv `
    --output outputs/path_map
```

调试时可以限制每批航班数，并在匹配结束后用 Workbench 查看少量成功和失败样本：

```powershell
uv run python src/__main__.py --limit 10 --visualize
```

每次任务在输出根目录下创建时间戳目录，只保存 `graph.json`、`paths.jsonl`、
`matches.jsonl` 和 `summary.json`。相同有向边序列只在 `paths.jsonl` 保存一次；
每架航班在 `matches.jsonl` 中通过 `path_id` 引用路径，匹配失败时该值为 `null`。
`PathRecord` 本身只包含图内容 ID 和有向边序列。
机场图的空间索引和路由器
只构建一次，并在两批航班之间复用。ADS-B 文件通过 `load_data()` 读取、附加运行类型并按
`flight_id` 拆分；每架航班的观测按时间排序后再进行匹配。匹配结果逐条写入磁盘，
每处理 100 架航班刷新一次输出和运行中摘要。

## PEK 地面图与 Top 3 滑行路径

```powershell
uv sync
uv run python -m pek_surface_routing.main
# 仅构图、识别端点和保存检查图
uv run python -m pek_surface_routing.main --build-only --output outputs/pek_identification
```

默认读取 `data/Geojson` 中的 runway、taxiway、parking_position 文件，构建以米为权重的
NetworkX MultiGraph，识别单个停机位与跑道边界接入点。默认建图无需联网。

按长度输出每个机位—入口组合最多三条无环路径，禁止直线跨跑道、实际路径穿越跑道、
穿过其他机位或借用专用机位引导线抄近路。输出位于 `outputs/pek_surface_routing`，
包括图、端点、路径 GeoJSON、组合结果表和检查报告。

![PEK 地面网络](outputs/pek_surface_routing/overview.png)

构图规则、图例、数据限制和 Python 接口见
[机场图与路径说明](src/pek_surface_routing/README.md)。

## Airport Workbench：机场图编辑与匹配结果查看

```powershell
uv run python -m airport_workbench
```

工作台只加载已经生成的 `data/graphs/zbaa_final.json`，不会在匹配或编辑过程中隐式建图。
浏览器中的“保存”直接更新该文件。工作台还可以叠加显示项目自己的
`adsb.Flight` 和 `path_map.Path`：

```python
from airport_workbench import open_workbench

open_workbench(graph, flights=[flight], paths=[matched_path])
```

只查看机场图、轨迹与匹配结果时，使用只读入口。它保留搜索、图层控制和拓扑检查，
但不提供编辑控件，服务端也会拒绝写请求：

```python
from airport_workbench import visualize_graph

visualize_graph(graph, flights=[flight], paths=[matched_path])
```

Flight 显示原始轨迹和观测点；Path 按遍历顺序显示每一条有向边。二者可在
Leaflet 图层控制器中分别显示或隐藏。

Python 接口：

```python
from airport_surface import load_graph, save_graph
from airport_workbench import edit_graph

graph = load_graph()
graph = edit_graph(graph)
save_graph(graph)
```

首次建图是独立的离线步骤，需要可选的 `graph-build` 依赖组：

```powershell
uv sync --group graph-build
uv run python scripts/build_airport_graph.py `
    --airport ZBAA `
    --projection EPSG:32650

uv run python scripts/repair_airport_graph.py `
    --input data/graphs/zbaa_raw.json `
    --output data/graphs/zbaa_final.json
```

投影必须由用户显式指定，并且是以米为水平单位的投影坐标系，不能使用
`EPSG:4326`。建图默认写入
`data/graphs/<icao>_raw.json`。为避免误覆盖已有图，目标存在时命令会停止；
确认需要替换时显式传入 `--force`。脚本保存后会用生产环境的 `load_graph()` 回读，
核对 `graph_id` 并输出节点、边、原始来源和构图问题摘要。

只有 `airport_surface.traffic_builder` 和建图脚本会导入 `traffic`；匹配、图加载和
Workbench 编辑流程均不导入该可选依赖。

完整的建图、修复、覆盖保护和一键命令见
[机场图建图与修复脚本使用说明](docs/graph_build_and_repair.md)。

“切分”会吸附到附近原边或真实几何交点，新增节点并切分相关边。灰色节点为人工新增节点；
红色节点仅表示度数为 1。编辑器支持按钮或 `Ctrl+Z` 撤销当前会话最近 50 次修改，
删除节点时会连同原始弯曲边及其属性一起恢复。编辑器为本地单用户工具，不需要 Jupyter。

### 机场图数据模型与构图规则

项目使用自己的 `airport_surface.AirportGraph`，不依赖 traffic 的 AirportGraph 实现。
它显式保存 NetworkX MultiGraph、不可变 SourceNode/SourceEdge 注册表、投影和图元数据。

构图只把 OSM way 首尾节点，以及被不同 way 共享的 OSM Node 作为拓扑节点，并在这些
节点处切分完整 way。普通内部 OSM Node 仅作为 LineString 形状点。坐标完全相同的不同
OSM Node 会记录为同一 SourceNode 的别名。系统不执行任何基于距离的自动吸附；几何相交
但不共享 OSM Node 的道路只写入 `build_issues`，不会自动建立连接。
