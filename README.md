# ADS-B 航班路径匹配

项目使用 ADS-B 地面观测和机场路网，估计航班经过的有向边序列。当前工作流以首都机场（ZBAA）为例。Python 依赖由 `uv` 管理，浏览器工作台由独立的 Vite 项目构建。

| 任务 | 从仓库根目录启动 | 说明 |
|---|---|---|
| 批量匹配 | `uv run --extra stand-editing python -m src` | 从 DuckDB 顺序读取航班，输出路径、结果和统计文件。 |
| 航班工作台 | `uv run --extra stand-editing python -m src --workbench` | 筛选航班、编辑航班机位、提交匹配并比较地图轨迹。机场图在此模式中只读。 |
| 机场图编辑 | `uv run python -m airport_workbench` | 检查和修复机场路网。 |

### 启动quack以并发访问duckdb

设置 `config.local.toml` 的 `[database]` 下启用
`quack_uri = 'quack:127.0.0.1:9494'`，并保留指向实际数据库的 路径。
在项目根目录启动 Quack 服务并保持终端运行。

```powershell
$env:PYTHONPATH = 'src'
uv run --extra stand-editing python -m flight.quack_server
```

设置datagrip数据源的url为：

```url
jdbc:duckdb:;session_init_sql_file=D:/code/adsb-processing/outputs/quack-datagrip.sql
```

## 文档

- [路径匹配运行说明](docs/path_matching_run.md)介绍配置、航班工作台操作、结果文件和统计口径。
- [机场图建图与修复](docs/graph_build_and_repair.md)介绍如何生成、编辑并交付机场图。
- [机场图数据设计](docs/airport_surface.md)解释拓扑、几何、来源区间与版本控制。
- [匹配算法](docs/path_map.md)解释候选生成、沿网转移和 Viterbi 解码。
- [匹配模块开发指南](src/path_map/README.md)和 [Workbench 前端指南](frontend/workbench/README.md)说明代码职责和测试入口。
