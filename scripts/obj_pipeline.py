"""obj_pipeline.py — 全流程 OBJ 输出(绕开 FBX)
[1] 加载 OSGB(分层回退) → [2] 合并+缝合 → [3] 减面
→ [4] 转轴(Y-up) → [5] UV 展开(xatlas) → [6] 输出 OBJ
用法: python obj_pipeline.py <瓦片目录> <输出目录> [--lod L22] [--faces 10000] [--uv] [--scale 100]
"""
import sys, os, shutil, subprocess, tempfile
import numpy as np


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import osgb_merge_export as ome
    import pymeshlab
    from pymeshlab.pmeshlab import PureValue

    import argparse
    ap = argparse.ArgumentParser(description='全流程 OBJ 输出')
    ap.add_argument('input', help='OSGB 工程目录 或 瓦片目录')
    ap.add_argument('output', help='输出目录')
    ap.add_argument('--lod', default='L22')
    ap.add_argument('--faces', type=int, default=10000)
    ap.add_argument('--uv', action='store_true', help='自动分 UV')
    ap.add_argument('--scale', type=float, default=1.0, help='顶点放大倍数(默认1)')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    os.environ['OSGROOT'] = r'E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph'
    osgconv = ome.find_osg(); env = ome.osgb_env(osgconv)
    engine_dir = os.path.join(os.path.dirname(os.path.abspath(ome.__file__)), '..', 'engine')
    osgb_full = os.path.join(engine_dir, 'osgb_full.exe')

    work = tempfile.mkdtemp(prefix='objpipe_')
    try:
        # [1] 加载
        print("[1/6] 加载 OSGB (分层回退)...")
        raw = os.path.join(work, 'raw.obj')
        tiles = ome.find_root_tiles(args.input)
        loaded_v, loaded_f = ome.osgb_full_load(osgb_full, osgconv, tiles, raw,
                                                0 if args.lod == 'root' else int(args.lod.replace('L', '')), env)
        print(f"  加载 {loaded_v:,}v / {loaded_f:,}f")

        # [2] 合并+缝合
        print("[2/6] 网格合并 + 边界缝合...")
        merged = os.path.join(work, 'merged.obj')
        ome.merge_mesh(raw, merged, 0.022, 0.2, args.verbose)

        # [3] 减面
        print(f"[3/6] 减面 (目标 {args.faces})...")
        ms = pymeshlab.MeshSet(); ms.load_new_mesh(merged)
        before_f = ms.current_mesh().face_number()
        if args.faces > 0 and args.faces < before_f:
            ms.meshing_decimation_quadric_edge_collapse(
                targetfacenum=args.faces, preserveboundary=False, preservenormal=True,
                optimalplacement=True, planarquadric=True, qualitythr=0.3)
        m = ms.current_mesh()
        simp = os.path.join(work, 'simp.obj')
        V = m.vertex_matrix(); F = m.face_matrix()
        with open(simp, 'w') as f:
            for v in V: f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for tri in F: f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
        print(f"  减面: {before_f} → {len(F)} 面, {len(V)} 顶点")

        # [4] 转轴 (Z-up → Y-up)
        print("[4/6] 调整轴向 (Y-up)...")
        v2, f2 = [], []
        for line in open(simp):
            p = line.split()
            if p and p[0] == 'v':
                x, y, z = float(p[1]), float(p[2]), float(p[3])
                v2.append([x, z, -y])
            elif p and p[0] == 'f':
                f2.append([int(p[1])-1, int(p[2])-1, int(p[3])-1])
        v2 = np.array(v2); f2 = np.array(f2)
        axis_obj = os.path.join(work, 'axis.obj')
        with open(axis_obj, 'w') as fp:
            for xyz in v2: fp.write(f"v {xyz[0]:.6f} {xyz[1]:.6f} {xyz[2]:.6f}\n")
            for tri in f2: fp.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")

        # [5] UV 展开(可选)
        export_obj = axis_obj
        if args.uv:
            print("[5/6] 自动分 UV (xatlas)...")
            import uv_unwrap
            uv_obj = os.path.join(work, 'unwrapped.obj')
            nv, nuv, nc = uv_unwrap.unwrap(axis_obj, uv_obj, resolution=2048, padding=2,
                                           verbose=args.verbose)
            print(f"  UV: 几何 {nv}v, UV {nuv}v, {nc} 岛")
            export_obj = uv_obj

        # [6] 应用 scale + 输出 OBJ
        print("[6/6] 输出 OBJ...")
        if args.scale != 1.0:
            scaled = os.path.join(work, 'scaled.obj')
            with open(export_obj) as fi, open(scaled, 'w') as fo:
                for line in fi:
                    p = line.split()
                    if p and p[0] == 'v':
                        x = float(p[1]) * args.scale
                        y = float(p[2]) * args.scale
                        z = float(p[3]) * args.scale
                        fo.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
                    else:
                        fo.write(line)
            export_obj = scaled
            print(f"  缩放: 顶点 ×{args.scale}")

        base = os.path.basename(args.input.rstrip('\\/')).replace('+', '')
        out_name = base + '.obj'
        out_path = os.path.join(args.output, out_name)
        shutil.copy2(export_obj, out_path)
        print(f"  输出: {out_path}")
        print(f"完成! 几何顶点 {len(v2)}, 面 {len(f2)}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
