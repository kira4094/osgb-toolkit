"""full_pipeline.py — 全流程: OSGB → 合并 → 简化 → UV → 烘焙 → OBJ+纹理
输出: <瓦片名>.obj(带UV, Y-up, scale) + <瓦片名>.mtl + texture.png
管线:
  [1] osgb_full 分层回退加载 → 合并 OBJ + 提取纹理(A 颜色源)
  [2] 从 A 简化出 B(同坐标 Z-up)
  [3] xatlas 自动分 UV
  [4] 像素级烘焙(±Z ray cast, A 纹理采样 → B 图集)
  [5] 转轴 Y-up + scale
  [6] 输出 OBJ(带 UV)+ MTL + texture.png
用法: python full_pipeline.py <瓦片目录> <输出目录> [--lod L22] [--faces 10000] [--scale 100] [--resolution 2048]
"""
import sys, os, shutil, subprocess, tempfile
import numpy as np
from PIL import Image


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import osgb_merge_export as ome
    import pymeshlab
    from pymeshlab.pmeshlab import PureValue
    import uv_unwrap
    import texture_bake as tb

    import argparse
    ap = argparse.ArgumentParser(description='全流程: OSGB → OBJ + 纹理')
    ap.add_argument('input', help='OSGB 工程目录 或 瓦片目录')
    ap.add_argument('output', help='输出目录')
    ap.add_argument('--lod', default='L22')
    ap.add_argument('--faces', type=int, default=10000)
    ap.add_argument('--scale', type=float, default=100.0)
    ap.add_argument('--resolution', type=int, default=2048, help='烘焙图集分辨率')
    ap.add_argument('--dilate', type=int, default=4, help='UV边缘扩散像素(消除黑边)')
    ap.add_argument('--sample-step', type=int, default=2, help='烘焙采样跳步(2=每2px采1个, 快4倍)')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    os.makedirs(args.output, exist_ok=True)
    os.environ['OSGROOT'] = r'E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph'
    osgconv = ome.find_osg(); env = ome.osgb_env(osgconv)
    engine_dir = os.path.join(os.path.dirname(os.path.abspath(ome.__file__)), '..', 'engine')
    osgb_full = os.path.join(engine_dir, 'osgb_full.exe')

    work = tempfile.mkdtemp(prefix='fullpipe_')
    try:
        # [1] 加载 A(合并 OBJ + 纹理)
        print("[1/6] 加载 OSGB + 提取纹理...")
        merged = os.path.join(work, 'merged.obj')
        tiles = ome.find_root_tiles(args.input)
        max_lod = 0 if args.lod == 'root' else int(args.lod.replace('L', ''))
        loaded_v, loaded_f = ome.osgb_full_load(osgb_full, osgconv, tiles, merged, max_lod, env)
        # 纹理已由 osgb_full 提取到 merged.obj 同目录
        tex_dir = os.path.dirname(merged)
        ntex = len([f for f in os.listdir(tex_dir) if f.startswith('texture_')])
        print(f"  A: {loaded_v:,}v {loaded_f:,}f, {ntex} 纹理")

        # [2] 从 A 简化出 B(同坐标 Z-up)
        print("[2/6] 简化...")
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(merged)
        ms.meshing_merge_close_vertices(threshold=PureValue(0.022))
        ms.meshing_remove_unreferenced_vertices()
        before_f = ms.current_mesh().face_number()
        if args.faces > 0 and args.faces < before_f:
            ms.meshing_decimation_quadric_edge_collapse(
                targetfacenum=args.faces, preserveboundary=False, preservenormal=True,
                optimalplacement=True, planarquadric=True, qualitythr=0.3)
        m = ms.current_mesh()
        B_geo = os.path.join(work, 'B.obj')
        V = m.vertex_matrix(); F = m.face_matrix()
        with open(B_geo, 'w') as fp:
            for vv in V: fp.write(f"v {vv[0]:.6f} {vv[1]:.6f} {vv[2]:.6f}\n")
            for tri in F: fp.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
        print(f"  B: {len(V):,}v {len(F):,}f (从 {before_f:,} 简化)")

        # [3] xatlas 自动分 UV
        print("[3/6] 自动分 UV...")
        B_uv = os.path.join(work, 'B_uv.obj')
        nv, nuv, nc = uv_unwrap.unwrap(B_geo, B_uv, resolution=2048, padding=8, verbose=False)
        print(f"  UV: 几何 {nv}v, UV {nuv}v, {nc} 岛")

        # [4] 像素级烘焙
        print("[4/6] 像素级烘焙 (±Z ray cast)...")
        # 关键: 切到 merged 目录, 让 trimesh 按相对路径找到纹理
        cwd = os.getcwd()
        os.chdir(os.path.dirname(merged))
        src = tb.BakeSource(os.path.basename(merged))
        os.chdir(cwd)
        tex_png = os.path.join(work, 'texture.png')
        tb.bake(src, B_uv, tex_png, args.resolution, verbose=args.verbose, dilate=args.dilate, sample_step=args.sample_step)

        # [5] 转轴 Y-up + scale
        print("[5/6] 转轴 Y-up + scale...")
        v, vt, f = tb.load_simplified_obj(B_uv)
        # 转轴: (x,y,z)Z-up → (x,z,-y)Y-up
        v_rot = np.column_stack([v[:, 0], v[:, 2], -v[:, 1]])
        # scale
        v_rot *= args.scale
        final_obj = os.path.join(work, 'final.obj')

        # [6] 输出 OBJ(带 UV)+ MTL + texture
        print("[6/6] 输出 OBJ + MTL + texture...")
        base = os.path.basename(args.input.rstrip('\\/')).replace('+', '')
        out_obj = os.path.join(args.output, base + '.obj')
        out_mtl = os.path.join(args.output, base + '.mtl')
        out_tex = os.path.join(args.output, 'texture.png')
        # 导出贴图上下翻转(垂直翻转, OBJ vt 保持原样)
        from PIL import Image as _PILImage
        _PILImage.open(tex_png).transpose(_PILImage.FLIP_TOP_BOTTOM).save(out_tex)

        with open(final_obj, 'w') as fp:
            for xyz in v_rot:
                fp.write(f"v {xyz[0]:.6f} {xyz[1]:.6f} {xyz[2]:.6f}\n")
            for uvt in vt:
                fp.write(f"vt {uvt[0]:.6f} {uvt[1]:.6f}\n")  # 烘焙已用 1-v 对齐, vt 保持原样
            for row in f:
                fp.write(f"f {row[0]+1}/{row[1]+1} {row[2]+1}/{row[3]+1} {row[4]+1}/{row[5]+1}\n")
        shutil.copy2(final_obj, out_obj)

        with open(out_mtl, 'w') as fp:
            fp.write(f"newmtl material_0\n")
            fp.write("Ka 0.2 0.2 0.2\nKd 0.8 0.8 0.8\nKs 0 0 0\n")
            fp.write("map_Kd texture.png\n")

        # OBJ 加 mtllib 引用
        obj_data = open(out_obj).read()
        if 'mtllib' not in obj_data.split('\n')[1]:
            obj_data = f"mtllib {base}.mtl\n" + obj_data
            open(out_obj, 'w').write(obj_data)

        print(f"\n=== 完成! ===")
        print(f"  OBJ:   {out_obj}")
        print(f"  MTL:   {out_mtl}")
        print(f"  TEXT:  {out_tex}")
        print(f"  几何:  {len(v):,}v {len(f):,}f, 图集 {args.resolution}²")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
