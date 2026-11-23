# `airport_surface` 模块指南

`airport_surface` 负责机场地面路网（`AirportGraph`）的**数据模型、来源链几何重建、一致性校验、Schema v2 持久化**以及**离线 OSM 建图**。

- 架构设计与概念详解见 [机场图数据设计](../../docs/airport_surface.md)
- 建图、编辑与运行命令见 [快速上手与运行指南](../../docs/quickstart.md#44-机场图构建与编辑)

## 常用入口

绝大多数外部模块只需从顶层包 `airport_surface` 导入即可：

```python
from airport_surface import AirportGraph, graph_id, load_graph, save_graph

airport_graph = load_graph("data/graphs/zbaa_final.json")
```

离线从 `traffic` / OSM 构建原始图时再显式导入 `traffic_builder`（需要 `graph-build` 依赖组）：

```python
from airport_surface.traffic_builder import build_graph

raw_graph = build_graph("ZBAA", "EPSG:32650")
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `identifiers.py` | 规范标识类型定义与校验：`NodeId`（非零十进制字符串，正数为 OSM 节点，负数为人工节点）、`OsmId`、`EdgeKey`、`EdgeId`。 |
| `models.py` | 核心数据对象：`AirportGraph`、`GraphMetadata`、`SourceNode`、`SourceEdge`、`SourceSegment`，以及投影辅助、机位索引（`stand_to_edges`）与跑道接口索引（`runway_interfaces`）。 |
| `source_chain.py` | 来源链算法与几何重建：切分（`split_source_chain`）、压缩（`compact_source_segments`）、反转（`reverse_source_segments`）、累计里程（`cumulative_distances`）与由来源区间重建 WGS84 折线（`geometry_from_source_segments`）。 |
| `validation.py` | 图结构不变量校验：端点一致性（`validate_edge_endpoints`）、来源链可重建性（`validate_edge_sources`）、来源全覆盖性（`validate_source_intervals`）。 |
| `persistence.py` | Schema v2 JSON 序列化、原子写盘（`save_graph`）、加载（`load_graph`）与内容哈希（`graph_id`）。 |
| `traffic_builder.py` | 离线建图流水线：从 `traffic` / OSM 读取地面要素、节点归一化、提取拓扑节点、沿来源线切边并校验。 |

## `AirportGraph.graph` 节点与边字段约定

`AirportGraph.graph` 底层为无向多重图 `nx.MultiGraph`，节点和边上的核心属性键如下：

### 节点属性（`graph.nodes[node_id]`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `pos` | `tuple[float, float]` | WGS84 `(lon, lat)` 坐标（必填）。 |
| `source_type` | `str` | 来源类型，如 `"osm"` 或 `"manual"`。 |
| `osm_node_ids` | `tuple[OsmId, ...]` | 归一化到该位置的原始 OSM 节点 ID 集合。 |
| `aeroway` | `str`（可选） | 保留的 OSM Point 要素标签，如 `"parking_position"`。 |

### 边属性（`graph.edges[u, v, key]`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `geometry` | `shapely.LineString` | WGS84 折线几何（必填）。 |
| `first` / `last` | `NodeId` | 折线与来源链的排列起止端点（不代表单向通行限制）。 |
| `source_segments` | `tuple[SourceSegment, ...]` | 权威来源链，记录依次引用的 `source_id`、起止里程（米）与方向。 |
| `source_type` | `str` | `"osm"`、`"manual"` 或 `"composite"`（跨多段来源组合而成）。 |
| `aeroway` | `str` | 业务类型：`taxiway`、`runway` 或 `parking_position`。 |
| `ref` / `name` | `str`（可选） | 业务编号（如机位号、跑道号 `"18L/36R"`）与名称。 |
| `osm_node_ids` | `tuple[OsmId, ...]`（可选） | 单来源边对应的原始 OSM 节点序列；组合边不保留。 |
