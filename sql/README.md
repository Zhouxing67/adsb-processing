# 数据库 SQL 规范与使用指南

本目录统一维护 DuckDB（`adsb.db`）的建表、迁移、按月增量入库、质量检查与导出脚本，供 DataGrip（通过 Quack 会话）直接执行。

## 目录结构

| 路径 | 用途 |
|---|---|
| `schema/01_core_tables.sql` | 核心业务表（`main.adsb_arr`、`main.adsb_dep`、`main.ingest_batches`）显式 DDL。 |
| `schema/02_airport_boundary.sql` | 导入/刷新机场边界表 `main.airport_boundary`。 |
| `migrations/001_normalize_202406_tables.sql` | 一次性迁移脚本：将旧 `adsb_202406_arr`/`dep` 原地重命名为 `adsb_arr`/`dep` 并补充 `source_month = '2024-06'`，保留所有人工修正过的机位。 |
| `ingest/ingest_month.sql` | 单月 CSV 增量导入脚本（Staging 清洗 → 幂等替换当月 → 跨月去重写入 → 登记批次）。 |
| `analysis/quality_checks.sql` | 按月汇总、点数分布、机位/跑道一致性及验证航班集检查模板。 |
| `analysis/filter_garbage_flights.sql` | 人工前置异常/垃圾轨迹过滤脚本（只读占比预览、抽样复核、可选刷新 `flight_quality_metrics`/`flight_whitelist` 或清理异常航班）。 |
| `export/export_templates.sql` | 常用 CSV 导出模板（按最小点数导出进/离港、导出机位清单）。 |

## 核心表与约定

- **`main.adsb_arr`** / **`main.adsb_dep`**：进港与离港场面 ADS-B 观测主表，所有月份数据统一写入这两张表，通过 `source_month`（如 `'2024-06'`）区分导入批次。
- **`main.ingest_batches`**：批次台账表，记录每个 `source_month` 的源文件、导入时间及进/离港行数与航班数。
- **`main.airport_boundary`**：机场地理边界，用于导入时的空间粗筛（`ST_Covers`）。
- **`main.route_library`**：滑行路径库表（由 `src/route_library/repository.py` 自动维护建表与索引）。
- **命名与单位约定**：
  - 表名与列名统一小写蛇形，不含月份后缀。
  - 无时区 `timestamp` 按北京时间（`Asia/Shanghai`）存储，Python 读取时统一转为 UTC。
  - `groundspeed` 单位为节（`kt`），仅在 `ingest_month.sql` 的临时表阶段完成 `km/h -> kt` 换算，绝不对正式表做全表乘系数更新。

## 常见操作流程

### 1. 导入一个新月份（例如 `2024-07`）

1. 打开 `sql/ingest/ingest_month.sql`。
2. 修改顶部 `source_month` 与 `csv_path` 变量。
3. 在 DataGrip 中按顺序执行全脚本。
4. 检查脚本末尾输出的 `main.ingest_batches` 汇总行。

### 2. 重跑或回滚某个月份

- **重跑当月**：直接再次执行 `sql/ingest/ingest_month.sql`（脚本会在事务内先删除该 `source_month` 的旧数据再重新写入，不影响其他月份）。
- **回滚删除某月**：
  ```sql
  BEGIN TRANSACTION;
  DELETE FROM main.adsb_arr WHERE source_month = '2024-07';
  DELETE FROM main.adsb_dep WHERE source_month = '2024-07';
  DELETE FROM main.ingest_batches WHERE source_month = '2024-07';
  COMMIT;
  ```
