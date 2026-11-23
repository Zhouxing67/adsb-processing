# Windows 间歇性 Access Violation 与内存损坏排查记录

本文记录项目在 Windows 环境下（包括离线大批量路径匹配、机场图构建校验）遇到的间歇性 `Windows fatal exception: access violation` 及伴随的离奇运行时异常的排查过程、纯 Python 最小复现样例、根因分析与工程建议。

---

## 1. 复现环境

| 项目 | 值 |
|---|---|
| 操作系统 | `Windows-11-10.0.26200-SP0` |
| Python 版本 | `3.13.15 (main, Sep 1 2026, 14:16:48) [MSC v.1944 64 bit (AMD64)]`（`uv` 托管独立构建 `cpython-3.13-windows-x86_64-none`） |
| GIL 状态 | `True`（标准带 GIL 构建） |

---

## 2. 观测到的异常现象

在高频循环（例如大批量航班匹配、`validate_source_intervals` 遍历、或纯 Python 压力循环）中，同一份代码在不同运行次序下会随机出现以下**纯 Python 逻辑层面不可能发生**的异常：

| 异常表现 | 含义 |
|---|---|
| `AttributeError: 'str' object has no attribute 'get'` / `'LineString'` / `'code'` | 局部变量原本持有边属性 `dict`，运行中指针错位指向了其他对象（如 `'parking_position'`、`LineString` 或 `code` 对象）。 |
| `TypeError: 'int' object is not callable`（发生在 `tuple(...)` 调用处） | 连内置类型对象 `tuple` 的引用都被破坏。 |
| `MemoryError`（发生在返回空列表的列表推导式） | 并非真的内存耗尽，而是对象头/长度字段损坏导致分配异常。 |
| `ValueError: generator already executing` | 单线程同步代码中的全新生成器表达式 `<genexpr>` 出现状态位损坏。 |
| `Fatal Python error: _PyEval_EvalFrameDefault: Executing a cache.` | CPython 3.13 自适应字节码解释器在执行内联缓存时读到了损坏的指令/缓存状态。 |
| `Windows fatal exception: access violation`（或进程静默异常退出） | 野指针解引用，操作系统直接终止进程。 |

---

## 3. 二分排查过程

从最早暴露问题的 `build_airport_graph.py` 出发，逐层剥离依赖，得到如下对照结果：

| 阶段 | 测试内容 | 结果 | 结论 |
|---|---|---|---|
| 1 | `build_graph("ZBAA", "EPSG:32650")`（默认 GC） | 稳定失败（`AttributeError` / `TypeError` / `access violation`） | 问题可稳定触发。 |
| 2 | 同上，加 `gc.disable()` | 全部通过（`nodes=1963 edges=2739`） | 触发频率与 GC / 堆活动高度相关。 |
| 3 | 不导入 `traffic`，仅 `load_graph("data/graphs/zbaa_final.json")` + 循环 1,000 次 `derived_edges("nonexistent")` | 稳定复现（`AttributeError: 'LineString' object has no attribute 'get'`） | 排除 `traffic` 与 OSM 解析。 |
| 4 | 同样循环，加 `gc.disable()` | 通过 | 再次验证与堆分配/GC 压力高度相关。 |
| 5 | 零项目代码，仅测试单个第三方库 `import` + 纯 Python 循环 | `import numpy` 触发 `MemoryError`；`import pyproj` 触发 `AttributeError: 'code' object has no attribute 'get'` | 不是某一个特定 C 扩展（如 `shapely`）独有。 |
| 6 | **零第三方库**：仅导入 Python 标准库 + 纯内置数据结构（`list`/`tuple`/`dict`/`str`/`dataclass`）跑 5 轮 | 第 3 轮触发 `Windows fatal exception: access violation`，第 4 轮静默崩溃 | **彻底排除项目业务代码与所有第三方 C 扩展（`networkx`、`shapely`、`pyproj`、`numpy`、`duckdb` 等）。** |
| 7 | 同上纯标准库脚本，加 `gc.disable()` 跑 5 轮 | 虽全部打印 `PASS`，但第 1 轮仍出现 `ValueError: generator already executing` | 即使关闭循环 GC，单线程生成器状态仍偶发损坏，说明问题出在更底层的解释器或硬件层面。 |

---

## 4. 纯 Python 最小复现样例

以下脚本**不依赖任何第三方库和项目代码**，只使用 Python 标准库与内置数据结构（`list`、`tuple`、`dict`、`str`、`dataclass`）。在 PowerShell 中直接执行（连续跑 5 轮以覆盖随机性）：

