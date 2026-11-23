# `route_library` 模块指南

`route_library` 负责将批量匹配产出的机场地面滑行路径持久化到 DuckDB（与原始航班表同库，表名 `main.route_library`），并提供按 OD 分组键 `(graph_id, movement, stand_ref, runway_ref)` 索引的查询、幂等入库与人工审校状态管理。

- 命令行运行步骤见 [快速上手与运行指南](../../docs/quickstart.md#43-路径库入库duckdb-持久化)
- 路径匹配算法与 `PathRecord` 说明见 [匹配算法](../../docs/path_map.md)

## 命令行入口

从仓库根目录运行独立入库命令，将一次 `BatchMatchingRunner` 产出目录（包含 `graph.json`、`paths.jsonl`、`matches.jsonl`）导入到 `config.local.toml` 指定的 DuckDB 数据库：

```powershell
# 默认模式：先清理当前 graph_id 下旧的 candidate 记录，再导入本批去重路径
# （完整保留已人工审校的 verified / rejected / manual 记录及其他 graph_id 的数据）
uv run --extra stand-editing python -m route_library import outputs/path_map/<run_id>

# 增量追加模式：保留已有 candidate，仅追加本次新出现的路径
uv run --extra stand-editing python -m route_library import --append outputs/path_map/<run_id>
```

## Python 常用入口

`FlightDatabase` 已挂载 `database.routes`（`RouteLibraryRepository`），可直接按分组键查询、更新审校状态或还原为带几何的 `Path` 对象：

```python
from airport_surface import graph_id, load_graph
from config import load_settings
from flight.flight_repository import open_flight_database
from route_library import RouteStatus, import_batch_run

settings = load_settings()
database = open_flight_database(settings.database, read_only=False)
airport_graph = load_graph(settings.graph_path)

# 1. 导入一批匹配结果
summary = import_batch_run("outputs/path_map/<run_id>", database.routes)

# 2. 按 OD 分组键索引查询
routes = database.routes.find_by_od(
    graph_id=graph_id(airport_graph),
    movement="departure",
    stand_ref="009",
    runway_ref="01",
)

# 3. 还原为 AirportGraph 上的连续有向 Path
path = routes[0].resolve(airport_graph)

# 4. 更新人工审校状态
database.routes.update_status(
    routes[0].route_id,
    RouteStatus.VERIFIED,
    note="标准滑行路径",
)
```

## 文件职责

| 文件 | 职责 |
|---|---|
| `models.py` | 定义 `RouteEntry`、`RouteStatus`、`RouteSource`，提供字段规范化、边序列 JSON 编解码、`make_route_id` 确定性哈希及 `RouteEntry.from_path()` / `resolve()`。 |
| `repository.py` | `RouteLibraryRepository`：维护 `main.route_library` 建表与 OD 复合索引，提供单事务 `replace_candidates()`、幂等 `upsert_routes()`、按分组键查询 `find_by_od()`、`get()`、`update_status()` 与 `delete()`；全程通过 `DuckDBConnection.bind()` 兼容直连与 Quack。 |
| `importer.py` | `import_batch_run()` 与 `ImportSummary`：读取 `graph.json`、`paths.jsonl`、`matches.jsonl`，校验 `graph_id` 与拓扑连续性，按 `route_id` 去重后落盘。 |
| `cli.py` / `__main__.py` | `python -m route_library import [--append] <run_dir>` 命令行入口。 |

## 数据表与语义约定

表名：`main.route_library`，复合索引：`idx_route_library_od (graph_id, movement, stand_ref, runway_ref)`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `route_id` | `VARCHAR` (PK) | `r-` + `sha256(graph_id, movement, stand_ref, runway_ref, edges_json)[:20]`，同图同 OD 下天然幂等。 |
| `graph_id` | `VARCHAR` | 绑定的机场图内容标识（`airport_surface.graph_id`）。 |
| `movement` | `VARCHAR` | `departure` 或 `arrival`。 |
| `stand_ref` | `VARCHAR` | 机位编号（必填，非空）。 |
| `runway_ref` | `VARCHAR` | 跑道号（大写规范化，原航班缺失跑道时为 `NULL`）。 |
| `runway_interface_node` | `VARCHAR` | 路径靠跑道一端的接口节点 ID（离港取末边终点，进港取首边起点）。 |
| `edges_json` | `VARCHAR` | 与 `PathRecord` 一致的紧凑 JSON 边序列 `[[u, v, key], ...]`。 |
| `edge_count` | `INTEGER` | 路径包含的有向边数量。 |
| `total_length_m` | `DOUBLE` | 路径总长度（米）。 |
| `status` | `VARCHAR` | `candidate`（默认）/ `verified` / `rejected` / `manual`。 |
| `source` | `VARCHAR` | `matched`（算法导入）/ `manual`（人工录入）。 |
| `note` | `VARCHAR` | 人工审校备注（可空）。 |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | 创建与最近更新时间（UTC）。 |

### 导入覆盖与保护规则

- **默认替换（`replace_candidates=True`）**：在同一写事务内先删除 `graph_id = 当前图 AND status = 'candidate'` 的记录，再对本批路径执行 `ON CONFLICT (route_id) DO NOTHING`。因此旧算法残留的未审校候选会被清干净，而人工已标记的 `verified` / `rejected` / `manual` 记录以及其他 `graph_id` 的数据均不会被覆盖或删除。
- **增量追加（`--append`）**：不删除已有 `candidate`，仅插入新 `route_id`。
- 若导入旧版不含 `stand_ref` 字段的 `matches.jsonl`，缺失行会被跳过并计入 `ImportSummary.skipped_missing_od`。

## 测试入口

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_route_library.py
```
