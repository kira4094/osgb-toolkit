#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stitch_borders.py — 边界缝合(模拟 OPEditor/CGAL stitch_borders)
============================================================
只融合"网格边界上接近的点", 不动内部顶点。
消除小瓦片接缝: 边界上的点自动 merge 成 1 个点。

原理:
  1. 找出所有边界边(只被 1 个面共享的边)
  2. 边界边的端点 = 候选缝合顶点
  3. 对距离 < threshold 的边界顶点对, 合并成 1 个
  4. 只合并边界顶点, 内部顶点不动

用法:
  python stitch_borders.py <in.obj> <out.obj> [threshold] [max_iterations]
"""
import sys
import numpy as np
from collections import defaultdict


def load_obj(path):
    V = []
    F = []
    for line in open(path, encoding='utf-8', errors='replace'):
        if line.startswith('v '):
            p = line.split()
            V.append([float(p[1]), float(p[2]), float(p[3])])
        elif line.startswith('f '):
            p = line.split()[1:]
            idx = [int(x.split('/')[0]) - 1 for x in p]
            if len(idx) >= 3:
                F.append(idx[:3])
    return np.array(V, dtype=np.float64), np.array(F, dtype=np.int64)


def save_obj(path, V, F):
    with open(path, 'w') as f:
        for v in V:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for tri in F:
            f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")


def find_boundary_vertices(V, F):
    """找出边界边两端的顶点(边界顶点集合)"""
    edge_count = defaultdict(list)
    for fi, tri in enumerate(F):
        for e in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])]:
            key = tuple(sorted(e))
            edge_count[key].append(fi)
    boundary_verts = set()
    for e, faces in edge_count.items():
        if len(faces) == 1:  # 边界边
            boundary_verts.add(e[0])
            boundary_verts.add(e[1])
    return boundary_verts


def stitch_borders(V, F, threshold=0.05, max_iter=3):
    """边界缝合: 只融合边界上接近的点"""
    nv = len(V)
    for iteration in range(max_iter):
        bverts = find_boundary_vertices(V, F)
        if not bverts:
            print(f"  迭代{iteration}: 无边界顶点")
            break
        bv_list = sorted(bverts)
        bv_set = set(bv_list)

        # 空间哈希: 按 threshold 分桶, 找接近的边界点对
        bv_pos = {v: V[v] for v in bv_list}
        # 网格分桶
        cells = defaultdict(list)
        cell_size = threshold
        for v in bv_list:
            p = bv_pos[v]
            key = (int(p[0] // cell_size), int(p[1] // cell_size), int(p[2] // cell_size))
            cells[key].append(v)

        # 合并映射: 接近的边界顶点 → 代表顶点
        merge_map = {}  # v -> representative
        merged = 0
        for v in bv_list:
            if v in merge_map:
                continue
            p = bv_pos[v]
            cx, cy, cz = int(p[0] // cell_size), int(p[1] // cell_size), int(p[2] // cell_size)
            # 检查周围 27 个格子
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for nb in cells.get((cx+dx, cy+dy, cz+dz), []):
                            if nb == v or nb in merge_map:
                                continue
                            d = np.linalg.norm(bv_pos[v] - bv_pos[nb])
                            if d < threshold:
                                # v 代表点, nb 合并到 v
                                merge_map[nb] = v
                                merged += 1

        if merged == 0:
            print(f"  迭代{iteration}: 无可缝合点")
            break

        # 应用合并: 面索引更新
        new_F = []
        for tri in F:
            nt = [merge_map.get(x, x) for x in tri]
            # 跳过退化面(两个顶点合并后重合)
            if len(set(nt)) == 3:
                new_F.append(nt)
        F = np.array(new_F, dtype=np.int64)

        # 移除被合并的顶点
        merged_verts = set(merge_map.keys())
        keep = np.array([i not in merged_verts for i in range(nv)], dtype=bool)
        v_new_idx = np.full(nv, -1, dtype=np.int64)
        v_new_idx[keep] = np.arange(keep.sum())
        V = V[keep]
        F = np.array([[v_new_idx[x] for x in tri] for tri in F], dtype=np.int64)
        nv = len(V)
        print(f"  迭代{iteration}: 缝合 {merged} 对, V {nv} → 面 {len(F)}")

    return V, F


def main():
    if len(sys.argv) < 3:
        print("Usage: python stitch_borders.py <in.obj> <out.obj> [threshold] [max_iter]")
        return
    in_obj = sys.argv[1]
    out_obj = sys.argv[2]
    threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.05
    max_iter = int(sys.argv[4]) if len(sys.argv) > 4 else 3

    V, F = load_obj(in_obj)
    print(f"输入: {len(V)}v / {len(F)}f")
    bv = find_boundary_vertices(V, F)
    print(f"边界顶点: {len(bv)}")
    V2, F2 = stitch_borders(V, F, threshold, max_iter)
    save_obj(out_obj, V2, F2)
    print(f"输出: {len(V2)}v / {len(F2)}f")


if __name__ == '__main__':
    main()
