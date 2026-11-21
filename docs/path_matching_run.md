# 航班路径匹配运行说明

航班匹配使用 DuckDB 中的观测记录和已经确认的 AirportGraph JSON。批处理与航班工作台共享配置、匹配算法和统计口径。生成或修复机场图请参阅[机场图建图与修复](graph_build_and_repair.md)。

## 1. 准备环境和数据

从仓库根目录执行：

```powershell
uv sync --extra stand-editing
if (-not (Test-Path config.local.toml)) { Copy-Item config.example.toml config.local.toml }
```

已存在 `config.local.toml` 时直接编辑现有文件。设置 `[database].path` 指向包含 `main.adsb_202406_arr` 和 `main.adsb_202406_dep` 的 DuckDB 文件，并通过 `graph_path` 指定确认后的机场图。已有配置模板中的相对路径以仓库根目录为基准。本地配置由 Git 忽略。

```toml
graph_path = 'data/graphs/zbaa_final.json'

[database]
path = 'C:\data\identifier.db'
```

同一表中相同 `flight_id` 的观测组成一条航班轨迹。进港和离港中的同名航班分别处理。两张表的无时区 `timestamp` 按北京时间解释，匹配读取的观测时间转换为 UTC。工作台目录与日期筛选默认使用北京时间。

需要准备数据库时，参照离线的 [导入 SQL](../sql/import.sql)和[数据筛选 SQL](../sql/filter.sql)。
[导出 SQL](../sql/export.sql)与 [CSV 诊断工具](../scripts/csv_flights.py)供离线分析、诊断和测试使用。

要使用航班工作台，先[构建浏览器前端](../frontend/workbench/README.md)；仅运行批处理时可直接启动。

## 2. 选择运行模式

```powershell
# 后台批量匹配
uv run --extra stand-editing python -m src

# 航班工作台
uv run --extra stand-editing python -m src --workbench
```

`--workbench` 是航班入口的模式参数。其他选项从 `config.local.toml` 读取。纯机场图编辑使用 `python -m airport_workbench`，具体操作见[机场图建图与修复](graph_build_and_repair.md)。

### 批量匹配

批处理以只读连接依次处理进港和离港。它按 `flight_id` 排序，逐航班读取和校验观测，再将匹配结果写入文件。正常的匹配失败会记录原因并继续处理下一条；输入或程序异常可能终止批次。

小规模验证时，在 `[batch]` 中设置 `limit = 10`，进港和离港各最多处理十条航班。设为 `0` 可生成零航班报告；省略该项会处理全部航班。命令占用当前终端，执行完毕后退出。

### 航班工作台

默认在浏览器打开 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)。工作台以读写方式使用 DuckDB。启动前关闭其他持有数据库文件的连接，例如 DataGrip 中的活动会话。

1. 打开「航班」，按航班号或 ID、进出港、匹配状态、观测点数、机位或日期起止筛选。点击「过滤」应用条件。机位下拉支持搜索、多选和空机位。日期按航班开始日期计算，包含起止当天。
2. 勾选待匹配航班。可以跨页选择，也可以选择本页或当前筛选的全部结果。点击「匹配所选航班」提交任务。只勾选一条航班时仍会提交一个批次。
3. 将航班加入地图，比较虚线原始轨迹和实线匹配路径。地图展示集合独立于待匹配集合，可使用「并排」同时查看地图和航班目录并拖动分隔线调整比例。
4. 点击「详情」查看按时间排序的观测记录，默认每页一百条。单条观测可定位到地图，也可切换显示全部字段。

机位列支持直接编辑。保存时按现有 `flight_id` 在一个事务内更新对应航班的全部观测。离港使用 `adsb_202406_dep.dep_stand_position`，进港使用 `adsb_202406_arr.arr_stand_position`。清空机位写入 SQL `NULL`。

工作台匹配任务和路径缓存在服务会话内，关闭标签页后服务仍运行。按 `Ctrl+C` 关闭服务时，正在处理的航班会完成，剩余排队工作取消。服务重启后需要重新匹配；已提交的机位编辑保存在数据库中。

## 3. 配置参考

| 配置项 | 默认值 | 用途 |
|---|---|---|
| `database.path` | 必填 | DuckDB 数据库文件。 |
| `graph_path` | `data/graphs/zbaa_final.json` | 两种匹配模式共用的机场图。 |
| `batch.output_dir` | `outputs/path_map` | 批量报告父目录。 |
| `batch.limit` | 不限制 | 进港和离港各自的航班数上限。 |
| `workbench.host` | `127.0.0.1` | 服务监听地址。 |
| `workbench.port` | `8765` | 服务端口。 |
| `workbench.open_browser` | `true` | 启动时自动打开浏览器。 |
| `workbench.display_timezone` | `Asia/Shanghai` | 航班目录和日期筛选使用的时区。 |
| `matching.*` | `MatchConfig` | 两种模式共用的算法参数。见[参数与算法](path_map.md#8-参数批量执行与结果)。 |

例如，改用 8877 端口并手动打开浏览器：

```toml
[workbench]
port = 8877
open_browser = false
```

## 4. 读取结果

### 批量报告

每次运行按北京时间创建一个目录，形如 `outputs/path_map/<YYYYMMDD_HHMMSS>/`。

| 文件 | 内容 |
|---|---|
| `graph.json` | 匹配使用的机场图快照。 |
| `paths.jsonl` | 按有向边序列去重的路径，关联图内容标识 `graph_id`。 |
| `matches.jsonl` | 每条航班的匹配结果。成功记录以 `path_id` 引用路径；失败记录保存分类和原因。 |
| `summary.json` | 整次运行及进港、离港两个批次的统计。 |

批处理每处理一百条航班刷新结果文件并打印进度。整次运行完成后才写入 `summary.json`。提前终止时，已有 JSONL 是部分结果。解释或恢复路径时使用同次运行保存的图快照。

### 统计口径

后台报告与工作台共用航班总数、成功数、失败数、成功率、失败分类和匹配耗时。成功率以已完成航班为分母。批量报告另外记录实际运行经过的时间和去重路径数。工作台另外显示等待与运行中的航班数，通过 `GET /api/matches` 查询；重复传入 `task_id` 可限定统计范围。

匹配成功表示算法找到了满足当前约束的路径。准确率、被跳过的观测和算法限制见[匹配算法](path_map.md)。

## 5. 常见问题

- **数据库打不开**。检查是否从仓库根目录启动、配置的路径是否正确，以及是否有其他进程持有数据库。
- **机场图加载失败**。检查 `graph_path` 和图文件的校验错误；已有图的构建与修复独立进行。
- **页面提示尚未构建**。执行[前端构建命令](../frontend/workbench/README.md)后重启服务。
- **需要保留匹配路径和统计**。使用批量入口生成包含图快照的持久化报告。
