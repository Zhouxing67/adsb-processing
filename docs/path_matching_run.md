# 路径匹配运行说明

路径匹配直接加载已确认的 AirportGraph JSON，不会重新构图或下载 OSM 数据。运行有两种方式：

| 方式 | 入口 | 适用场景 | 结果保存 |
|---|---|---|---|
| 后台批量匹配（默认） | `src/__main__.py` | 自动处理所选数据集，生成批量报告后退出。 | 写入独立的运行目录。 |
| Workbench 交互匹配 | `src/__main__.py --workbench` | 浏览完整目录，选择最多 5 条后按需匹配。 | 当前服务会话内保存。 |

本文中的“后台批量匹配”指不启动界面的计算流程。普通命令仍占用当前终端，不会自动脱离终端成为后台服务。

机场图的准备见 [建图与修复说明](graph_build_and_repair.md)，算法原理见 [path_map 设计说明](path_map.md)。

## 1. 准备环境与输入

以下 PowerShell 命令均在仓库根目录执行：

```powershell
uv sync
```

匹配无需安装 `graph-build` 可选依赖组。准备好：

- 已检查的机场图，例如 `data/graphs/zbaa_final.json`；
- 航班观测 CSV，例如 `data/ADS-B/more_15_arr.csv` 和 `more_15_dep.csv`。

CSV 必须包含 `flight_id`、`timestamp`、`longitude`、`latitude`。同一文件内相同 `flight_id` 的记录组成一条航班轨迹；不同来源文件中的同名航班保持独立，经纬度使用 WGS84；其他列作为附加信息保留。Workbench 能识别现有数据中的 `NUMBER` 航班号列。

## 2. 后台批量匹配

### 完整运行

```powershell
uv run python src/__main__.py `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv `
    --departures data/ADS-B/more_15_dep.csv `
    --output outputs/path_map
```

上述命令依次处理进港和离港两个批次，复用机场图的匹配器。只指定一类输入时仅运行该批次。正常的单航班匹配失败会记录原因，其他航班继续执行。每处理 100 条航班打印进度并刷新结果文件；每个批次结束时打印统计。

两个航班参数都省略时使用默认进港、离港文件。只显式提供其中一个参数时，仅处理该参数对应的数据集；不会再隐式补入另一类默认文件。

### 小规模验证

```powershell
uv run python src/__main__.py --limit 10
```

`--limit 10` 表示每个批次最多处理 10 条航班，两批合计最多 20 条，按 `flight_id` 的确定顺序选取，不是随机抽样。

### 参数

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--graph` | `data/graphs/zbaa_final.json` | 已有机场图。 |
| `--arrivals` | 两类均未指定时使用 `data/ADS-B/more_15_arr.csv` | 进港 CSV；仅指定离港时不加载进港。 |
| `--departures` | 两类均未指定时使用 `data/ADS-B/more_15_dep.csv` | 离港 CSV；仅指定进港时不加载离港。 |
| `--output` | `outputs/path_map` | 运行目录的父目录。 |
| `--limit` | 不限制 | 每批最多处理的航班数。 |
| `--input-timezone` | `UTC` | 解释 CSV 中无时区的时间；已有时区的时间转换为 UTC。 |
| `--search-radius` | 40 | 初始候选搜索半径，米。 |
| `--max-candidates` | 6 | 每个观测的候选数量上限。 |
| `--gps-sigma` | 10 | 观测距离误差参数，米。 |
| `--transition-beta` | 20 | 转移距离误差参数，米。 |

最大搜索半径使用 MatchConfig 默认的 120 米，统一 CLI 没有对应参数，两种模式都使用该默认值。

### 输出文件

每次运行以 Asia/Shanghai 时间创建新的 `YYYYMMDD_HHMMSS` 子目录：

```text
outputs/path_map/<运行时间>/
├── graph.json       # 本次匹配使用的机场图快照
├── paths.jsonl      # 去重后的有向路径及其图内容标识
├── matches.jsonl    # 每条航班的匹配结果或失败原因
└── summary.json    # 全部及分批统计、耗时和成功率
```

`matches.jsonl` 中成功航班通过 `path_id` 引用 `paths.jsonl`。相同有向边序列共用同一条路径记录；失败航班的 `path_id` 为 `null`，并附带失败分类及原因。

解释或恢复路径时应使用该运行目录内的图快照。另一版本的图可能具有相同节点 ID，但不一定具有相同几何或连接关系。

`summary.json` 在整次匹配完成后生成。中途用 `Ctrl+C` 停止时，不应将已有部分文件当作完整运行报告。程序不自动恢复中断任务，也不覆盖已有同名运行目录。

统一入口会在进入批量或 Workbench 生命周期前构造并验证全部 `Flight`，包括时间、坐标及必填值。输入无效时不会调用匹配器、启动服务或创建批量输出目录。

## 3. 启动 Workbench 交互匹配

### 加载全部航班

