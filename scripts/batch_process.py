#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch_process.py — 批量处理脚本
对 OSGB 工程的每个瓦片(或指定 LOD 层级)执行: 合并 → GH 简化 → FBX

用法:
  python batch_process.py <osgb工程目录> <输出目录> [选项]

选项:
  --lod LOD          LOD 层级: root|all|L16~L22(默认 root)
  --faces N          每瓦片目标面数(默认 0 不简化)
  --strategy S       简化策略
  --bake             纹理烘焙
  --workers N        并行数(默认 4)
  --overwrite        覆盖已存在输出
"""
import argparse
import os
import subprocess
import sys
import concurrent.futures

def main():
    ap = argparse.ArgumentParser(description='OSGB 批量减面工具')
    ap.add_argument('input', help='OSGB 工程目录(含 Data/)')
    ap.add_argument('output', help='输出目录')
    ap.add_argument('--lod', default='root', help='LOD: root|all|L16~L22')
    ap.add_argument('--faces', type=int, default=0, help='每瓦片目标面数')
    ap.add_argument('--strategy', default='planar',
                    choices=['triangular','prob_triangular','planar','prob_planar'])
    ap.add_argument('--bake', action='store_true', help='纹理烘焙')
    ap.add_argument('--workers', type=int, default=4, help='并行数')
    ap.add_argument('--overwrite', action='store_true', help='覆盖已存在输出')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'osgb_simplifier.py')
    data_dir = os.path.join(args.input, 'Data')
    if not os.path.isdir(data_dir):
        print(f"错误: {data_dir} 不存在")
        sys.exit(1)

    # 收集所有瓦片目录
    tiles = []
    for entry in sorted(os.listdir(data_dir)):
        d = os.path.join(data_dir, entry)
        if os.path.isdir(d):
            tiles.append(d)
    if not tiles:
        print("错误: Data/ 下没有瓦片目录")
        sys.exit(1)

    os.makedirs(args.output, exist_ok=True)

    # 构建任务列表
    tasks = []
    for t in tiles:
        name = os.path.basename(t)
        out = os.path.join(args.output, f'{name}_lod{args.lod}.fbx')
        if os.path.exists(out) and not args.overwrite:
            if args.verbose:
                print(f"跳过(已存在): {out}")
            continue
        tasks.append((t, out))

    if not tasks:
        print("所有瓦片已处理过, 用 --overwrite 重新处理")
        return

    print(f"共 {len(tasks)} 个瓦片, {args.workers} 并行, LOD={args.lod}, 目标面数={args.faces}")

    def run_one(item):
        t, out = item
        cmd = [sys.executable, script, t, out,
               '--lod', args.lod, '--faces', str(args.faces),
               '--strategy', args.strategy]
        if args.bake:
            cmd.append('--bake')
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode == 0:
            size = os.path.getsize(out) // 1024
            return f"OK   {os.path.basename(t)} → {size} KB"
        else:
            return f"FAIL {os.path.basename(t)}: {r.stderr[-200:]}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(run_one, tasks))

    ok = sum(1 for r in results if r.startswith('OK'))
    fail = sum(1 for r in results if r.startswith('FAIL'))
    print(f"\n完成: {ok} 成功, {fail} 失败")
    for r in results:
        print("  " + r)

if __name__ == '__main__':
    main()
