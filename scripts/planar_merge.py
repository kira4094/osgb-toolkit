#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
planar_merge.py — 平面区域合并(模拟 OPEditor CGAL Planar_segmentation)
============================================================
原理: 
  1. 计算每三角形法线 + 平面方程
  2. 区域生长: 相邻且共面(法线夹角小 + 平面距离近)的三角形聚成 patch
  3. 每个 patch 消除内部顶点(非边界顶点), 由边界顶点替代
  4. 重新三角化(简单 fan 三角化)

用法:
  python planar_merge.py <in.obj> <out.obj> [angle_thr_deg] [dist_thr]
"""
import sys
import numpy as np


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


def planar_merge(V, F, angle_thr_deg=15.0, dist_thr=0.5):
    """
    平面区域合并: 共面三角形聚成 patch, 消除 patch 内部顶点
    返回新的 (V, F)
    """
    nf = len(F)
    va, vb, vc = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    # 三角形法线 + 平面偏移 (n·x = d)
    n = np.cross(vb - va, vc - va)
    norm = np.linalg.norm(n, axis=1)
    norm[norm < 1e-12] = 1e-12
    n = n / norm[:, None]
    d = np.sum(n * va, axis=1)  # 平面到原点距离

    # 面邻接: 共享边的面
    edge_faces = {}
    for fi in range(nf):
        f = F[fi]
        for e in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])]:
            key = tuple(sorted(e))
            edge_faces.setdefault(key, []).append(fi)

    # 区域生长 (BFS): 相邻且共面
    cos_thr = np.cos(np.radians(angle_thr_deg))
    patch_id = np.full(nf, -1, dtype=np.int64)
    n_patches = 0
    for start in range(nf):
        if patch_id[start] >= 0:
            continue
        # BFS
        stack = [start]
        patch_id[start] = n_patches
        while stack:
            fi = stack.pop()
            f = F[fi]
            for e in [(f[0], f[1]), (f[1], f[2]), (f[2], f[0])]:
                key = tuple(sorted(e))
                for nb in edge_faces.get(key, []):
                    if patch_id[nb] >= 0:
                        continue
                    # 共面判断: 法线夹角 + 平面距离
                    cos_angle = np.dot(n[fi], n[nb])
                    dist = abs(d[fi] - d[nb])
                    if cos_angle > cos_thr and dist < dist_thr:
                        patch_id[nb] = n_patches
                        stack.append(nb)
        n_patches += 1

    # 统计 patch 大小
    sizes = np.bincount(patch_id, minlength=n_patches)
    big_patches = np.where(sizes >= 4)[0]
    print(f"共 {n_patches} 个 patch, 其中 >=4 面的 {len(big_patches)} 个")

    # 对每个大 patch, 找出内部顶点(所有邻面都在同 patch 的顶点)
    v_remove = np.zeros(len(V), dtype=bool)
    for pi in big_patches:
        faces_in = np.where(patch_id == pi)[0]
        verts_in = set()
        for fi in faces_in:
            verts_in.update(F[fi].tolist())
        # 顶点邻面
        for v in verts_in:
            nbr_faces = np.where((F == v).any(axis=1))[0]
            # 内部顶点: 所有邻面都在同 patch
            if len(nbr_faces) > 0 and all(patch_id[nb] == pi for nb in nbr_faces):
                v_remove[v] = True

    # 重建网格: 删除被移除的顶点, 重映射面索引
    keep = ~v_remove
    v_new_idx = np.full(len(V), -1, dtype=np.int64)
    v_new_idx[keep] = np.arange(keep.sum())
    V_new = V[keep]

    F_new_list = []
    for tri in F:
        ni = v_new_idx[tri]
        if all(ni >= 0) and len(set(ni.tolist())) == 3:
            F_new_list.append(ni.tolist())
    F_new = np.array(F_new_list, dtype=np.int64)

    print(f"移除顶点: {v_remove.sum()}, 面: {nf} → {len(F_new)}")
    return V_new, F_new


def main():
    if len(sys.argv) < 3:
        print("Usage: python planar_merge.py <in.obj> <out.obj> [angle_deg] [dist]")
        return
    in_obj = sys.argv[1]
    out_obj = sys.argv[2]
    angle = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
    dist = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5

    V, F = load_obj(in_obj)
    print(f"输入: {len(V)}v / {len(F)}f")
    V2, F2 = planar_merge(V, F, angle, dist)
    save_obj(out_obj, V2, F2)
    print(f"输出: {len(V2)}v / {len(F2)}f")


if __name__ == '__main__':
    main()
