# -*- coding: utf-8 -*-
"""pymeshlab 减面+纹理验证"""
import pymeshlab, sys, os
from pymeshlab.pmeshlab import PureValue
sys.stdout.reconfigure(encoding='utf-8')

OBJ = os.environ.get('TILE_OBJ', r'D:\WindowsOS\Temp\t34.obj')
OUT = os.environ.get('TILE_OUT', r'D:\WindowsOS\Temp\t34_dec.obj')

ms = pymeshlab.MeshSet()
ms.load_new_mesh(OBJ)
print("原始:", ms.current_mesh().vertex_number(), "v,",
      ms.current_mesh().face_number(), "f",
      "| tex:", ms.current_mesh().texture_number())

# 合并重复顶点
ms.meshing_merge_close_vertices(threshold=PureValue(1e-5))
print("合并后:", ms.current_mesh().vertex_number(), "v,",
      ms.current_mesh().face_number(), "f")

# GH 减面(带纹理保持, 全参数)
ms.meshing_decimation_quadric_edge_collapse_with_texture(
    targetfacenum=1000,
    qualitythr=0.3,
    preserveboundary=True,
    preservenormal=True,
    optimalplacement=True,
    extratcoordw=1.0,
    planarquadric=False)
m = ms.current_mesh()
print("减面后:", m.vertex_number(), "v,", m.face_number(), "f",
      "| tex:", m.texture_number(), "| vtex:", m.has_vertex_tex_coord())

ms.save_current_mesh(OUT)
print("已保存:", OUT, os.path.getsize(OUT), "bytes")

# 列出输出目录的纹理文件
d = os.path.dirname(OUT)
for f in os.listdir(d):
    if not f.endswith('.obj'):
        print("  纹理文件:", f, os.path.getsize(os.path.join(d, f)), "bytes")
