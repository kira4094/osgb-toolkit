#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osgb_simplifier.py — OSGB 网格合并 + GH 简化 + 纹理烘焙 + FBX 导出工具
=============================================================
管线: OSGB → osgconv转OBJ → pymeshlab GH减面(四策略) → 纹理烘焙 → osgconv转FBX

依赖:
  - pymeshlab (pip install pymeshlab)
  - 官方 OSG 3.6.5 (Objexx 预编译包, 提供 osgconv.exe + osgdb_fbx.dll)

用法:
  python osgb_simplifier.py <input> <output> [options]

参数:
  input   OSGB 工程目录(含 Data/ + metadata.xml) 或单瓦片目录
  output  输出文件(.fbx / .obj / .gltf)

选项:
  --faces N            目标面数(默认 0 = 不简化)
  --strategy S         简化策略: triangular | prob_triangular | planar | prob_planar
  --preserve-boundary  保持网格边界(默认 True)
  --preserve-normal    保持法线方向(默认 True)
  --optimal-placement  GH 最优顶点位置(默认 True)
  --texcoord-weight W  纹理坐标权重(默认 1.0)
  --quality-thr Q      三角形质量阈值(默认 0.3)
  --bake               纹理烘焙(简化后重烘焙纹理)
  --tex-size N         烘焙纹理大小(默认 2048, 如 2048x2048)
  --texels-per-unit T  烘焙纹理精度(texels per unit)
  --dilate N           烘焙边界扩展像素(默认 2)
  --rotation R         输出旋转(默认 -90-1,0,0 即 Z-up→Y-up)
  --keep-obj           保留中间 OBJ 文件
  --verbose            详细输出
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

import pymeshlab
from pymeshlab.pmeshlab import PureValue
import numpy as np

# 四策略 → pymeshlab 参数映射
STRATEGIES = {
    'triangular':       dict(planarquadric=False, qualitythr=0.3),
    'prob_triangular':  dict(planarquadric=False, qualitythr=0.5),
    'planar':           dict(planarquadric=True,  qualitythr=0.3),
    'prob_planar':      dict(planarquadric=True,  qualitythr=0.1),
}