如果输入中的无时区时间表示北京时间，可按下列方式启动：

```powershell
uv run python src/__main__.py `
    --workbench `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv `
    --departures data/ADS-B/more_15_dep.csv `
    --input-timezone Asia/Shanghai `
    --display-timezone Asia/Shanghai
```

默认自动打开浏览器，本地地址为 [http://127.0.0.1:8765](http://127.0.0.1:8765)。加载航班后进入航班侧栏模式，不显示图编辑工具，也不允许修改机场图。

只查看一类航班时，仅传对应 CSV 参数即可。例如：

```powershell
uv run python src/__main__.py `
    --workbench `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv
```

此命令使用默认 UTC 时间解释与展示。两个 CSV 参数都不传时加载默认进港和离港文件。若所选文件缺失、加载失败或合计没有航班，程序报错退出，不会退化为图编辑模式。

### 操作流程

1. 在侧栏按航班号或 ID 搜索，按进出港类型或匹配状态筛选。
2. 勾选 1～5 条航班，地图显示原始轨迹；已选航班通过 A～E 标记和颜色对应。
3. 点击“匹配所选航班”，等待各航班状态更新。服务端在后台执行，页面仍可操作。
4. 成功结果自动显示路径；同一航班的轨迹和路径使用同色，虚线与实线区分两者。
5. 使用“定位”“原始轨迹”“匹配路径”比较结果，或进入详情查看观测记录。失败原因显示在对应航班条目中。

匹配成功解释的是保留观测，不能视为每个原始点都已贴合道路。候选不足、无法连通、全程无沿网移动，以及当前不支持的自环候选，都可能产生明确的匹配失败。

### 服务参数与关闭

| 参数 | 默认值 | 含义 |
|---|---|---|
| `--graph` | `data/graphs/zbaa_final.json` | 已有机场图。 |
| `--arrivals` / `--departures` | 默认进港、离港文件 | 两者均省略时加载默认文件；只提供一个时只加载该类。 |
| `--input-timezone` | `UTC` | 无时区输入时间的解释时区。 |
| `--display-timezone` | `UTC` | 目录摘要时间的展示时区。 |
| `--host` | `127.0.0.1` | 服务监听地址。 |
| `--port` | `8765` | 服务端口。 |
| `--no-browser` | 不启用 | 只启动服务，不自动打开浏览器。 |

端口冲突或希望手动打开浏览器时：

```powershell
uv run python src/__main__.py `
    --workbench `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv `
    --port 8877 `
    --no-browser
```

然后访问 [http://127.0.0.1:8877](http://127.0.0.1:8877)。在运行终端按 `Ctrl+C` 结束服务；关闭标签页不会结束服务。匹配结果保存在服务内存中，浏览器刷新不会重新启动服务，但服务重启后结果不会自动恢复。

## 4. 两种模式的差异

| 项目 | 默认批量模式 | `--workbench` 模式 |
|---|---|---|
| 航班文件参数 | `--arrivals`、`--departures` | 相同 |
| 匹配范围 | 自动处理所选数据集，可按类限制数量 | 由用户选择，每次 1～5 条 |
| 候选数量默认值 | 6 | 6 |
| 匹配参数调整 | 半径、候选数、σ、β | 相同 |
| 无时区时间解释 | `--input-timezone` | 相同 |
| 结果持久化 | 图快照、路径、航班结果和统计文件 | 会话内结果，无批量文件自动导出 |

两种模式复用同一份数据加载和 `MatchConfig` 构造逻辑。输入时间已有时区时按原时区转换为 UTC；无时区时间按 `--input-timezone` 解释后转换为 UTC。

`python -m airport_workbench` 保留为纯机场图查看／编辑入口，不再接受航班文件和匹配参数。批量模式传入服务参数或 `--display-timezone`、Workbench 模式传入 `--output` 或 `--limit` 都会在加载数据前报用法错误。已删除的 `--visualize`、`--success-samples`、`--failure-samples` 直接报错。

## 5. 常见问题

- **找不到机场图**：先按建图与修复文档生成最终图，或用 `--graph` 指定已有文件；匹配流程不会自动建图。
- **找不到 CSV**：相对路径以启动命令所在目录为基准；在仓库根目录运行，或改用绝对路径。
- **批量只想处理少量数据**：使用 `--limit`，它分别限制所选的每个批次；`--limit 0` 不执行航班匹配，但仍会生成零航班统计及输出文件。
- **Workbench 没有航班列表**：统一入口会拒绝空数据集；检查所选 CSV 内容和字段。
- **成功却没有想象中的精确起止位置**：Path 表示完整图边序列，首尾边不按观测位置截断；长度是完整边累计长度。
- **需要保存交互匹配的结果**：当前界面没有批量结果导出流程；需要持久化报告时使用后台批量入口。

查看当前入口的完整帮助：

```powershell
uv run python src/__main__.py --help
uv run python -m airport_workbench --help
```
