# ADS-B 航班路径匹配

项目使用 ADS-B 地面观测和机场路网，估计航班经过的有向边序列。当前工作流以首都机场（ZBAA）为例。Python 依赖由 `uv` 管理，浏览器工作台由独立的 Vite + `pnpm` 项目构建，DuckDB 并发访问由 Quack 提供支持。

## 快速开始

新电脑首次部署（安装依赖、配置 `config.local.toml`、启动 Quack 与 DataGrip 连接、构建前端）请按步骤执行 **[快速上手与运行指南](docs/quickstart.md)**。

完成初始化后，从仓库根目录运行常用任务：

| 任务 | 命令 | 说明 |
|---|---|---|
| Quack 服务 | `uv run --extra stand-editing python -m flight.quack_server` | 提供 DuckDB 并发访问并生成 DataGrip 初始化脚本（保持后台运行）。 |
| 构建前端 | `pnpm --dir frontend/workbench build` | 编译浏览器工作台静态资源（首次或前端更新后执行）。 |
| 航班工作台 | `uv run --extra stand-editing python -m src --workbench` | 筛选航班、编辑机位、提交匹配并对比轨迹（机场图只读）。 |
| 批量匹配 | `uv run --extra stand-editing python -m src` | 离线顺序匹配全部航班，输出路径、结果与统计报告。 |
| 机场图编辑 | `uv run python -m airport_workbench` | 检查和修复机场路网 JSON。 |

## 文档导航

- **操作指南**：[快速上手与运行指南](docs/quickstart.md) —— 涵盖环境安装、Quack & DataGrip、前端构建、工作台操作、机场图构建修复、配置参考与常见问题。
- **架构与算法**：
  - [机场图数据设计](docs/airport_surface.md) —— 拓扑、几何、来源区间、业务索引与版本控制。
  - [匹配算法](docs/path_map.md) —— 候选生成、有向对偶图转角约束、OD 约束与两阶段 Viterbi 解码。
- **开发指南**：
  - [匹配模块开发指南](src/path_map/README.md) —— `path_map` 编程接口与模块职责。
  - [Workbench 前端指南](frontend/workbench/README.md) —— 前端架构、OpenAPI 契约生成与回归测试。