def find_osg():
    """定位 osgconv.exe"""
    env = os.environ.get('OSGROOT')
    if env:
        p = os.path.join(env, 'bin', 'osgconv.exe')
        if os.path.exists(p):
            return p
    # 默认项目路径
    candidates = [
        r'E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph\bin\osgconv.exe',
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    shutil.which('osgconv')
    return None

def find_lod_tiles(input_path, lod):
    """返回每个瓦片的 root.osgb 路径列表
    lod 参数保留用于兼容(实际 LOD 深度由 osgb_full 的 max_lod 控制)
    """
    data_dir = os.path.join(input_path, 'Data')
    if not os.path.isdir(data_dir):
        # 单瓦片模式: 返回该目录的 root.osgb
        if os.path.isdir(input_path):
            name = os.path.basename(input_path)
            root = os.path.join(input_path, name + '.osgb')
            if os.path.exists(root):
                return [root]
            # 兜底: 找非 LOD 的 .osgb
            for f in sorted(os.listdir(input_path)):
                if f.endswith('.osgb') and '_L' not in f:
                    return [os.path.join(input_path, f)]
            return []
        return find_root_tiles(input_path)
    tiles = []
    for entry in sorted(os.listdir(data_dir)):
        d = os.path.join(data_dir, entry)
        if not os.path.isdir(d):
            continue
        root = os.path.join(d, entry + '.osgb')
        if os.path.exists(root):
            tiles.append(root)
    return tiles

def find_root_tiles(input_path):
    """返回要处理的瓦片列表(兼容旧接口)"""
    data_dir = os.path.join(input_path, 'Data')
    if os.path.isdir(data_dir):
        # 工程模式: 遍历所有瓦片目录的根 osgb
        tiles = []
        for entry in sorted(os.listdir(data_dir)):
            d = os.path.join(data_dir, entry)
            if os.path.isdir(d):
                root = os.path.join(d, entry + '.osgb')
                if os.path.exists(root):
                    tiles.append(root)
        return tiles
    # 单瓦片模式
    if input_path.endswith('.osgb'):
        return [input_path]
    # 瓦片目录模式
    name = os.path.basename(input_path)
    root = os.path.join(input_path, name + '.osgb')
    if os.path.exists(root):
        return [root]
    # 目录内找第一个非 LOD osgb
    for f in sorted(os.listdir(input_path)):
        if f.endswith('.osgb') and '_L' not in f:
            return [os.path.join(input_path, f)]
    return []

def _lod_of_file(fn):
    """从文件名提取 LOD 深度(root=0)"""
    import re
    m = re.search(r'_L(\d+)_', os.path.basename(fn))
    return int(m.group(1)) if m else 0


def read_srs_origin(input_path):
    """从 metadata.xml 读取 SRSOrigin 偏移
    返回 (x, y, z) 或 None
    OSGB 瓦片坐标是相对 SRSOrigin 的局部坐标, 需加回真实地理坐标
    """
    import xml.etree.ElementTree as ET
    # 找 metadata.xml: 优先 input/Data 上级, 或 input 本身
    candidates = []
    data_dir = os.path.join(input_path, 'Data')
    if os.path.isdir(data_dir):
        candidates.append(os.path.join(input_path, 'metadata.xml'))
    else:
        # 单瓦片目录: 向上找工程根
        candidates.append(os.path.join(input_path, 'metadata.xml'))
        parent = os.path.dirname(input_path)
        candidates.append(os.path.join(parent, 'metadata.xml'))
        grand = os.path.dirname(parent)
        candidates.append(os.path.join(grand, 'metadata.xml'))
    for c in candidates:
        if os.path.exists(c):
            try:
                root = ET.parse(c).getroot()
                srs = root.find('SRS').text
                origin = root.find('SRSOrigin').text
                ox, oy, oz = [float(v) for v in origin.split(',')]
                return (ox, oy, oz, srs)
            except Exception as e:
                print(f"  [warn] 读取 metadata.xml 失败: {e}")
    return None


def apply_origin_to_obj(obj_path, origin, y_up=True):
    """把 SRSOrigin 偏移加到 OBJ 所有顶点, 并旋转到 Y-up
    OSGB 局部坐标 (x,y,z) 是 ENU 系: x=东, y=北, z=高
    1. 加偏移 → 地理坐标: X=ox+x, Y=oy+y, Z=oz+z
    2. 旋转到 Y-up (Rx -90°): x'=x, y'=z, z'=-y
    结果: FBX.X=东(大数), FBX.Y=高(Y-up 上方向), FBX.Z=-北
    """
    ox, oy, oz, _ = origin
    lines = []
    with open(obj_path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('v ') and len(line.split()) >= 4:
                parts = line.split()
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                gx, gy, gz = x + ox, y + oy, z + oz  # 地理坐标
                if y_up:
                    # Rx(-90°): 东→X, 高→Y, -北→Z
                    nx, ny, nz = gx, gz, -gy
                else:
                    nx, ny, nz = gx, gy, gz
                lines.append(f"v {nx:.6f} {ny:.6f} {nz:.6f}\n")
            else:
                lines.append(line)
    with open(obj_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)


def osgb_to_obj(osgconv, tiles, out_obj, verbose=False, max_lod=22):
    """多个 OSGB 文件用 osgb_full.exe 分层回退合并转成 OBJ
    每区域取最深可用 LOD(到 max_lod), 无空洞(模拟 OPEditor DatabasePager)
    """
    if not tiles:
        raise RuntimeError("未找到 OSGB 瓦片")
    origin = read_srs_origin(os.path.dirname(os.path.dirname(tiles[0])))
    # osgb_full.exe 路径(与脚本同目录的 engine/)
    engine_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'engine')
    osgb_full = os.path.join(engine_dir, 'osgb_full.exe')
    if not os.path.exists(osgb_full):
        raise RuntimeError(f"找不到 osgb_full.exe: {osgb_full}")

    # 找每个瓦片的 root.osgb
    tmp_dir = tempfile.mkdtemp(prefix='osgb_full_')
    objs = []
    # 子进程环境: 设置 OSG 插件路径 + PATH(加载 osg.dll)
    osg_bin = os.path.dirname(osgconv)
    env = dict(os.environ)
    env['OSG_LIBRARY_PATH'] = osg_bin
    env['PATH'] = osg_bin + os.pathsep + env.get('PATH', '')
    try:
        for tile in tiles:
            # tile 是 root.osgb 路径
            if not os.path.exists(tile) or not tile.endswith('.osgb'):
                continue
            tmp_obj = os.path.join(tmp_dir, os.path.basename(os.path.dirname(tile)) + '.obj')
            if os.path.exists(tmp_obj):
                objs.append(tmp_obj)
                continue
            # 用 osgb_full 分层回退到 max_lod
            r = subprocess.run([osgb_full, tile, tmp_obj, str(max_lod)],
                               capture_output=True, text=True, encoding='utf-8',
                               errors='replace', env=env)
            if r.returncode == 0 and os.path.exists(tmp_obj):
                objs.append(tmp_obj)
            else:
                print(f"  [warn] osgb_full 失败 {tile}: {r.stderr[-200:] if r.stderr else ''}")
        if not objs:
            raise RuntimeError("所有瓦片处理失败")
        # 用 osgconv 合并所有瓦片 OBJ(可靠, 支持大文件)
        merge_cmd = [osgconv] + objs + [out_obj]
        r = subprocess.run(merge_cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env)
        if r.returncode != 0 or not os.path.exists(out_obj):
            raise RuntimeError(f"osgconv 合并失败: {r.stderr[-200:]}")
        ms = pymeshlab.MeshSet()
        ms.load_new_mesh(out_obj)
        if verbose:
            print(f"  [osgb_full] 合并 {len(objs)} 个瓦片(LOD分层回退到{max_lod}) → OBJ")
        return ms
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def simplify_obj(in_obj, out_obj, args):
    """pymeshlab GH 减面"""
    ms = pymeshlab.MeshSet()
    ms.load_new_mesh(in_obj)
    before_v, before_f = ms.current_mesh().vertex_number(), ms.current_mesh().face_number()
    if args.verbose:
        print(f"  输入: {before_v} 顶点, {before_f} 面, 纹理 {ms.current_mesh().texture_number()}")

    # 1. 合并重复顶点 + 跨瓦片接缝融合
    #    阈值自适应: 包围盒对角线 × merge_ratio(默认 1e-3, 融合瓦片接缝)
    bb = ms.current_mesh().bounding_box()
    diag = bb.diagonal()
    merge_thr = diag * args.merge_ratio
    ms.meshing_merge_close_vertices(threshold=PureValue(merge_thr))
    if args.verbose:
        print(f"  合并顶点(阈值 {merge_thr:.4f}): {ms.current_mesh().vertex_number()} 顶点")

    # 2. GH 减面
    if args.faces > 0 and args.faces < before_f:
        strat = STRATEGIES.get(args.strategy, STRATEGIES['triangular'])
        params = dict(
            targetfacenum=args.faces,
            preserveboundary=args.preserve_boundary,
            preservenormal=args.preserve_normal,
            optimalplacement=args.optimal_placement,
            extratcoordw=args.texcoord_weight,
        )
        params.update(strat)
        if args.quality_thr is not None:
            params['qualitythr'] = args.quality_thr
        # 优先用带纹理的减面; 若纹理不一致(部分面无UV)则回退无纹理减面
        try:
            ms.meshing_decimation_quadric_edge_collapse_with_texture(**params)
        except Exception as e:
            if args.verbose:
                print(f"  [warn] 带纹理减面失败({str(e)[:60]}), 回退无纹理减面")
            # 移除 UV 后减面
            params.pop('extratcoordw', None)
            ms.meshing_decimation_quadric_edge_collapse(**params)
        if args.verbose:
            print(f"  简化后: {ms.current_mesh().vertex_number()} 顶点, {ms.current_mesh().face_number()} 面")

    # 2.5 各向同性重网格化(优化布线, 三角形等边化, 模拟 OPEditor)
    #     减面后边折叠产生细长三角形, 重网格化让布线均匀
    if args.remesh and ms.current_mesh().face_number() > 0:
        try:
            bb = ms.current_mesh().bounding_box()
            diag = bb.diagonal()
            # 目标边长按"目标面数"算: 每面近似等边三角形, 面积≈0.433*L²
            # 总表面积 ≈ 目标面数 * 0.433 * L² → L = sqrt(总表面积/(0.433*目标面数))
            # 用包围盒对角线近似表面积: 倾斜摄影是近似平面区域
            target_faces = args.faces if args.faces > 0 else ms.current_mesh().face_number()
            # 估计表面积: 用包围盒的 X-Y 平面面积(倾斜摄影近似水平)
            try:
                import numpy as _np
                # 用 pymeshlab 算实际表面积
                ms2_area = ms.current_mesh().surface_area()
                target_len = _np.sqrt(ms2_area / (0.433 * target_faces))
            except Exception:
                target_len = diag / max(1.0, _np.sqrt(max(target_faces, 1)))
            if args.remesh_targetlen:
                target_len = args.remesh_targetlen
            ms.meshing_isotropic_explicit_remeshing(
                iterations=args.remesh_iterations,
                targetlen=PureValue(target_len),
                splitflag=True, collapseflag=True,
                swapflag=True, smoothflag=True,
                reprojectflag=True, checksurfdist=False,
            )
            if args.verbose:
                print(f"  重网格化(边长 {target_len:.4f}): {ms.current_mesh().vertex_number()} 顶点, "
                      f"{ms.current_mesh().face_number()} 面")
            # 再减面回目标面数(remesh 会增加面数, 需再减回目标)
            if args.faces > 0 and ms.current_mesh().face_number() > args.faces:
                params2 = dict(targetfacenum=args.faces,
                                preserveboundary=args.preserve_boundary,
                                preservenormal=args.preserve_normal,
                                optimalplacement=args.optimal_placement)
                params2.update(strat)
                try:
                    ms.meshing_decimation_quadric_edge_collapse_with_texture(**params2)
                except Exception:
                    params2.pop('extratcoordw', None)
                    ms.meshing_decimation_quadric_edge_collapse(**params2)
                if args.verbose:
                    print(f"  再减面: {ms.current_mesh().vertex_number()} 顶点, "
                          f"{ms.current_mesh().face_number()} 面")
        except Exception as e:
            if args.verbose:
                print(f"  [warn] 重网格化失败({str(e)[:60]})")

    # 3. 纹理烘焙(可选)
    if args.bake:
        # 计算纹理大小: texels_per_unit * 模型对角线
        bb = ms.current_mesh().bounding_box()
        diag = bb.diagonal()
        if args.texels_per_unit and diag > 0:
            size = max(64, int(args.texels_per_unit * diag))
            size = min(8192, size)
        else:
            size = args.tex_size
        # 转移原始纹理到简化后网格
        ms.transfer_attributes_to_texture_per_vertex(
            sourcemesh=0, targetmesh=0,
            attributeenum='Texture Color',
            textw=size, texth=size,
            textname=os.path.basename(out_obj).replace('.obj', '.png'),
            overwrite=True, pullpush=True,
        )
        if args.verbose:
            print(f"  纹理烘焙: {size}x{size}")

    ms.save_current_mesh(out_obj)
    return ms

def obj_to_fbx(osgconv, in_obj, out_fbx, rotation, verbose=False):
    """osgconv 转 FBX"""
    cmd = [osgconv]
    if rotation:
        cmd += ['-o', rotation]
    cmd += [in_obj, out_fbx]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f"osgconv FBX 导出失败: {r.stderr[:300]}")
    return r

