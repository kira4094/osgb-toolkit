#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osgb_merge_export.py — OSGB 网格合并 + FBX 导出(独立步骤, 已检验通过)
====================================================================
流程: osgb_full(LOD分层回退) → pymeshlab merge(0.022) → 纯几何OBJ → FBX → GlobalSettings补丁

用法:
  python osgb_merge_export.py <输入瓦片/工程目录> <输出.fbx> [--lod L22] [--merge-thr 0.022]

关键参数(从 OPEditor 逆向):
  - merge 阈值 0.022 (对角线×2.7e-4): 每面独立顶点 → 共享顶点 (95359→52497)
  - FBX UnitScaleFactor=100: 3ds Max 显示 scale=100 的来源
  - FBX GlobalSettings: UpAxis=2, FrontAxis=1, FrontAxisSign=-1 (轴向正确)
  - 必须用纯几何 OBJ (无 vn/vt) 导出, 否则 FBX 顶点未融合
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import tempfile

import pymeshlab
import numpy as np
from pymeshlab.pmeshlab import PureValue

# 项目根(找 engine/osgb_full.exe)
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_osg():
    env = os.environ.get('OSGROOT')
    if env:
        p = os.path.join(env, 'bin', 'osgconv.exe')
        if os.path.exists(p):
            return p
    p = os.path.join(PROJ, 'thirdparty', 'OpenSceneGraph', 'bin', 'osgconv.exe')
    if os.path.exists(p):
        return p
    return shutil.which('osgconv')


def osgb_env(osgconv):
    """子进程环境: OSG 插件路径 + PATH"""
    osg_bin = os.path.dirname(osgconv)
    env = dict(os.environ)
    env['OSG_LIBRARY_PATH'] = osg_bin
    env['PATH'] = osg_bin + os.pathsep + env.get('PATH', '')
    return env


def find_root_tiles(input_path):
    """返回每个瓦片的 root.osgb"""
    data_dir = os.path.join(input_path, 'Data')
    if os.path.isdir(data_dir):
        tiles = []
        for entry in sorted(os.listdir(data_dir)):
            d = os.path.join(data_dir, entry)
            if os.path.isdir(d):
                root = os.path.join(d, entry + '.osgb')
                if os.path.exists(root):
                    tiles.append(root)
        return tiles
    if os.path.isdir(input_path):
        name = os.path.basename(input_path)
        root = os.path.join(input_path, name + '.osgb')
        if os.path.exists(root):
            return [root]
        for f in sorted(os.listdir(input_path)):
            if f.endswith('.osgb') and '_L' not in f:
                return [os.path.join(input_path, f)]
    return []


