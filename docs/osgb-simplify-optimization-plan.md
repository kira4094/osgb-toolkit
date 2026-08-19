# OSGB 减面优化方案(对齐 OPEditor 平面省面)

> 日期: 2026-08-19 | 依据: OPEditor.exe 二进制逆向 + 豆包布线对比 + 量化测量

---

## 一、问题现状(已量化)

| 指标 | OPEditor | 我们 | 差距 |
|---|---|---|---|
| 独立顶点 | 4,743 | 5,334 | +12% |
| 三角形面积跨度(最大/中位) | **811x** | **98x** | OPEditor 平面区省面 |
| 平面区大三角形占比 | 14.2% | 12.4% | 接近 |
| 非流形边 | 0(CGAL 半边天然流形) | **329** | 阻挡折叠 |
| 边界边(减面后) | 100%(每面独立导出) | 687 | — |

**根因**: 我们的 planarquadric(平面检测减面)被 **329 条非流形边阻挡**——折叠需要边两侧面法线一致,非流形边处无法折叠,导致平面区三角形压不下去(98x vs 811x)。

---

## 二、方案总览(三档,按投入递增)

| 方案 | 改动 | 预期效果 | 工作量 | 风险 |
|---|---|---|---|---|
| **A. 参数优化** | 消除非流形边 + planar 强度调优 | 平面区改善 30-50% | 1天 | 低(可回退) |
| **B. 流程重构** | 多阶段减面 + remesh 引导 + 二次缝合 | 接近 OPEditor | 2-3天 | 中 |
| **C. CGAL 原生** | C++ 编译 CGAL 边折叠(复刻 OPEditor) | 完全对齐 811x | 5-7天 | 高(需编译) |

---

## 三、方案 A:参数优化(推荐先做,验证可行性)

### A1. 消除非流形边(减面前的关键前提)
```python
# 只删"短的非流形边"(接缝处), 不动长边(模型特征)
# pymeshlab 没有"删短非流形边"的现成 filter, 用两步:
ms.meshing_repair_non_manifold_edges()   # 全部修复(风险:可能删长边撕裂)
# 或: 自写过滤 —— 只处理边长 < 阈值 的非流形边
```

**风险控制**: 之前 `repair_non_manifold_edges` 撕裂模型是因为**把长边也删了**。正确做法:
- 先算每条非流形边的长度
- 只对**短边**(< 平均边长×0.3,即接缝处)做删除/重连
- 长非流形边(模型真实特征)保留

### A2. 提高 planarquadric 强度(两阶段减面)
```python
# 阶段1: 先减到目标×1.5 (粗减, 平面区开始聚合)
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=15000, planarquadric=True, ...)
# 阶段2: 再减到目标 (细减, 平面区进一步折叠)
ms.meshing_decimation_quadric_edge_collapse(targetfacenum=10000, planarquadric=True, ...)
```

**原理**: 单次减面 10000 时,非流形边阻挡的平面区来不及折叠;分两阶段让平面区先粗聚合、再细折叠。

### A3. 减面后二次缝合(已有,保留)
```python
# 减面后 stitch_borders 再缝一轮, 修复边折叠拉开的缝
_V2, _F2 = sb_stitch(V, F, stitch_thr, max_iter=2)
```

### A4. 验收标准
```
独立顶点: 5,334 → 目标 < 5,000 (逼近 4,743)
面积跨度: 98x  → 目标 > 300x (平面省面)
视觉: 红框地面大三角形明显变少
```

---

## 四、方案 B:流程重构(若 A 不够)

对齐 OPEditor 完整顺序:

```
加载(osgb_full)
  → ① 消除非流形边(短边, A1)
  → ② OverlapErosion(自交面删除)     [OPEditor: checkBoxStitchBeforeErosion]
  → ③ merge_close_vertices(0.022)
  → ④ StitchBorders(0.8, 多轮)       [OPEditor: SnappingBorders 4级容差]
  → ⑤ 两阶段减面(planar, A2)
  → ⑥ 二次缝合
  → ⑦ RemoveFloatingParts(<25面)     [OPEditor: RemoveFloatingPartsDialog]
  → ⑧ UV 展开 → 导出
```

**新增步骤**: ② 和 ⑦ 之前已经实现(GUI 有开关),只需调整顺序到 OPEditor 相同。

---

## 五、方案 C:CGAL 原生(终极方案,若 A+B 达不到)

**复刻 OPEditor 核心**:
```cpp
// CGAL 半边网格 + 边折叠(OPEditor 同款)
#include <CGAL/Surface_mesh.h>
#include <CGAL/Polygon_mesh_processing/edge_collapse.h>
#include <CGAL/Surface_mesh_simplification/edge_collapse.h>
```
- 数据结构: `CGAL::Surface_mesh<Point_3<Epick>>`(半边,天然流形)
- 减面: `Surface_mesh_simplification::edge_collapse`(Garland-Heckbert)
- 融合: `Polygon_mesh_processing::corefine`(拓扑级切割对齐, OPEditor 的 Corefining Boundary)
- 权重: 体积/边界/形状三权重(OPEditor 的 spinBoxVolumeWeight/BoundaryWeight/ShapeWeight)

**需要**: VS2022 编译 CGAL(带依赖 boost/gmp/mpfr),工作量最大但**完全对齐**。

---

## 六、建议执行路径

```
第1步(今天): 方案 A —— 消除短非流形边 + 两阶段减面
             → 用 Tile_+034_+036 验证, 看顶点数和面积跨度
第2步(明天): 若 A 达标(<5000v, >300x) → 收工
             若 A 不达标 → 方案 B 流程重构
第3步(可选): B 仍不够 → 方案 C CGAL(需用户确认投入)
```

**关键风险提醒**:
1. 消除非流形边可能删面(之前撕裂教训)→ 必须只删短边
2. 两阶段减面可能略微过减 → 用目标×1.5 过渡
3. 任何改动先 GUI 验证(用户基准),确认无撕裂再固化

---

## 七、附:OPEditor 减面参数逆向(供参考)

```
EdgeCollapsingWidget:
  LindstromTurk | GarlandHeckbert  (两种算法)
  spinBoxVolumeWeight   (体积权重)
  spinBoxBoundaryWeight (边界权重)
  spinBoxShapeWeight    (形状权重)
  日志: "Edge collapse reconstruct, target faces: X, total faces: Y"

SnappingBordersWidget:
  spinBoxTolerance0~3   (4级容差)
  checkBoxSimplify      (简化后缝合)

OverlapErosionWidget:
  checkBoxStitchBeforeErosion (侵蚀前先缝合)
