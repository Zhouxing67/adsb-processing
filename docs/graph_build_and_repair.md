# 机场图建图与修复脚本使用说明

机场图采用离线生成、人工检查、生产加载三个阶段。匹配主过程只读取已经确认的
`AirportGraph` JSON，不会导入 `traffic`，也不会在运行中重新下载或构造机场图。

```text
traffic 机场/OSM 数据
        │ build_airport_graph.py
        ▼
<icao>_raw.json
        │ repair_airport_graph.py + Workbench
        ▼
<icao>_final.json
        │ load_graph()
        ▼
匹配主过程
```

## 1. 准备环境

在仓库根目录执行：

```powershell
uv sync --group graph-build
```

`traffic` 只属于 `graph-build` 可选依赖组。普通匹配环境不需要安装或导入它。

## 2. 构造原始机场图

脚本位置：`scripts/build_airport_graph.py`。

必须提供：

- `--airport`：ICAO 机场代码，例如 `ZBAA`、`KJFK`；
- `--projection`：适用于该机场的米制投影 CRS，例如 `EPSG:32650`；
- `--output`：可选。省略时写入 `data/graphs/<icao小写>_raw.json`。

北京首都机场示例：

```powershell
uv run python scripts/build_airport_graph.py `
    --airport ZBAA `
    --projection EPSG:32650
```

指定输出文件：

```powershell
uv run python scripts/build_airport_graph.py `
    --airport ZBAA `
    --projection EPSG:32650 `
    --output data/graphs/zbaa_raw.json
```

投影必须满足以下条件：

- 是投影坐标系，不能使用 `EPSG:4326` 等经纬度坐标系；
- 水平单位是米，因为边长、搜索半径、吸附距离和匹配参数均以米解释；
- 适合机场所在区域。脚本不会自动猜测投影，以保证结果可复现。

脚本完成后会：

1. 验证边端点、来源链和来源区间；
2. 原子化保存 JSON；
3. 使用生产环境的 `load_graph()` 回读；
4. 比较保存前后的 `graph_id`；
5. 输出投影、节点数、边数、来源数和所有 `build_issues`。

输出已经存在时脚本默认停止。确认需要替换时添加 `--force`：

```powershell
uv run python scripts/build_airport_graph.py `
    --airport ZBAA `
    --projection EPSG:32650 `
    --force
```

## 3. 检查和修复机场图

脚本位置：`scripts/repair_airport_graph.py`。

```powershell
uv run python scripts/repair_airport_graph.py `
    --input data/graphs/zbaa_raw.json `
    --output data/graphs/zbaa_final.json
```

脚本加载原始图并启动本地 Airport Workbench。默认地址为
`http://127.0.0.1:8765`，并自动打开浏览器。可以在工作台中检查构图问题、切分边、
合并或删除节点、恢复连接以及撤销编辑。

完成检查后，点击 Workbench 中的“完成”。程序会验证并保存最终图，然后停止本地服务。
仅点击“保存”会写入目标文件，但不会结束工作台。

常用选项：

```powershell
# 使用其他端口
uv run python scripts/repair_airport_graph.py `
    --input data/graphs/zbaa_raw.json `
    --output data/graphs/zbaa_final.json `
    --port 8877

# 不自动打开浏览器
uv run python scripts/repair_airport_graph.py `
    --input data/graphs/zbaa_raw.json `
    --output data/graphs/zbaa_final.json `
    --no-browser
```

目标文件已经存在时，修复脚本同样默认停止。确认替换时添加 `--force`。建议保留原始图，
把修复结果写入不同的 `_final.json` 文件，避免丢失可追溯的原始构图产物。

## 4. 最终图用于匹配

确认后的图由主过程直接加载：

```powershell
uv run python src/__main__.py `
    --graph data/graphs/zbaa_final.json `
    --arrivals data/ADS-B/more_15_arr.csv `
    --departures data/ADS-B/more_15_dep.csv `
    --output outputs/path_map
```

最终图包含投影定义和内容 `graph_id`。匹配输出会记录对应的 `graph_id`，从而避免路径结果
被错误地解析到另一版本的机场图上。
