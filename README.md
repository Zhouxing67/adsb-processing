# ADS-B 航班路径匹配

项目使用 ADS-B 地面观测和机场路网，估计航班经过的有向边序列。当前工作流以首都机场（ZBAA）为例。Python 依赖由 `uv` 管理，浏览器工作台由独立的 Vite + `pnpm` 项目构建，数据持久化与并发访问由 **PostgreSQL** 提供支持。

## 快速开始

新电脑首次部署（安装依赖、初始化 PostgreSQL 与 `config.local.toml`、导入原始 CSV、构建前端）请按步骤执行 **[快速上手与运行指南](docs/quickstart.md)**。

完成初始化后，从仓库根目录运行常用任务：

| 任务 | 命令 | 说明 |
|---|---|---|
| 导入原始 CSV | `uv run python scripts/ingest_csv_to_postgres.py <csv> --source-month <YYYY-MM>` | 流式清洗原始 ADS-B CSV 并幂等导入 PostgreSQL 分区表。 |
| 构建前端 | `pnpm --dir frontend/workbench build` | 编译浏览器工作台静态资源（首次或前端更新后执行）。 |
| 航班工作台 | `uv run python -m src --workbench` | 筛选航班、编辑机位、提交匹配并对比轨迹（机场图只读）。 |
| 批量匹配 | `uv run python -m src` | 离线顺序匹配全部航班，输出路径、结果与统计报告。 |
| 路径库入库 | `uv run python -m route_library import outputs/path_map/<run_id>` | 将批匹配结果去重导入 PostgreSQL `public.route_library` 表（加 `--append` 可增量追加）。 |
| 机场图编辑 | `uv run python -m airport_workbench` | 检查和修复机场路网 JSON。 |

## 文档导航

- **操作指南**：[快速上手与运行指南](docs/quickstart.md) —— 涵盖环境安装、PostgreSQL 配置与入库、DataGrip 连接、前端构建、工作台操作、批量匹配、路径库入库、机场图构建修复、配置参考与常见问题。
- **架构与算法**：
  - [机场图数据设计](docs/airport_surface.md) —— 拓扑、几何、来源区间、业务索引与版本控制。
  - [匹配算法](docs/path_map.md) —— 候选生成、有向对偶图转角约束、OD 约束与两阶段 Viterbi 解码。
- **开发指南与排查记录**：
  - [数据库 SQL 规范](sql/README.md) —— PostgreSQL 核心 DDL、质量检查与导出查询模板。
  - [机场图模块指南](src/airport_surface/README.md) —— `airport_surface` 文件职责与图字段约定。
  - [匹配模块开发指南](src/path_map/README.md) —— `path_map` 编程接口与模块职责。
  - [路径库模块指南](src/route_library/README.md) —— `route_library` 表结构、OD 索引查询与独立入库规则。
  - [Workbench 前端指南](frontend/workbench/README.md) —— 前端架构、OpenAPI 契约生成与回归测试。
  - [Windows Access Violation 排查记录](docs/windows_access_violation.md) —— 间歇性运行时内存损坏的纯 Python 复现样例与排查方法。
