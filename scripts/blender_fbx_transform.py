import bpy
import math
import sys
import os

# 参数: input.obj, output.fbx, scale, rotX_deg
in_obj = sys.argv[sys.argv.index('--') + 1]
out_fbx = sys.argv[sys.argv.index('--') + 2]
scale = float(sys.argv[sys.argv.index('--') + 3])
rotx = float(sys.argv[sys.argv.index('--') + 4])

# 清空场景
bpy.ops.wm.read_factory_settings(use_empty=True)

# 导入 OBJ
bpy.ops.wm.obj_import(filepath=in_obj)

# 找到导入的对象
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    print("ERROR: 没有导入网格")
    sys.exit(1)

# 合并所有网格到一个根节点
if len(objs) > 1:
    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    root = bpy.context.active_object
else:
    root = objs[0]

# 在根节点上设 transform (scale + rotateX)
root.scale = (scale, scale, scale)
root.rotation_euler = (math.radians(rotx), 0, 0)
# 保持 transform 在节点层 (不应用)
bpy.ops.object.select_all(action='DESELECT')
root.select_set(True)
bpy.context.view_layer.objects.active = root

# 导出 FBX (保留节点 transform)
bpy.ops.export_scene.fbx(
    filepath=out_fbx,
    use_selection=False,
    object_types={'MESH'},
    apply_scale_options='FBX_SCALE_NONE',   # 不烘焙 scale
    bake_space_transform=False,              # 不烘焙旋转
    apply_unit_scale=False,                  # 不应用单位缩放
    axis_forward='-Z', axis_up='Y',          # FBX 标准 Y-up
)
print(f"OK: {out_fbx}")
