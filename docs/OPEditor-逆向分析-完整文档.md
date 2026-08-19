# OPEditor 重构流程逆向分析(完整文档)

> 日期: 2026-08-19 | 来源: OPEditor.exe 二进制字符串/符号提取(UTF-8 + 符号名)
> 目的: 作为 osgb-toolkit 对齐 OPEditor 的权威参考, 防止疏漏

---

## 一、完整重构流程(ReconstructDialog, 10 步权威顺序)

从 exe 的 widget 类名出现顺序 + 流程日志拼接确认:

```
ope::ReconstructDialog 重构流程:
1.  读取网格       (ReadingWidget)
2.  网格合并       (MeshMergingWidget: buttonMergeMeshMergingWidget)
3.  网格/重网格化  (RemeshingWidget: spinBoxTargetEdgeLength)
4.  网格/边界合并  (SnappingBordersWidget: 容忍度1-4 + 允许简化)
5.  网格/简化      (EdgeCollapsingWidget: LT|GH + 3权重 + 4策略 + 目标面数)
6.  网格/组件过滤  (ComponentFilterWidget: 面积阈值)
7.  网格/点集采样  (SamplingWidget)
8.  网格/补洞      (HoleFillingWidget: 最大顶点数/密度/平滑度/最大长度)
9.  网格/重叠腐蚀  (OverlapErosionWidget: 重叠阈值 + 腐蚀前缝合)
10. 网格/边界桥接  (BridgeBordersWidget: 桥接阈值)
```

**核心日志(确认流程)**:
- `Exec edge collapse`(简化)
- `Corefining Boundary`(边界共形化)
- `Clipping blocks`(分块)
- `Converting model`(转换模型)
- `Generating textures`(生成纹理)
- `Snapping` ×13(缝合)

---

## 二、各 Widget 完整参数(逆向提取)

### 2.1 EdgeCollapsingWidget(简化 — 核心)
```
方法:   LindstromTurk | GarlandHeckbert
体积权重: spinBoxVolumeWeight
边界权重: spinBoxBoundaryWeight
形状权重: spinBoxShapeWeight
策略:   平面 | 概率平面 | 三角形 | 概率三角形
目标面数: spinBoxFaceCountThreshold
日志: "Edge collapse reconstruct, target faces: X, total faces: Y"
      "Unknown edge collapse method" / "  edges collapsed"
```

### 2.2 SnappingBordersWidget(边界缝合)
```
容忍度1: spinBoxTolerance0
容忍度2: spinBoxTolerance1
容忍度3: spinBoxTolerance2
容忍度4: spinBoxTolerance3
允许简化: checkBoxSimplify
```

### 2.3 MeshMergingWidget(网格合并)
```
按钮: buttonMergeMeshMergingWidget
日志: "正在合并" / "网格合并必须在读取流程之后" / "无法合并网格"
```

### 2.4 RemeshingWidget(重网格化)
```
目标边长: spinBoxTargetEdgeLength
日志: "不能计算平均边长, 输入为空?"
```

### 2.5 HoleFillingWidget(补洞)
```
最大顶点数: spinBoxMaxVertices(不限制)
密度系数: spinBoxDensity
平滑度: spinBoxFairing
最大长度: spinBoxMaxLength
日志: "Hole filling: start" / "Hole filling: duplicate" / "补洞失败" / "Hole filling: done"
算法: CGAL advancing front(triangulate_hole)
```

### 2.6 ComponentFilterWidget(组件过滤)
```
过滤规则: 面积降序 | 面积升序 | 面积小于
保留个数: spinBoxTargetNumComponents
面积阈值: spinBoxAreaThreshold
```

### 2.7 OverlapErosionWidget(重叠腐蚀)
```
重叠阈值: (未命名 spinBox)
腐蚀前缝合边界: checkBoxStitchBeforeErosion
日志: "Overlap erosion: start" / "Overlap erosion: done"
```

### 2.8 BridgeBordersWidget(边界桥接)
```
桥接阈值: epsilonSpinBox
```

---

## 三、导出对话框(ExportModelDialog — 默认 vs 大疆)

```
导出格式: OBJ | FBX
网格合并: checkBoxMergeMesh(复选框)
网格类型: comboBoxMeshType = 默认 | 大疆
导出路径: lineEditExportPath

大疆类型参数(导出 FBX 时):
  MayaZUp
  FBX-AxisSystem
  FBX-SystemUnit-ScaleFactor
  FBX-AssetUnitMeter
  SyncWriting=1.fbx
```

**说明**: "默认|大疆"是**导出格式选项**(大疆 = DJI 的 FBX 轴/单位规范),不是重构流程的合并算法。

---

## 四、CGAL 使用(符号证据)

```
CGAL 引用: 6430 次
关键符号:
  CGAL::Surface_mesh<CGAL::Point_3<Epick>>  (半边网格, 天然流形)
  CGAL::Polygon_mesh_processing::stitch_borders (缝合)
  CGAL::Polygon_mesh_processing::triangulate_hole (补洞, advancing front)
  CGAL::Surface_mesh_simplification (简化)
  CGAL::Property_map / Point_set_3 (点集)
  CGAL::Mesh_triangulation_3 (重建)
  TBB 并行 (tbb::parallel, flow graph)

网格处理类(ope::edit::Mesh):
  StitchBorders@Mesh@edit@ope (边界缝合)
  ConvertFromOSGParallel@Model@edit@ope (并行转换)
```

**关键**: OPEditor 用 `CGAL::Surface_mesh`(半边结构, **天然保证流形**)——这是它减面不崩、顶点少的根本原因。

---

## 五、四策略 = OPEditor 内部平面检测变体

```
平面         → 标准 GH 平面 quadric
概率平面     → 平面 + 概率采样
三角形       → 标准 GH 三角 quadric
概率三角形   → 三角 + 概率采样
```

exe 中无 `probabilistic` 符号 → 四策略是 OPEditor 对 GH quadric 计算器的变体控制, 非独立 CGAL 类。

---

## 六、与我们流程的差距(关键)

| 步骤 | OPEditor | 我们 | 差距 |
|---|---|---|---|
| 网格结构 | CGAL Surface_mesh(半边,流形) | pymeshlab/OBJ 中转 | 非流形问题 |
| 重网格化 | ✅ 简化前(目标边长) | ❌ 无 | 布线不均 |
| 边界缝合 | ✅ 4级容忍度 | ✅ stitch_borders(0.2) | 部分 |
| 简化 | ✅ GH + 3权重(体积/边界/形状) | GH 平面(单权重) | 权重缺失 |
| 补洞 | ✅ 简化后(advancing front) | ❌ 无 | **破洞** |
| 边界桥接 | ✅ 桥接阈值 | ❌ 无 | 接缝 |
| 顶点融合 | ✅ 半边天然共享 | ✅ merge 0.022 | 接近 |

---

## 七、对齐计划(下一步)

**重点: 保留边(特征)前提下重网格化 + GH 默认流程**

1. 简化前重网格化(CGAL remesh, 目标边长) — 布线均匀
2. GH GarlandHeckbert 默认(平面策略) — 平面省面
3. 补洞(triangulate_hole, 已实现) — 消除破洞
4. 简化后缝合(stitch_borders) — 消除接缝
5. 三权重探索(体积/边界/形状) — 逼近 OPEditor 顶点数

**测试基准**: Tile_+034_+036, L22, 目标 10000 面
**对齐目标**: OPEditor 输出(output/OPEditor/Tile_+034_+036.fbx)
