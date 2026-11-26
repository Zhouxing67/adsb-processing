# 数据库 SQL 规范与使用指南（PostgreSQL）

本目录统一维护 PostgreSQL（`adsb` / `adsb_test`）的核心 DDL、质量检查与导出查询模板，供 DataGrip / `psql` 直接执行。

## 目录结构

| 路径 | 用途 |
|---|---|
| `schema/01_core_tables.sql` | 5 张核心业务表与按月分区辅助函数显式 DDL（单一事实来源）。 |
| `analysis/quality_checks.sql` | 按月汇总、点数分布、冲突字段、分区健康及验证航班集检查模板。 |
| `export/export_templates.sql` | 常用导出查询模板（去重机位清单、按最小点数导出进/离港轨迹）。 |

## 核心表与约定

- **`public.flights`**：航班主表（主键 `flight_pk`，业务唯一键 `(movement, flight_id)`），保存航班静态元数据、起止时间/点数摘要、多值冲突记录（`conflict_fields`）及独立的人工修正机位（`stand_override` / `stand_is_overridden`）。
- **`public.adsb_observations`**：进/离港合并的场面轨迹窄表，按 `ts` 按月原生分区（`PARTITION BY RANGE (ts)`），配 `(flight_pk, ts)` 复合索引。
- **`public.ingest_batches`**：按月入库台账表，记录源文件、导入时间及进/离港行数与航班数。
- **`public.route_library`**：滑行路径库表，配 OD 复合索引 `idx_route_library_od (graph_id, movement, stand_ref, runway_ref)`。
- **`public.match_issues`**：工作台归档的匹配异常航班表。
- **时区与单位约定**：
  - 所有时间列统一存 `TIMESTAMPTZ`（原始北京时间按 `Asia/Shanghai` 解析入库）。
  - `groundspeed` 单位为节（`kt`），在入库清洗阶段完成 `km/h -> kt` 换算。

## 常见操作流程

### 1. 直接从原始 CSV 导入一个月份

```powershell
.venv\Scripts\python.exe scripts\ingest_csv_to_postgres.py data\ADS-B\M_adsb_data_2024-06-2.csv --source-month 2024-06
```

- 同一 `source_month` 可安全幂等重跑（单事务内替换当月观测点，完整保留工作台人工修正的 `stand_override`）。

### 2. 回滚删除某个月份

```sql
BEGIN;
DELETE FROM public.adsb_observations WHERE source_month = '2024-07';
DELETE FROM public.flights f
WHERE f.source_month = '2024-07'
  AND NOT EXISTS (SELECT 1 FROM public.adsb_observations o WHERE o.flight_pk = f.flight_pk);
DELETE FROM public.ingest_batches WHERE source_month = '2024-07';
COMMIT;
```
