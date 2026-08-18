"""uv_unwrap.py - 自动分 UV (纹理映射第一步)
基于 xatlas: 对简化后的网格自动展开 UV + 岛打包
输入: 简化后 OBJ(纯几何, 无 UV)
输出: 带 UV 的 OBJ(v 几何顶点 + vt UV 顶点 + f 分离引用)
用法: python uv_unwrap.py <in.obj> <out.obj> [--resolution 2048] [--padding 2]
"""
import sys, os
import numpy as np
import xatlas


def load_obj(path):
    """读取 OBJ: 返回顶点数组 + 面数组(0-based 索引)"""
    v, f = [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            v.append([float(parts[1]), float(parts[2]), float(parts[3])])
        elif parts[0] == "f":
            idx = [int(p.split("/")[0]) - 1 for p in parts[1:] if p]
            if len(idx) >= 3:
                f.append(idx[:3])
    return np.array(v, dtype=np.float32), np.array(f, dtype=np.uint32)


def unwrap(in_obj, out_obj, resolution=2048, padding=4, max_iterations=4,
           texels_per_unit=None, verbose=False, brute_force=False):
    """自动分 UV + 打包
    v = 几何顶点(保持融合), vt = UV 顶点(seam 分裂, 正常)
    f = vi/vti 分离引用: 几何融合 + UV 分裂并存
    """
    v, f = load_obj(in_obj)
    if len(v) == 0 or len(f) == 0:
        raise RuntimeError(f"OBJ 为空或无法解析: {in_obj}")

    if verbose:
        print(f"  输入: {len(v)} 顶点, {len(f)} 面")

    atlas = xatlas.Atlas()
    atlas.add_mesh(v, f)

    chart_opts = xatlas.ChartOptions()
    chart_opts.max_iterations = max_iterations

    pack_opts = xatlas.PackOptions()
    pack_opts.resolution = resolution
    pack_opts.padding = padding
    # bruteForce 打包: 质量最高(89%)但慢 50-80 倍; padding 启发式快 80 倍(84.5%)
    pack_opts.bruteForce = brute_force
    if texels_per_unit:
        pack_opts.texels_per_unit = texels_per_unit

    atlas.generate(chart_opts, pack_opts)

    # vm = 顶点索引数组(长度=UV顶点数, 值=原始几何顶点索引)
    # fm = UV面, uv = UV坐标
    vm, fm, uv = atlas.get_mesh(0)
    if verbose:
        print(f"  展开: 几何 {len(v)}v, UV {len(vm)}v, {len(fm)} 面, {atlas.atlas_count} 岛")
        print(f"  UV 范围: [{uv.min():.3f}, {uv.max():.3f}], 打包 {atlas.width}x{atlas.height}")
        print(f"  利用率: {atlas.utilization:.1%}")

    with open(out_obj, "w") as fp:
        fp.write(f"# UV-unwrapped by xatlas (geom {len(v)}v + uv {len(vm)}v, {len(fm)}f)\n")
        # v: 原始几何顶点(保持融合)
        for xyz in v:
            fp.write(f"v {float(xyz[0]):.6f} {float(xyz[1]):.6f} {float(xyz[2]):.6f}\n")
        # vt: UV 顶点(seam 分裂)
        for uvt in uv:
            fp.write(f"vt {float(uvt[0]):.6f} {float(uvt[1]):.6f}\n")
        # f: 位置索引=vm[tri], UV索引=tri
        for tri in fm:
            fp.write(f"f {int(vm[tri[0]])+1}/{int(tri[0])+1} {int(vm[tri[1]])+1}/{int(tri[1])+1} {int(vm[tri[2]])+1}/{int(tri[2])+1}\n")

    return len(v), len(vm), atlas.atlas_count


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='自动分 UV (xatlas)')
    ap.add_argument('in_obj')
    ap.add_argument('out_obj')
    ap.add_argument('--resolution', type=int, default=2048, help='纹理分辨率')
    ap.add_argument('--padding', type=int, default=4, help='岛间距像素')
    ap.add_argument('--brute-force', action='store_true', help='bruteForce 密集打包(慢但利用率最高)')
    ap.add_argument('--texels-per-unit', type=float, default=None, help='每单位texel')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    nv, nuv, nchart = unwrap(args.in_obj, args.out_obj,
                             resolution=args.resolution, padding=args.padding,
                             texels_per_unit=args.texels_per_unit, verbose=args.verbose,
                             brute_force=args.brute_force)
    print(f"完成! 几何 {nv} 顶点, UV {nuv} 顶点, {nchart} 岛 -> {args.out_obj}")
