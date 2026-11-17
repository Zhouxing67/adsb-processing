# 机场建图与 Workbench 工作流

机场图离线生成，再通过 Workbench 检查、编辑并保存。匹配过程加载已确认的图，不会重新下载 OSM 或在运行时建图。

```text
traffic / OSM → 原始图 _raw.json → 编辑工作台 → 已确认图 _final.json
                                                     ↓
                                         航班工作台查询与匹配
```

Workbench 只有两种后端会话：

| 会话 | 可用功能 | 图修改权限 |
|---|---|---|
| 编辑工作台 | 地图查看、要素搜索、拓扑检查、图编辑 | 点击“编辑图”后操作，保存到指定输出文件 |
| 航班工作台 | 航班筛选、选择、匹配、观测记录、地图对照 | 后端禁止修改机场图 |

两者使用同一个页面入口 `/`。不再提供独立的只读查看模式或 `/preview` 页面。只想查看图时，也启动编辑工作台，保持默认查看状态即可；进入页面不会自动保存。

## 1. 环境与前端构建

以下命令均在仓库根目录执行。建图环境：

```powershell
uv sync --group graph-build
```

`traffic` 仅用于离线建图。已有图的检查、编辑和航班匹配只需普通环境：

```powershell
uv sync
```

首次使用、拉取前端改动后，构建工作台：

```powershell
pnpm --dir frontend/workbench install --frozen-lockfile
pnpm --dir frontend/workbench build
```

前端源码位于 `frontend/workbench`，构建产物位于 `src/airport_workbench/web_dist`。React、Ant Design、Leaflet 由本地构建提供；在线底图仍需要网络。缺少构建时入口返回 503 和构建提示，不会回退旧页面。更新代码或构建后，请停止旧服务并重新启动。

## 2. 生成原始机场图

```powershell
uv run python scripts/build_airport_graph.py `
  --airport ZBAA `
  --projection EPSG:32650 `
  --output data/graphs/zbaa_raw.json
```

- `--airport`：ICAO 机场代码。
- `--projection`：适合机场区域、水平单位为米的投影 CRS，不能使用经纬度 CRS。
- `--output`：省略时为 `data/graphs/<icao小写>_raw.json`。
- `--force`：允许替换已经存在的输出文件；默认拒绝覆盖。

建图脚本校验图的端点与来源区间，原子保存 JSON，并通过生产用 `load_graph()` 回读核对 `graph_id`。完成后检查输出的构图问题，再进入工作台。

## 3. 打开编辑工作台

```powershell
uv run python scripts/repair_airport_graph.py `
  --input data/graphs/zbaa_raw.json `
  --output data/graphs/zbaa_final.json
```

已有最终图需要继续修改时，使用新的输出文件：

```powershell
uv run python scripts/repair_airport_graph.py `
  --input data/graphs/zbaa_final.json `
  --output data/graphs/zbaa_edited.json
```

默认打开浏览器，地址为 [http://127.0.0.1:8765/](http://127.0.0.1:8765/)。页面初始为查看状态，可搜索节点、边端点及机位编号 `ref`，或打开拓扑检查。搜索命中多条机位边时，从候选列表选择。

需要修改时点击地图工具区的“编辑图”：

- 左侧栏切换为切分、连线、来源恢复、合并、吸附和删除工具。
- 选中点或边后，属性浮层显示在地图中；`aeroway / name / ref` 可编辑，其他字段只读。
- `aeroway` 可选择 `taxiway`、`runway`、`parking_position`；机位边使用独立颜色。
- 修改属性后点击“保存属性”写入当前会话，图操作可撤销；写入图文件还需点击顶部“保存”或“完成”。

“保存”验证并写入 `--output`，服务继续运行；“完成”保存后结束服务。关闭浏览器标签不会停止服务；终端 `Ctrl+C` 停止服务，不会替你保存尚未保存的会话编辑。

输出文件已存在时默认停止；确需替换可添加 `--force`。保留原始图及独立的修订输出，便于比较和恢复。

## 4. 打开航班工作台

```powershell
uv run python src/__main__.py --workbench `
  --graph data/graphs/zbaa_final.json `
  --arrivals data/ADS-B/more_15_arr.csv `
  --departures data/ADS-B/more_15_dep.csv `
  --input-timezone UTC `
  --display-timezone UTC
```

仅查看进港或离港时，只传对应的一个 CSV 参数。输入的无时区时间由 `--input-timezone` 解释；若原始时间表示北京时间，将其设置为 `Asia/Shanghai`。当前后端仍在启动时读入所选 CSV，尚未迁移至数据库。

1. 在底部切换到“航班”，填写航班号/ID、进出港、状态及点数范围，点击“过滤”。修改条件不会立即影响已显示结果。
2. 在表格中选择航班，可跨页选择；“全部结果”选择已应用筛选条件对应的结果。
3. 点击“匹配所选航班”，确认后查看任务进度与成功/失败状态。
4. 将航班加入地图，比较原始轨迹与匹配路径；“详情”查看观测记录，“定位”返回地图。

底部页签可拖到内容区一侧分屏；拖回页签栏恢复单页。左右侧栏支持显隐和宽度调整。航班会话不显示“编辑图”入口，后端也会拒绝图写入。

匹配结果保存在当前服务会话中，刷新页面不等于重启服务；重启后需重新匹配。完整匹配参数、后台批量输出见 [路径匹配运行说明](path_matching_run.md)。

## 5. 地址、端口和关闭服务

编辑脚本与航班命令均支持：

| 参数 | 默认值 | 用途 |
|---|---|---|
| `--host` | `127.0.0.1` | 本地监听地址 |
| `--port` | `8765` | 服务端口 |
| `--no-browser` | 未启用 | 不自动打开浏览器 |

例如在编辑命令后添加 `--port 8877 --no-browser`，再手动打开 `http://127.0.0.1:8877/`。端口被占用时先停止旧服务，或改用另一端口。

若启动在图校验阶段失败，服务尚未运行；根据错误检查输入图，不能通过刷新页面解决。匹配输出关联图内容 `graph_id`，解释结果时必须使用对应版本的图。