def main():
    ap = argparse.ArgumentParser(description='OSGB 合并+GH简化+纹理烘焙+FBX导出')
    ap.add_argument('input', help='OSGB 工程目录或瓦片目录')
    ap.add_argument('output', help='输出文件(.fbx/.obj/.gltf)')
    ap.add_argument('--lod', default='root',
                    help='LOD 层级: root(默认,根瓦片) | all(全部) | L16~L22(指定层级)')
    ap.add_argument('--merge-ratio', type=float, default=1e-3,
                    help='顶点融合阈值比例(包围盒对角线×此值, 默认1e-3, 融合瓦片接缝)')
    ap.add_argument('--faces', type=int, default=0, help='目标面数')
    ap.add_argument('--strategy', default='planar',
                    choices=list(STRATEGIES.keys()), help='简化策略')
    ap.add_argument('--preserve-boundary', action='store_true', default=True,
                    help='保持边界')
    ap.add_argument('--preserve-normal', action='store_true', default=True,
                    help='保持法线')
    ap.add_argument('--optimal-placement', action='store_true', default=True,
                    help='GH 最优位置')
    ap.add_argument('--texcoord-weight', type=float, default=1.0,
                    help='纹理坐标权重')
    ap.add_argument('--quality-thr', type=float, default=None,
                    help='三角形质量阈值')
    ap.add_argument('--remesh', action='store_true', default=True,
                    help='减面后各向同性重网格化(优化布线)')
    ap.add_argument('--remesh-iterations', type=int, default=10,
                    help='重网格化迭代次数')
    ap.add_argument('--remesh-targetlen', type=float, default=None,
                    help='重网格化目标边长(默认自动)')
    ap.add_argument('--no-remesh', action='store_true', help='关闭重网格化')
    ap.add_argument('--bake', action='store_true', help='纹理烘焙')
    ap.add_argument('--tex-size', type=int, default=2048, help='烘焙纹理大小')
    ap.add_argument('--texels-per-unit', type=float, default=None,
                    help='烘焙纹理精度')
    ap.add_argument('--dilate', type=int, default=2, help='烘焙边界扩展')
    ap.add_argument('--coords', default='geographic',
                    choices=['geographic', 'local', 'centered'],
                    help='坐标模式: geographic(真实地理坐标,默认) | local(局部坐标) | centered(居中)')
    ap.add_argument('--keep-obj', action='store_true', help='保留中间 OBJ')
    ap.add_argument('--verbose', action='store_true', help='详细输出')
    args = ap.parse_args()
    if getattr(args, 'no_remesh', False):
        args.remesh = False

    osgconv = find_osg()
    if not osgconv:
        print("错误: 找不到 osgconv.exe, 请设置 OSGROOT 环境变量")
        sys.exit(1)
    if args.verbose:
        print(f"osgconv: {osgconv}")

    # 输出格式判断
    ext = os.path.splitext(args.output)[1].lower()
    if ext not in ('.fbx', '.obj', '.gltf', '.glb'):
        print(f"错误: 不支持的输出格式 {ext}")
        sys.exit(1)

    work_dir = tempfile.mkdtemp(prefix='osgb_simp_')
    try:
        merged_obj = os.path.join(work_dir, 'merged.obj')
        simplified_obj = os.path.join(work_dir, 'simplified.obj')

        print(f"[1/3] 读取 OSGB(LOD={args.lod}) → OBJ ...")
        max_lod = 0 if args.lod == 'root' else _lod_of_file(f'_{args.lod}_x.osgb')
        ms = osgb_to_obj(osgconv, find_lod_tiles(args.input, args.lod), merged_obj,
                         args.verbose, max_lod=max_lod)

        print(f"[2/3] GH 简化(策略={args.strategy}, 目标面数={args.faces}) ...")
        ms = simplify_obj(merged_obj, simplified_obj, args)

        # 坐标处理: 简化后在局部坐标完成, 导出前应用偏移/居中
        origin = read_srs_origin(args.input)
        if args.coords == 'geographic' and origin:
            # 两步: 1) 加 SRSOrigin 偏移(东/北/高) 2) flipz 让 osgconv 转 Y-up 后 Y=+高
            apply_origin_to_obj(simplified_obj, origin, y_up=False)
            ms2 = pymeshlab.MeshSet()
            ms2.load_new_mesh(simplified_obj)
            ms2.apply_matrix_flip_or_swap_axis(flipz=True)
            ms2.save_current_mesh(simplified_obj)
            print(f"  [coords] 地理坐标+Y-up: 偏移 ({origin[0]:.1f}, {origin[1]:.1f}, {origin[2]:.1f}) + flipz")
        elif args.coords == 'centered':
            # 居中: 减去包围盒中心
            import numpy as np
            xs, ys, zs = [], [], []
            with open(simplified_obj, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith('v '):
                        p = line.split(); xs.append(float(p[1])); ys.append(float(p[2])); zs.append(float(p[3]))
            if xs:
                cx, cy, cz = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2
                lines = []
                with open(simplified_obj, encoding='utf-8', errors='replace') as f:
                    for line in f:
                        if line.startswith('v '):
                            p = line.split();
                            lines.append(f"v {float(p[1])-cx:.6f} {float(p[2])-cy:.6f} {float(p[3])-cz:.6f}\n")
                        else:
                            lines.append(line)
                with open(simplified_obj, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
                print(f"  [coords] 居中: 中心 ({cx:.1f}, {cy:.1f}, {cz:.1f})")
        else:
            print("  [coords] 局部坐标(不偏移)")

        if ext == '.fbx':
            print(f"[3/3] 导出 FBX ...")
            obj_to_fbx(osgconv, simplified_obj, args.output, "", args.verbose)
        else:
            print(f"[3/3] 导出 {ext} ...")
            shutil.copy2(simplified_obj, args.output)

        if args.keep_obj:
            shutil.copy2(simplified_obj, os.path.join(os.path.dirname(args.output),
                        os.path.splitext(os.path.basename(args.output))[0] + '.obj'))
            print(f"  中间 OBJ: {os.path.join(os.path.dirname(args.output), os.path.splitext(os.path.basename(args.output))[0] + '.obj')}")

        print(f"完成! 输出: {args.output} ({os.path.getsize(args.output) // 1024} KB)")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

if __name__ == '__main__':
    main()
