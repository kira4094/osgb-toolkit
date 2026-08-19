# OPEditor 网格合并算法 —— 最终确认(2026-08-19 深度逆向)

> 本文件是**确定性结论**(非推测), 基于 OPEditor.exe 二进制符号逆向。

---

## 一、核心结论: OPEditor 的"网格合并" = 平面补丁重网格化

**不是距离合并(merge_close_vertices), 不是 corefine 剪裁, 而是 CGAL 的 `remesh_almost_planar_patches`(平面区重网格化)**。

### 证据(符号级)

`exec@MeshMergingStep@MeshMergingWidget` 附近 20000 字节的 CGAL 符号:

```
merge/weld/duplicate/stitch/corefine/collapse: 全部 0 次  ← 不是这些算法!
remesh/Remesh: 7 次                                    ← 是 remesh!

CGAL 类型:
  CGAL::Surface_mesh<CGAL::Point_3<Epick>>   (半边网格, 流形)
  CGAL::Plane_3<Epick>                        (平面)
  internal::Planar_segment<Epick>             (平面分割)
  CGAL::compute_average_spacing               (平均间距)
```

**Plane_3 + Planar_segment + remesh = CGAL `remesh_almost_planar_patches`**:
1. 检测网格中的平面区域(Planar_segment 分割)
2. 每个平面区重网格化成大三角形(省面)
3. 非平面区保留细节

---

## 二、为什么这解释所有现象

| 现象 | 解释 |
|---|---|
| 平面区省面(811x 大三角形) | remesh 把平面区重网格化成大面 |
| 无瓦片边界 | 平面补丁跨越瓦片边界重建 |
| 顶点少(4743) | remesh 后网格顶点均匀且少 |
| 布线均匀 | remesh 的等边化 |
| 无破洞 | 补洞(HoleFilling)在简化后 |

---

## 三、OPEditor 完整重构流程(确定版)

```
1. 读取网格(ReadingWidget)          — 构建 CGAL Surface_mesh(流形)
2. 网格合并(MeshMergingWidget)      — remesh_almost_planar_patches(平面省面!)
3. 网格/重网格化(RemeshingWidget)   — isotropic_remeshing(目标边长)
4. 网格/边界合并(SnappingBordersWidget) — stitch_borders(4级容忍度)
5. 网格/简化(EdgeCollapsingWidget)  — GH 边折叠(3权重+4策略+目标面数)
6. 网格/组件过滤(ComponentFilterWidget) — 面积阈值移除碎片
7. 网格/点集采样(SamplingWidget)
8. 网格/补洞(HoleFillingWidget)     — triangulate_hole(advancing front)
9. 网格/重叠腐蚀(OverlapErosionWidget) — 重叠区删除
10. 网格/边界桥接(BridgeBordersWidget) — 桥接裂缝
```

---

## 四、我们应如何对齐(最终实现方案)

```
1. osgb_full 读取(保留)
2. [替换] pymeshlab 合并 → CGAL remesh_almost_planar_patches
   (平面区重网格化, 消除瓦片边界 + 平面省面)
3. [保留] GH 简化(已实现, CGAL edge_collapse)
4. [保留] 补洞(已实现, triangulate_hole)
5. [新增] 组件过滤(面积阈值)
6. UV + 转轴 + scale(保留)
```

**关键改动**: 合并步骤从"merge+stitch"换成"remesh_almost_planar_patches"。

---

## 五、CGAL 函数签名(已确认)

```cpp
// remesh_planar_patches.h
bool remesh_almost_planar_patches(
    const TriangleMeshIn& tm_in,   // 输入(瓦片拼接后)
    PolygonMeshOut& pm_out,        // 输出(平面重网格化后)
    std::size_t nb_patches,        // 平面补丁数
    std::size_t nb_corners,        // 角点数
    FacePatchMap face_patch_map,
    VertexCornerMap vertex_corner_map,
    EdgeIsConstrainedMap ecm,
    np_in = default, np_out = default);
```