```powershell
for ($t = 1; $t -le 5; $t++) {
    Write-Output "--- Run $t ---"
    .venv\Scripts\python.exe -X faulthandler -c "
import asyncio, email, inspect, pathlib, typing, decimal, json, re, urllib.request
from dataclasses import dataclass
@dataclass(frozen=True, slots=True)
class Seg: source_id: str
def read_segs(d): return d.get('segs') or ()
edges = [(str(i), str(i+1), 0, {'segs': (Seg(f's-{i//3}'),)}) for i in range(2700)]
for _ in range(3000):
    _ = [(u,v,k,d) for u,v,k,d in edges if any(s.source_id == 'x' for s in read_segs(d))]
print('PASS')
"
}
```

典型崩溃输出：

```text
--- Run 3 ---
Windows fatal exception: access violation

Current thread 0x0000b35c (most recent call first):
  File "<string>", line 9 in <genexpr>
  File "<string>", line 9 in <module>
```

> 仓库中另有分层压测脚本 [scripts/isolate_native_crash.py](../scripts/isolate_native_crash.py) 与 [scripts/minimal_networkx_repro.py](../scripts/minimal_networkx_repro.py)，可用于在不同层做更长时间的压力对照。

---

## 5. 根因分析

既然**零第三方 C 扩展、单线程纯 Python 代码**就能稳定复现 `access violation`、`_PyEval_EvalFrameDefault: Executing a cache.` 和 `ValueError: generator already executing`，根因只可能落在以下两个层面之一：

### 可能原因 A：CPython 3.13.15（Windows 构建）解释器自身缺陷
- CPython 3.13 的自适应字节码特化器（PEP 659 inline cache）与高频嵌套生成器表达式（列表推导式内嵌 `any(<genexpr>)`）交互时，若存在字节码缓存/引用计数或帧复用缺陷，会导致 `_PyEval_EvalFrameDefault: Executing a cache.`、`generator already executing` 以及堆对象错位。
- 为什么“导入更多标准库”更容易复现？因为加载大量模块后堆更满、内存布局更复杂，高频分配临时生成器对象时触发 GC 与内存页复用的概率大幅上升。

### 可能原因 B：本机硬件/内存稳定性问题（不可忽视）
- 在 Windows 台式机/笔记本上，**内存条不稳定（如 XMP 超频）、CPU 电压/微码不稳定（典型如 Intel 13/14 代 Raptor Lake 缩缸或欠压）**在单线程高密度指针追踪（Python 解释器循环 + GC 遍历正是典型的指针密集型负载）下，会表现为**完全一致的症状**：随机 `access violation`、偶发 `AttributeError`（指针位翻转）、`MemoryError` 和 `Executing a cache`。

### 如何 1 分钟区分原因 A 与原因 B？

直接拿第 4 节的最小复现脚本做两个对照实验：
1. **换 Python 版本（同机对照）**：在本机安装另一个 Python 版本（如 Python 3.12 或其他 3.13 补丁版本）连跑 20 轮上述脚本。
   - 若仅 `3.13.15` 崩、其他版本 20/20 全通过 → **基本确认是 CPython 3.13.15 构建问题**。
   - 若多个 Python 版本在本机都随机崩 → **高度怀疑硬件/内存/CPU 稳定性**，建议跑 Windows 内存诊断 / MemTest86 / Prime95 或检查 BIOS 微码与 XMP 设置。
2. **换机器（同版本对照）**：在另一台电脑上用相同 `Python 3.13.15` 跑 20 轮上述脚本。
   - 若另一台电脑也复现 → **确认为 CPython 3.13.15 自身 bug**（可直接向 CPython 上游提 issue）。
   - 若另一台电脑完全不复现 → **确认为当前机器硬件/系统环境问题**。

---

## 6. 项目中的缓解与工程建议

1. **消除无谓的 $O(N^2)$ 高频对象分配（已落地）**
   - 原本 [validation.py](../src/airport_surface/validation.py)（原 `graph.py`）中的 `validate_source_intervals()` 对每条来源边（1,046 条）都全表扫描一遍图边（2,739 条），产生约 286 万次带嵌套生成器的迭代，极易引爆该问题。
   - 改为单遍扫描 $O(|E| + |S|)$ 后，迭代降至 2,739 次，`scripts/build_airport_graph.py` 已稳定跑通且速度提升近千倍。
2. **大批量匹配时的防御措施**
   - 尽量避免在热循环中高频嵌套 `any(... for ...)` 生成器表达式（必要时展开为普通 `for` 循环减少帧对象分配）。
   - 批处理入口（`uv run --extra stand-editing python -m src`）已按每 100 条航班刷新 JSONL；若单次全量跑出现进程崩溃，建议按 `[batch].limit` 分批或先完成第 5 节的版本/硬件排查以根治。
   - **不建议在生产代码中全局 `gc.disable()`**：实测关闭 GC 只能降低崩溃频率，无法根除（仍会出现 `generator already executing`），且长时间运行会导致循环引用内存持续增长。
