# 快速上手与运行指南

本文面向在新电脑上 `git clone` 仓库后的首次部署与日常使用，涵盖**环境安装、数据库与 Quack 并发服务配置、DataGrip 连接、前端构建**，以及**航班工作台、批量匹配、机场图编辑**的完整操作流程。

> **架构与原理文档**见 [机场图数据设计](airport_surface.md) 与 [匹配算法](path_map.md)；**开发与测试文档**见 [匹配模块开发指南](../src/path_map/README.md) 与 [Workbench 前端指南](../frontend/workbench/README.md)。

---

## 1. 环境与配置准备

### 前置工具

- **Python 3.13**（要求 `>=3.13,<3.14`）与 **[uv](https://docs.astral.sh/uv/)**
- **Node.js** 与 **pnpm**（使用浏览器工作台时需要；仅运行命令行批量匹配可跳过）
- **DataGrip**（可选，用于查询或手动检查 DuckDB 数据）

### 1.1 安装 Python 依赖

从仓库根目录执行：

```powershell
uv sync --extra stand-editing
```

- `--extra stand-editing` 安装 DuckDB、SQLAlchemy 及 Quack 所需依赖，覆盖批量匹配、航班工作台与 Quack 服务。
- 若后续需要从 OSM 离线重新生成原始机场图，再额外安装建图依赖组：

```powershell
uv sync --group graph-build
```

### 1.2 放置数据库与 SQL 文件

将准备好的 DuckDB 数据库文件（需包含 `main.adsb_202406_arr` 和 `main.adsb_202406_dep` 两张表）放到本地目录，推荐放在仓库下的 `data/database/`（该目录已在 `.gitignore` 中忽略），例如：

```text
data/database/adsb.db
data/database/sql/        # 可选：存放离线 import/filter/export/analyse 等 SQL 脚本
```

> **数据约定**：同一表中相同 `flight_id` 的观测组成一条航班轨迹，进港和离港中的同名航班分别处理。两张表的无时区 `timestamp` 按北京时间解释，匹配读取时转换为 UTC；工作台目录与日期筛选默认使用北京时间。离线诊断脚本见 [scripts/csv_flights.py](../scripts/csv_flights.py)。

### 1.3 创建本地配置 `config.local.toml`

从仓库根目录复制配置模板（`config.local.toml` 已被 Git 忽略，其中的相对路径以仓库根目录为基准）：

```powershell
if (-not (Test-Path config.local.toml)) { Copy-Item config.example.toml config.local.toml }
```

编辑 `config.local.toml`，指定数据库路径、机场图路径，并启用 `quack_uri` 以支持多客户端并发访问：

```toml
graph_path = 'data/graphs/zbaa_final.json'

[database]
path = 'data/database/adsb.db'
quack_uri = 'quack:127.0.0.1:9494'
```

- `path` 支持相对路径（相对仓库根目录）或绝对路径（例如 `D:\code\adsb-processing\data\database\adsb.db`）。
- 启用 `quack_uri` 后，工作台、批处理脚本与 DataGrip 可通过 Quack 并发读写同一数据库。若省略 `quack_uri`，程序将直连 `.db` 文件，此时同一时间只能有一个读写进程占用数据库。

---

## 2. 启动 Quack 服务与配置 DataGrip

若在 `config.local.toml` 中启用了 `quack_uri`，在运行工作台、批量匹配或通过 DataGrip 查询前，先启动 Quack 服务。

### 2.1 启动 Quack 服务

新开一个终端，在仓库根目录执行并保持运行：

```powershell
uv run --extra stand-editing python -m flight.quack_server
```

启动后服务会自动完成以下操作：
1. 安装并加载 DuckDB 的 `quack` 与 `spatial` 扩展（**新电脑首次运行需要联网下载扩展**）。
2. 在 `outputs/quack.token` 生成或复用本地访问令牌，并在 `quack:127.0.0.1:9494` 监听（仅允许本机回环地址）。
3. 自动生成 DataGrip 会话初始化脚本 `outputs/quack-datagrip.sql`。

需要停止服务时，在该终端按 `Ctrl+C`。

### 2.2 在 DataGrip 中新建数据库连接

1. 在 DataGrip 中新建数据源，选择 **DuckDB**。
2. 将连接 **URL** 设置为（将 `<仓库绝对路径>` 替换为本机实际路径，并使用正斜杠 `/`）：

```text
jdbc:duckdb:;session_init_sql_file=<仓库绝对路径>/outputs/quack-datagrip.sql
```

示例：

```text
jdbc:duckdb:;session_init_sql_file=D:/code/adsb-processing/outputs/quack-datagrip.sql
```

3. 确认 2.1 的 Quack 服务处于运行状态，点击 **Test Connection**。会话会自动加载 `quack`、`ATTACH` 数据库、`USE adsb.main` 并加载 `spatial` 扩展。

> **注意**：请勿在 Quack 服务运行时用 DataGrip 直接打开同一个 `.db` 文件，否则会触发文件锁冲突。

---

## 3. 构建前端

航班工作台与机场图编辑工作台共用同一套浏览器前端。首次在新电脑上运行，或拉取前端更新后，在仓库根目录执行：

```powershell
pnpm --dir frontend/workbench install --frozen-lockfile
pnpm --dir frontend/workbench build
```

构建产物会写入 `src/airport_workbench/web_dist/`（Git 忽略）。若仅运行命令行批量匹配，可跳过此步骤。前端开发热更新、OpenAPI 类型生成与回归测试见 [Workbench 前端指南](../frontend/workbench/README.md)。

---

## 4. 启动日常任务

完成上述准备后，可按需启动以下三类任务（均从仓库根目录运行）。

### 4.1 航班工作台（交互式筛选、机位编辑与匹配）

```powershell
uv run --extra stand-editing python -m src --workbench
```

默认自动在浏览器打开 `http://127.0.0.1:8765/`（可在 `config.local.toml` 的 `[workbench]` 中调整端口或禁用自动打开）。此模式下机场图为**只读**。

主要操作：
1. **筛选航班**：在「航班」页按航班号/ID、进出港、匹配状态、观测点数、机位或日期起止筛选，点击「过滤」生效。机位下拉支持搜索、多选与空机位；日期按航班开始日期计算（含起止当天）。
2. **提交匹配**：勾选待匹配航班（支持跨页、本页或当前筛选的全部结果），点击「匹配所选航班」提交任务。
3. **地图对比**：将航班加入地图，对比虚线原始轨迹与实线匹配路径。地图展示集合独立于待匹配集合，可点击「并排」同时浏览目录与地图并拖动分隔线。
4. **观测详情**：点击「详情」查看按时间排序的观测记录（默认每页 100 条），支持单条观测定位到地图及展开全部字段。
5. **编辑机位**：机位列支持直接编辑，保存时在一个事务内更新该 `flight_id` 的全部观测（离港写 `adsb_202406_dep.dep_stand_position`，进港写 `adsb_202406_arr.arr_stand_position`，清空写 `NULL`）。

> 匹配任务与路径缓存在服务端内存中，关闭浏览器标签页不会停止服务；按 `Ctrl+C` 关闭服务时，正在处理的航班会完成，其余排队任务取消。重启后需重新匹配，但已提交的机位编辑已持久化到 DuckDB。

### 4.2 批量路径匹配（离线批处理与报告输出）

```powershell
uv run --extra stand-editing python -m src
```

批处理以只读连接依次处理进港和离港，按 `flight_id` 排序，每处理 100 条航班刷新结果并打印进度。正常的匹配失败会记录原因并继续处理下一条。

- **小规模验证**：在 `config.local.toml` 的 `[batch]` 中设置 `limit = 10`（进、离港各最多 10 条；设为 `0` 生成零航班报告；省略则处理全部）。
- **输出目录**：每次运行按北京时间创建 `outputs/path_map/<YYYYMMDD_HHMMSS>/`：

| 文件 | 内容 |
|---|---|
| `graph.json` | 本次匹配使用的机场图快照。 |
| `paths.jsonl` | 按有向边序列去重的路径，关联图内容标识 `graph_id`。 |
| `matches.jsonl` | 每条航班的匹配结果。成功记录以 `path_id` 引用路径；失败记录保存分类和原因。 |
| `summary.json` | 整次运行及进港、离港两个批次的统计（全部完成后写入）。 |

- **统计口径**：批量报告与航班工作台共用航班总数、成功数、失败数、成功率（以已完成航班为分母）、失败分类与匹配耗时。批量报告额外记录实际运行耗时与去重路径数；工作台额外提供等待/运行中航班数（可通过 `GET /api/matches` 查询，重复传入 `task_id` 限定范围）。

### 4.3 机场图构建与编辑

机场路网先离线构建，再经人工检查和修复，最后作为已确认的 JSON 提供给航班匹配（不依赖 DuckDB 与 Quack）：

```mermaid
flowchart LR
    subgraph G["机场场面图构建与编辑"]
        A["traffic / OSM"] --> B["原始图<br/>_raw.json"]
        B --> C["编辑工作台"]
        C --> D["已确认图<br/>_final.json"]
    end

    subgraph F["航班轨迹处理"]
        E["航班工作台 / 批处理"] --> H["查询与匹配"]
    end

    D --> E
```

#### 直接查看或编辑已有机场图

```powershell
uv run python -m airport_workbench --graph data/graphs/zbaa_final.json
```

省略 `--graph` 时默认加载 `data/graphs/zbaa_final.json`。页面中的「保存」会直接写回该文件。

#### 从原始图生成独立修订版

需要保留原图并写出新文件时，使用修复脚本（目标文件已存在时更换文件名或加 `--force`）：

```powershell
uv run python scripts/repair_airport_graph.py `
  --input data/graphs/zbaa_raw.json `
  --output data/graphs/zbaa_final.json
```

修复模式中的「保存」和「完成」均写入 `--output`，「完成」随后自动停止服务。

> 以上两个入口默认监听 `http://127.0.0.1:8765/`，均支持 `--host`、`--port`、`--no-browser`（例如 `--port 8877 --no-browser`）。

#### 编辑器操作要点

- 页面初始处于查看状态，可搜索节点、边端点或机位编号 `ref`，也可打开拓扑检查。
- 点击「编辑图」进入编辑，左侧工具支持切分、绘制缺失连接、恢复来源连接、合并重合节点、人工吸附和删除；属性浮层可修改 `aeroway`（`taxiway`、`runway`、`parking_position`）、`name` 和 `ref`。
- 「保存属性」仅应用到当前会话（支持「撤销」）；点击顶部「保存」或「完成」才会校验并写入 JSON 文件。
- 确认完成后，将图路径填入 `config.local.toml` 的 `graph_path` 即可供航班匹配使用。

#### （可选）从 OSM 重新生成原始机场图

需先执行 `uv sync --group graph-build`：

```powershell
uv run --group graph-build python scripts/build_airport_graph.py `
  --airport ZBAA `
  --projection EPSG:32650 `
  --output data/graphs/zbaa_raw.json
```

| 参数 | 用途 |
|---|---|
| `--airport` | ICAO 机场代码。 |
| `--projection` | 适合该机场的米制投影坐标系。 |
| `--output` | 输出路径，省略时默认为 `data/graphs/<icao小写>_raw.json`。 |
| `--force` | 允许覆盖已有输出文件。 |

---

## 5. 配置参考（`config.local.toml`）

| 配置项 | 默认值 | 用途 |
|---|---|---|
| `database.path` | 必填 | DuckDB 数据库文件路径。 |
| `database.quack_uri` | 未启用 | 设为 `'quack:127.0.0.1:9494'` 以通过 Quack 并发访问数据库。 |
| `graph_path` | `data/graphs/zbaa_final.json` | 批处理与航班工作台共用的机场图路径。 |
| `batch.output_dir` | `outputs/path_map` | 批量匹配报告输出父目录。 |
| `batch.limit` | 不限制 | 进港与离港各自的航班数上限。 |
| `workbench.host` | `127.0.0.1` | 航班工作台监听地址。 |
| `workbench.port` | `8765` | 航班工作台监听端口。 |
| `workbench.open_browser` | `true` | 启动航班工作台时自动打开浏览器。 |
| `workbench.display_timezone` | `Asia/Shanghai` | 航班目录与日期筛选使用的时区。 |
| `matching.*` | `MatchConfig` 默认值 | 算法参数，详见 [匹配算法 §6 参数配置与批量执行](path_map.md#6-参数配置与批量执行)。 |

---

## 6. 常见问题

- **数据库打不开或报文件被占用**：确认从仓库根目录启动、`database.path` 路径正确；若启用了 `quack_uri`，确认 Quack 服务已启动；若启动 Quack 时报锁冲突，先关闭 DataGrip 或其他直接打开该 `.db` 文件的进程。
- **Quack 首次启动失败**：首次启动需联网下载 `quack` 与 `spatial` 扩展，请检查网络环境；另外 `quack_uri` 仅允许 `quack:127.0.0.1:9494`。
- **DataGrip 连接失败**：确认 Quack 服务正在运行、`outputs/quack-datagrip.sql` 已生成，且 JDBC URL 中的 `session_init_sql_file` 使用了本机实际绝对路径（正斜杠）。
- **页面提示前端尚未构建（HTTP 503）**：执行第 3 节的 `pnpm` 安装与构建命令后重启后端服务。
- **机场图加载失败**：检查 `graph_path` 路径和图文件校验报错。
- **需要持久化保留匹配路径与统计**：使用第 4.2 节的批量匹配入口生成带图快照的持久化报告。