def osgb_full_load(osgb_full, osgconv, tiles, out_obj, max_lod, env):
    """用 osgb_full.exe 对每个瓦片分层回退加载, 合并所有瓦片 OBJ
    返回 (面数, 顶点数): 从 osgb_full 输出解析加载统计
    """
    tmp_dir = tempfile.mkdtemp(prefix='osgb_full_')
    objs = []
    total_faces = 0
    total_verts = 0
    try:
        for tile in tiles:
            if not os.path.exists(tile):
                continue
            tmp_obj = os.path.join(tmp_dir, os.path.basename(os.path.dirname(tile)) + '.obj')
            if os.path.exists(tmp_obj):
                objs.append(tmp_obj)
                continue
            r = subprocess.run([osgb_full, tile, tmp_obj, str(max_lod)],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', env=env)
            if r.returncode == 0 and os.path.exists(tmp_obj):
                objs.append(tmp_obj)
                # 从输出解析 "Total: X vertices, Y faces"
                import re
                m = re.search(r'Total:\s*(\d+)\s*vertices,\s*(\d+)\s*faces', r.stdout or '')
                if m:
                    v, f = int(m.group(1)), int(m.group(2))
                    total_verts += v
                    total_faces += f
            else:
                print(f"  [warn] osgb_full 失败 {tile}: {r.stderr[-200:] if r.stderr else ''}")
        if not objs:
            raise RuntimeError("所有瓦片处理失败")
        if len(objs) == 1:
            # 单瓦片: 直接用 osgb_full 输出, 不做 osgconv 合并(避免 OBJ 翻转!)
            shutil.copy2(objs[0], out_obj)
            # 复制 MTL + 纹理文件(烘焙需要!)
            src_dir = os.path.dirname(objs[0])
            dst_dir = os.path.dirname(out_obj)
            for fname in os.listdir(src_dir):
                if fname.endswith(('.mtl', '.jpg', '.png', '.jpeg')) or fname.startswith('texture_'):
                    shutil.copy2(os.path.join(src_dir, fname), os.path.join(dst_dir, fname))
            print(f"  [osgb_full] 单瓦片(LOD分层回退到{max_lod}) → OBJ"
                  f" (加载 {total_verts:,} 顶点, {total_faces:,} 面)")
        else:
            # 多瓦片: osgconv 合并 (注意: osgconv 读OBJ按Y-up, 多瓦片坐标需统一)
            merge_cmd = [osgconv] + objs + [out_obj]
            r = subprocess.run(merge_cmd, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', env=env)
            if r.returncode != 0 or not os.path.exists(out_obj):
                raise RuntimeError(f"osgconv 合并失败: {r.stderr[-200:]}")
            print(f"  [osgb_full] 合并 {len(objs)} 瓦片(LOD分层回退到{max_lod}) → OBJ"
                  f" (加载 {total_verts:,} 顶点, {total_faces:,} 面)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return total_verts, total_faces


def merge_mesh(in_obj, out_pure_obj, threshold=None, stitch_thr=0.2, verbose=False):
    """pymeshlab 网格合并 + 边界缝合 + 输出纯几何 OBJ (不转轴)
    默认阈值 0.022 (OPEditor 对齐, 已验证得到 52,497v)
    边界缝合(stitch_thr): 消除小瓦片接缝点, 模拟 OPEditor StitchBorders
    注意: 不转轴! 保持 Z-up (Y=北, Z=高), 和 simp_stitch_rot0 一致
    轴向由 GlobalSettings 补丁控制 (osgconv 读 FBX 转 Y-up 显示)
    纯几何 OBJ = 只有 v + f (无 vn/vt), 保证 FBX 顶点融合
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from stitch_borders import stitch_borders as sb_stitch

    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(in_obj)
    if threshold is None:
        threshold = 0.022  # OPEditor 合并阈值(固定值, 非比例)
    ms.meshing_merge_close_vertices(threshold=PureValue(threshold))
    ms.meshing_remove_unreferenced_vertices()
    m = ms.current_mesh()
    if verbose:
        print(f"  网格合并(阈值 {threshold:.4f}): {m.vertex_number()}v / {m.face_number()}f")

    # 边界缝合: 消除小瓦片接缝点(不转轴)
    V = m.vertex_matrix()
    F = m.face_matrix()
    V2, F2 = sb_stitch(V, F, stitch_thr, max_iter=3)
    if verbose:
        print(f"  边界缝合(阈值 {stitch_thr}): {len(V)} → {len(V2)} 顶点, {len(F)} → {len(F2)} 面")

    # 不转轴! 保持 Z-up (Y=北, Z=高), 和 simp_stitch_rot0 一致
    # 手动写纯几何 OBJ
    with open(out_pure_obj, 'w') as f:
        f.write("# Pure geometry OBJ (Z-up)\n")
        for v in V2:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for tri in F2:
            f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
    return ms


def obj_to_fbx(osgconv, in_obj, out_fbx, env, model_name=None):
    """OBJ → FBX (用 osgb_named.exe, 节点名 = model_name)
    轴向由 GlobalSettings 补丁控制, 模型名在 C++ 层设置(不碰二进制)
    """
    engine_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engine')
    osgb_named = os.path.join(engine_dir, 'osgb_named.exe')
    if os.path.exists(osgb_named):
        if model_name is None:
            model_name = os.path.splitext(os.path.basename(out_fbx))[0]
        r = subprocess.run([osgb_named, in_obj, out_fbx, model_name],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', env=env, timeout=180)
        if r.returncode != 0 or not os.path.exists(out_fbx):
            raise RuntimeError(f"osgb_named 导出失败: {r.stderr[-300:]}")
        if r.stdout:
            for line in r.stdout.strip().split('\n'):
                if 'Written' in line:
                    print(f"  {line.strip()}")
    else:
        # 兜底: osgconv 直接转
        r = subprocess.run([osgconv, in_obj, out_fbx], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env)
        if r.returncode != 0 or not os.path.exists(out_fbx):
            raise RuntimeError(f"osgconv FBX 导出失败: {r.stderr[-300:]}")


def rename_fbx_model(fbx_path, model_name):
    """把 FBX 里的 DefaultName 完整替换成 model_name
    处理长度差异: DefaultName\0\1Model(18) → model_name\0\1Model(可变)
    同步修正: 字符串长度字段 + 节点 plen + 后续数据偏移
    """
    data = bytearray(open(fbx_path, 'rb').read())
    old = b'DefaultName\x00\x01Model'
    idx = data.find(old)
    if idx < 0:
        # 可能已是自定义名, 检查
        print(f"  [warn] 未找到 DefaultName 模式")
        return
    # 新内容: model_name + \0\1 + Model
    new_content = model_name.encode('utf-8') + b'\x00\x01Model'
    delta = len(new_content) - len(old)  # 长度差

    # 1. 修改字符串长度字段 (S 类型后的 4 字节, 在 old 前 4 字节)
    str_len_pos = idx - 4
    old_len = struct.unpack_from('<I', data, str_len_pos)[0]
    if old_len != 18:
        print(f"  [warn] 字符串长度异常 {old_len}")
    struct.pack_into('<I', data, str_len_pos, len(new_content))

    # 2. 替换内容 + 处理长度差
    # 把 old 位置后的数据(含 old)整体替换
    # 新数据 = [0:idx] + new_content + [idx+18:]
    new_data = bytearray(data[:idx])
    new_data += new_content
    new_data += data[idx + 18:]

    # 3. 修正节点 plen (Model 节点的属性总长度 + delta)
    # 找 Model 节点: \x05Model 在 idx 前
    node_start = new_data.find(b'\x05Model', max(0, idx - 40))
    if node_start >= 0 and node_start < idx:
        # plen 在节点: [05][Model][nprops:2][plen:4]
        plen_pos = node_start + 9
        plen = struct.unpack_from('<I', new_data, plen_pos)[0]
        # 安全: 只当 plen 合理时修正
        if plen < len(new_data):
            struct.pack_into('<I', new_data, plen_pos, plen + delta)
            print(f"  plen: {plen} → {plen + delta}")

    open(fbx_path, 'wb').write(new_data)
    print(f"  模型名: → {model_name}")


def patch_fbx_global(fbx_path, unit_scale=100.0, up_axis=2, front_axis=1, front_sign=-1):
    """修改 FBX 二进制 GlobalSettings, 对齐 OPEditor
    - UnitScaleFactor = 100 (3ds Max 显示 scale=100)
    - UpAxis=2, FrontAxis=1, FrontAxisSign=-1 (轴向正确)
    节点 Lcl Scaling/Rotation 保持默认 (1,1,1)/(0,0,0)
    """
    data = bytearray(open(fbx_path, 'rb').read())

    def patch_double(kw, val):
        idx = data.find(kw.encode())
        if idx < 0:
            return False
        for i in range(idx, min(idx + 80, len(data))):
            if data[i] == 0x44:  # 'D' double
                old = struct.unpack_from('<d', data, i + 1)[0]
                struct.pack_into('<d', data, i + 1, val)
                print(f"  {kw}: {old:g} → {val:g}")
                return True
        return False

    def patch_int(kw, val):
        idx = data.find(kw.encode())
        if idx < 0:
            return False
        # 属性值通常是第二个 'I' int (第一个是类型标识干扰)
        chunk = data[idx:idx + 100]
        int_positions = []
        for i in range(len(chunk) - 4):
            if chunk[i] == 0x49:
                int_positions.append(idx + i + 1)
        if len(int_positions) >= 2:
            struct.pack_into('<i', data, int_positions[1], val)
            print(f"  {kw}: → {val}")
            return True
        return False

    patch_double('UnitScaleFactor', unit_scale)
    patch_double('OriginalUnitScaleFactor', unit_scale)
    patch_int('UpAxis', up_axis)
    patch_int('FrontAxis', front_axis)
    patch_int('FrontAxisSign', front_sign)
    open(fbx_path, 'wb').write(data)
    print("  GlobalSettings 补丁完成")


def main():
    ap = argparse.ArgumentParser(description='OSGB 网格合并 + FBX 导出')
    ap.add_argument('input', help='OSGB 工程目录 或 瓦片目录')
    ap.add_argument('output', help='输出 .fbx')
    ap.add_argument('--lod', default='L22', help='LOD 层级(默认 L22)')
    ap.add_argument('--name', default=None,
                    help='模型名(默认自动从输入提取, 如 Tile_+034_+036)')
    ap.add_argument('--merge-thr', type=float, default=None,
                    help='合并阈值(默认 0.022)')
    ap.add_argument('--stitch-thr', type=float, default=0.2,
                    help='边界缝合阈值(默认 0.2, 消除瓦片接缝)')
    ap.add_argument('--faces', type=int, default=10000,
                    help='减面目标面数(默认 10000, 0=不减面)')
    ap.add_argument('--strategy', default='planar',
                    choices=['planar', 'prob_planar', 'triangular', 'prob_triangular'],
                    help='减面策略(默认 planar)')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--uv', action='store_true', help='自动分UV + 纹理烘焙(需先转轴)')
    ap.add_argument('--uv-resolution', type=int, default=2048, help='UV纹理分辨率(默认2048)')
    args = ap.parse_args()

    osgconv = find_osg()
    if not osgconv:
        print("错误: 找不到 osgconv.exe, 设置 OSGROOT")
        sys.exit(1)
    osgb_full = os.path.join(PROJ, 'engine', 'osgb_full.exe')
    if not os.path.exists(osgb_full):
        print(f"错误: 找不到 osgb_full.exe: {osgb_full}")
        sys.exit(1)
    env = osgb_env(osgconv)
    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)

    # 模型名: 默认从输入提取(瓦片目录名, 与 Data/ 下文件夹一致)
    if args.name is None:
        # 单瓦片: input 是 Tile_+XX_+YY 目录 → 取目录名
        # 工程: 取 output 文件名
        inp = args.input.rstrip('\\/')
        if os.path.isdir(inp) and os.path.basename(inp).startswith('Tile_'):
            args.name = os.path.basename(inp)
        else:
            args.name = os.path.splitext(os.path.basename(args.output))[0]
    # 移除特殊字符 + (Maya 会转义成 FBXASC043), 保持 3ds Max/Maya 显示一致
    args.name = args.name.replace('+', '')
    if args.verbose:
        print(f"模型名: {args.name}")

    # LOD → max_lod
    max_lod = 0 if args.lod == 'root' else int(args.lod.replace('L', '')) if args.lod.upper().startswith('L') else int(args.lod)

    work = tempfile.mkdtemp(prefix='osgb_merge_')
    try:
        raw_obj = os.path.join(work, 'raw.obj')
        merged_obj = os.path.join(work, 'merged.obj')
        simp_obj = os.path.join(work, 'simplified.obj')

        # 第1步: 分层回退加载
        print(f"[1/5] 分层回退加载 OSGB (LOD={args.lod}) → OBJ")
        tiles = find_root_tiles(args.input)
        if not tiles:
            raise RuntimeError("未找到 OSGB 瓦片")
        osgb_full_load(osgb_full, osgconv, tiles, raw_obj, max_lod, env)

        # 第2步: 网格合并 + 边界缝合
        print("[2/5] 网格合并 + 边界缝合")
        ms = merge_mesh(raw_obj, merged_obj, args.merge_thr, args.stitch_thr, args.verbose)

        # 第3步: 减面 (GH 平面策略)
        if args.faces > 0:
            print(f"[3/5] 减面 (策略={args.strategy}, 目标面数={args.faces})")
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(merged_obj)
            before_f = ms.current_mesh().face_number()
            if args.faces < before_f:
                strat = {
                    'planar': dict(planarquadric=True, qualitythr=0.3),
                    'prob_planar': dict(planarquadric=True, qualitythr=0.1),
                    'triangular': dict(planarquadric=False, qualitythr=0.3),
                    'prob_triangular': dict(planarquadric=False, qualitythr=0.5),
                }.get(args.strategy, dict(planarquadric=True, qualitythr=0.3))
                ms.meshing_decimation_quadric_edge_collapse(
                    targetfacenum=args.faces,
                    preserveboundary=False,
                    preservenormal=True,
                    optimalplacement=True,
                    **strat)
                if args.verbose:
                    print(f"  减面: {before_f} → {ms.current_mesh().face_number()} 面, "
                          f"{ms.current_mesh().vertex_number()} 顶点")
                # 写纯几何 OBJ(减面后)
                m = ms.current_mesh()
                V = m.vertex_matrix(); F = m.face_matrix()
                with open(simp_obj, 'w') as f:
                    for v in V:
                        f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                    for tri in F:
                        f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
            else:
                simp_obj = merged_obj  # 不需要减面
        else:
            print("[3/5] 跳过减面 (--faces 0)")
            simp_obj = merged_obj

        # 第4步: 调整轴向 (Z-up → Y-up, rotateX=-90)
        print("[4/5] 调整轴向 (Z-up → Y-up)")
        import numpy as np
        V = []; F = []
        for line in open(simp_obj, encoding='utf-8', errors='replace'):
            if line.startswith('v '):
                p = line.split(); V.append([float(p[1]), float(p[2]), float(p[3])])
            elif line.startswith('f '):
                p = line.split()[1:]
                F.append([int(x.split('/')[0])-1 for x in p[:3]])
        V = np.array(V); F = np.array(F)
        # rotateX(-90): (x,y,z)→(x,z,-y), Y=高度
        V_rot = np.column_stack([V[:,0], V[:,2], -V[:,1]])
        axis_obj = os.path.join(work, 'axis.obj')
        with open(axis_obj, 'w') as f:
            for v in V_rot:
                f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
            for tri in F:
                f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
        if args.verbose:
            print(f"  转轴: {len(V)} 顶点")

        # 第5步: 自动分 UV (可选) + 导出 FBX
        if args.uv:
            print("[5/6] 自动分 UV (xatlas)...")
            import uv_unwrap
            uv_obj = os.path.join(work, 'unwrapped.obj')
            nv, nf, nchart = uv_unwrap.unwrap(axis_obj, uv_obj,
                                              resolution=args.uv_resolution,
                                              padding=4, verbose=args.verbose)
            if args.verbose:
                print(f"  UV: {nv} 顶点, {nf} 面, {nchart} 岛")
            export_obj = uv_obj
            print("[6/6] 导出 FBX + 重命名 + GlobalSettings")
        else:
            export_obj = axis_obj
            print("[5/5] 导出 FBX + 重命名 + GlobalSettings")
        obj_to_fbx(osgconv, export_obj, args.output, env, model_name=args.name)
        patch_fbx_global(args.output)

        size = os.path.getsize(args.output) // 1024
        print(f"完成! {args.output} ({size} KB)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
