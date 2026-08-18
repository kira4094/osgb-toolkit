"""texture_bake.py v5 — 真正的像素级纹理烘焙(逐 texel ray cast + A 纹理采样)
和 Maya TransferMap / Substance Painter 相同原理:
  1. B 图集每个 texel → 重心反算 3D 点 + 法线
  2. 沿 ±Z 双向 ray cast 到 A(命中 66%+)
  3. 命中面 → 重心 → A 的 UV → A 纹理采样(像素级)
  4. 写图集
关键: intersects_first 批量(0.03s/1000 ray), 支持几十万 texel
"""
import sys, os, time
import numpy as np
import trimesh
from PIL import Image, ImageFilter
# 自动设置 CUDA_PATH(指向 pip 装的 CUDA runtime, 避免手动设环境变量)
if not os.environ.get('CUDA_PATH'):
    _cp = r'C:\Users\kiray\AppData\Local\Programs\Python\Python314\Lib\site-packages\nvidia\cuda_runtime'
    if os.path.exists(os.path.join(_cp, 'bin', 'cudart64_12.dll')):
        os.environ['CUDA_PATH'] = _cp
from scipy.ndimage import binary_dilation
# GPU 加速(可选): 无 cupy 或 GPU 时自动 fallback CPU
try:
    import cupy as cp
    _HAS_GPU = True
except Exception:
    _HAS_GPU = False


class BakeSource:
    """A 模型: trimesh ray + 组 UV/纹理采样"""

    def __init__(self, obj_path, y_up=False):
        self.y_up = y_up
        self.mesh = trimesh.load(obj_path, process=False, force='mesh')
        if y_up:
            v = np.column_stack([self.mesh.vertices[:, 0],
                                 self.mesh.vertices[:, 2],
                                 -self.mesh.vertices[:, 1]])
            self.mesh.vertices = v.astype(np.float64)
        scene = trimesh.load(obj_path, process=False)
        geoms = list(scene.geometry.items()) if hasattr(scene, 'geometry') else [('m', scene)]
        self.verts_list, self.faces_list, self.uvs_list, self.tex_list = [], [], [], []
        self.face_tex_id = []
        self.all_verts, self.all_faces = [], []
        for gi, (name, g) in enumerate(geoms):
            if not hasattr(g, 'faces') or len(g.faces) == 0: continue
            v = np.asarray(g.vertices, dtype=np.float64)
            f = np.asarray(g.faces, dtype=np.int64)
            uv = None; img = None
            if g.visual.kind == 'texture':
                uv = np.asarray(g.visual.uv, dtype=np.float64)
                mat = g.visual.material
                if hasattr(mat, 'image') and mat.image:
                    img = mat.image.convert('RGB')
            if uv is None or img is None: continue
            base = len(self.all_verts)
            self.all_verts.append(v); self.all_faces.append(f + base)
            self.face_tex_id.extend([gi] * len(f))
            self.verts_list.append(v); self.faces_list.append(f)
            self.uvs_list.append(uv); self.tex_list.append(img)
        # 组起点(快速定位)
        self.group_start = []
        acc = 0
        for fl in self.faces_list:
            self.group_start.append(acc); acc += len(fl)
        self.face_tex_id = np.array(self.face_tex_id)
        if y_up:
            # 同步 verts_list(用于 _batch_face_colors 的重心/UV计算)
            for gi in range(len(self.verts_list)):
                vv = np.column_stack([self.verts_list[gi][:, 0],
                                      self.verts_list[gi][:, 2],
                                      -self.verts_list[gi][:, 1]])
                self.verts_list[gi] = vv.astype(np.float64)

    def sample_points(self, points):
        """向量化: points (N,3) → colors (N,3) uint8
        ±Z 双向 ray, 命中 → 按组批量纹理采样"""
        N = len(points)
        colors = np.zeros((N, 3), dtype=np.uint8)
        if N == 0: return colors
        # 分段单向 ray: +Z 先, 未命中再 -Z(比一次双向快 10 倍)
        face_ids = np.full(N, -1, dtype=np.int64)
        if getattr(self, 'y_up', False):
            zplus = np.tile([0, 1, 0], (N, 1))  # Y-up: 沿 +Y
        else:
            zplus = np.tile([0, 0, 1], (N, 1))  # Z-up: 沿 +Z
        idx_p = self.mesh.ray.intersects_first(points, zplus)
        got = idx_p >= 0
        if got.any():
            face_ids[got] = idx_p[got]
        if not got.all():
            rem = ~got
            idx_m = self.mesh.ray.intersects_first(points[rem], -zplus[rem])
            face_ids[rem] = np.where(idx_m >= 0, idx_m, -1)
        valid = face_ids >= 0
        if not valid.any():
            return colors
        cols = self._batch_face_colors(face_ids[valid], points[valid])
        colors[valid] = cols
        return colors

    _GPU_KERNEL = r'''
extern "C" __global__ void raycast(
    const float* origins, const float* dirs, const float* tri,
    int* out_hit, float* out_t, int N, int M)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    float ox = origins[i*3], oy = origins[i*3+1], oz = origins[i*3+2];
    float dx = dirs[i*3], dy = dirs[i*3+1], dz = dirs[i*3+2];
    float best_t = 1e30f;
    int best_m = -1;
    for (int m = 0; m < M; m++) {
        float ax = tri[m*9], ay = tri[m*9+1], az = tri[m*9+2];
        float bx = tri[m*9+3], by = tri[m*9+4], bz = tri[m*9+5];
        float cx = tri[m*9+6], cy = tri[m*9+7], cz = tri[m*9+8];
        float e1x = bx-ax, e1y = by-ay, e1z = bz-az;
        float e2x = cx-ax, e2y = cy-ay, e2z = cz-az;
        float px = dy*e2z - dz*e2y, py = dz*e2x - dx*e2z, pz = dx*e2y - dy*e2x;
        float det = e1x*px + e1y*py + e1z*pz;
        if (fabsf(det) < 1e-12f) continue;
        float inv = 1.0f/det;
        float tx = ox-ax, ty = oy-ay, tz = oz-az;
        float u = (tx*px + ty*py + tz*pz) * inv;
        if (u < 0.0f || u > 1.0f) continue;
        float qx = ty*e1z - tz*e1y, qy = tz*e1x - tx*e1z, qz = tx*e1y - ty*e1x;
        float v = (dx*qx + dy*qy + dz*qz) * inv;
        if (v < 0.0f || u+v > 1.0f) continue;
        float t = (e2x*qx + e2y*qy + e2z*qz) * inv;
        if (t > 1e-4f && t < best_t) { best_t = t; best_m = m; }
    }
    out_hit[i] = best_m;
    out_t[i] = (best_m >= 0) ? best_t : 1e30f;
}
'''

    def _gpu_raycast(self, origins, dirs):
        """GPU 批量 ray cast: 返回命中面索引数组"""
        N = len(origins)
        if N == 0: return np.full(0, -1, dtype=np.int64)
        tri = self.mesh.triangles.astype(np.float32)  # (M,3,3) → (M,9)
        tri_flat = tri.reshape(-1, 9)
        M = len(tri_flat)
        o_g = cp.asarray(np.ascontiguousarray(origins, dtype=np.float32).ravel())
        d_g = cp.asarray(np.ascontiguousarray(dirs, dtype=np.float32).ravel())
        t_g = cp.asarray(np.ascontiguousarray(tri_flat).ravel())
        hit_g = cp.full(N, -1, dtype=cp.int32)
        t_out_g = cp.full(N, 1e30, dtype=cp.float32)
        k = cp.RawKernel(self._GPU_KERNEL, 'raycast')
        block = 256
        BS = 65536
        for s in range(0, N, BS):
            e = min(s+BS, N)
            n = e - s
            grid = (n + block - 1) // block
            k((grid,), (block,), (o_g[s*3:e*3], d_g[s*3:e*3], t_g, hit_g[s:e], t_out_g[s:e], n, M))
        cp.cuda.Stream.null.synchronize()
        return hit_g.get().astype(np.int64)

    def sample_points_gpu(self, points, normals=None):
        """GPU 像素级采样: points (N,3) → colors (N,3)
        沿法线双向 ray(Maya 方式, 消除多方向条纹)"""
        N = len(points)
        colors = np.zeros((N, 3), dtype=np.uint8)
        if N == 0 or not _HAS_GPU: return colors
        try:
            if normals is None:
                normals = np.tile([0, 0, 1], (N, 1))
            normals = np.asarray(normals, dtype=np.float32)
            # 沿法线双向(正向优先, 反向兜底)
            origins = np.vstack([points, points])
            dirs = np.vstack([normals, -normals])
            hit = self._gpu_raycast(origins, dirs)
            fwd = hit[:N].astype(np.int64)
            bwd = hit[N:].astype(np.int64)
            face_ids = np.where(fwd >= 0, fwd, bwd)
            valid = face_ids >= 0
            if valid.any():
                cols = self._batch_face_colors(face_ids[valid], points[valid])
                colors[valid] = cols
        except Exception as e:
            print(f"GPU 失败, fallback CPU: {e}")
        return colors

    def _batch_face_colors(self, face_ids, points):
        """批量: 多个命中面+点 → 按组重心 → UV → 纹理采样(向量化)"""
        M = len(face_ids)
        out = np.zeros((M, 3), dtype=np.uint8)
        # 按组分组处理
        for gi in range(len(self.faces_list)):
            start = self.group_start[gi]
            mask = (face_ids >= start) & (face_ids < start + len(self.faces_list[gi]))
            if mask.sum() == 0: continue
            local_f = face_ids[mask] - start
            cp = points[mask]
            f_local = self.faces_list[gi][local_f]
            uv = self.uvs_list[gi]; img = self.tex_list[gi]
            v0 = self.verts_list[gi][f_local[:, 0]]
            v1 = self.verts_list[gi][f_local[:, 1]]
            v2 = self.verts_list[gi][f_local[:, 2]]
            # 投影到面平面
            n = np.cross(v1 - v0, v2 - v0)
            nlen = np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
            n = n / nlen
            proj = cp - n * ((cp - v0) * n).sum(axis=1, keepdims=True)
            # 重心坐标(批量)
            tris = np.stack([v0, v1, v2], axis=1)
            try:
                bary = trimesh.triangles.points_to_barycentric(tris, proj)
            except Exception:
                continue
            u = bary[:, 0]; v = bary[:, 1]; w = bary[:, 2]
            uv0 = uv[f_local[:, 0]]; uv1 = uv[f_local[:, 1]]; uv2 = uv[f_local[:, 2]]
            # 重心越界 → 最近顶点 UV
            inside = (u >= -0.05) & (v >= -0.05) & (w >= -0.05)
            s = np.zeros((len(u), 2))
            s[inside] = (u[inside, None]*uv0[inside] + v[inside, None]*uv1[inside] + w[inside, None]*uv2[inside])
            # 越界点: 最近顶点
            if (~inside).any():
                d0 = np.linalg.norm(proj[~inside] - v0[~inside], axis=1)
                d1 = np.linalg.norm(proj[~inside] - v1[~inside], axis=1)
                d2 = np.linalg.norm(proj[~inside] - v2[~inside], axis=1)
                nearest = np.argmin(np.stack([d0, d1, d2], axis=1), axis=1)
                s_neg = s[~inside].copy()
                for k, ni in enumerate(nearest):
                    if ni == 0: s_neg[k] = uv0[~inside][k]
                    elif ni == 1: s_neg[k] = uv1[~inside][k]
                    else: s_neg[k] = uv2[~inside][k]
                s[~inside] = s_neg
            # UV → 像素
            W, H = img.size
            pxs = np.clip((s[:, 0] * (W - 1)).astype(int), 0, W-1)
            pys = np.clip(((1 - s[:, 1]) * (H - 1)).astype(int), 0, H-1)  # V 翻转: OBJ UV V=0底部 → 图像 V=0顶部
            arr = np.array(img)
            out[mask] = arr[pys, pxs]
        return out


def load_simplified_obj(obj_path):
    v, vt, f = [], [], []
    for line in open(obj_path, encoding='utf-8', errors='replace'):
        p = line.split()
        if not p: continue
        if p[0] == 'v': v.append([float(p[1]), float(p[2]), float(p[3])])
        elif p[0] == 'vt': vt.append([float(p[1]), float(p[2])])
        elif p[0] == 'f':
            idx = [x.split('/') for x in p[1:]]
            if len(idx) >= 3:
                f.append((int(idx[0][0])-1, int(idx[0][1])-1,
                          int(idx[1][0])-1, int(idx[1][1])-1,
                          int(idx[2][0])-1, int(idx[2][1])-1))
    return np.array(v), np.array(vt), np.array(f)


def bake(src, simp_obj, out_png, resolution=1024, verbose=True, dilate=4, sample_step=2):
    v, vt, f = load_simplified_obj(simp_obj)
    if verbose:
        print(f"B: {len(v)}v {len(f)}f, UV {len(vt)}, 图集 {resolution}²")
    img = Image.new('RGB', (resolution, resolution), (0, 0, 0))
    px = img.load()
    tri_v = np.array([[f[i][0], f[i][2], f[i][4]] for i in range(len(f))])
    tri_uv = np.array([[f[i][1], f[i][3], f[i][5]] for i in range(len(f))])
    # 预计算 B 面法线(每个 UV 三角形的 texel 共用面法线)
    _fv0 = v[tri_v[:, 0]]; _fv1 = v[tri_v[:, 1]]; _fv2 = v[tri_v[:, 2]]
    face_normals = np.cross(_fv1 - _fv0, _fv2 - _fv0)
    fn_len = np.linalg.norm(face_normals, axis=1, keepdims=True) + 1e-12
    face_normals = face_normals / fn_len
    # 向量化收集 texel 的 3D 点 + 法线(逐三角形 numpy 批量)
    pts_list, pix_list, norm_list = [], [], []
    for i in range(len(f)):
        t0, t1, t2 = tri_uv[i]
        u0, u1, u2 = vt[t0], vt[t1], vt[t2]
        umin = max(0, int(min(u0[0], u1[0], u2[0]) * resolution))
        umax = min(resolution-1, int(max(u0[0], u1[0], u2[0]) * resolution))
        vmin = max(0, int(min(u0[1], u1[1], u2[1]) * resolution))
        vmax = min(resolution-1, int(max(u0[1], u1[1], u2[1]) * resolution))
        if umax < umin or vmax < vmin: continue
        A2 = np.array([[u1[0]-u0[0], u2[0]-u0[0]], [u1[1]-u0[1], u2[1]-u0[1]]])
        det = A2[0,0]*A2[1,1] - A2[0,1]*A2[1,0]
        if abs(det) < 1e-12: continue
        Ainv = np.linalg.inv(A2)
        p0, p1, p2 = v[tri_v[i][0]], v[tri_v[i][1]], v[tri_v[i][2]]
        # 批量生成包围盒内像素坐标(跳步)
        xs = np.arange(umin, umax+1, sample_step)
        ys = np.arange(vmin, vmax+1, sample_step)
        if len(xs) == 0 or len(ys) == 0: continue
        gx, gy = np.meshgrid(xs, ys)
        gx = gx.ravel(); gy = gy.ravel()
        su = (gx + 0.5) / resolution; sv = (gy + 0.5) / resolution
        d = np.stack([su - u0[0], sv - u0[1]], axis=1)
        lam = d @ Ainv.T
        inside = (lam[:, 0] >= -1e-9) & (lam[:, 1] >= -1e-9) & (lam[:, 0] + lam[:, 1] <= 1 + 1e-9)
        if not inside.any(): continue
        lam_in = lam[inside]
        w0 = 1 - lam_in[:, 0] - lam_in[:, 1]
        P = w0[:, None]*p0 + lam_in[:, 0:1]*p1 + lam_in[:, 1:2]*p2
        gx_in = gx[inside]; gy_in = gy[inside]
        _fn = face_normals[i]
        for k in range(len(P)):
            pts_list.append(P[k]); pix_list.append((gx_in[k], gy_in[k])); norm_list.append(_fn)
    if not pts_list:
        print("无 texel"); return img
    pts = np.array(pts_list)
    if verbose:
        print(f"texel 数: {len(pts)} (跳步 {sample_step})")
    _t_stage = time.time()
    if _HAS_GPU:
        import time as _t
        colors = src.sample_points_gpu(pts, np.array(norm_list))
        if verbose: print(f"  [采样] {_t.time()-_t_stage:.1f}s")
        if (colors.sum(axis=1) > 0).sum() == 0:
            colors = src.sample_points(pts)  # fallback
    else:
        colors = src.sample_points(pts)
    nhit = (colors.sum(axis=1) > 0).sum()
    if verbose:
        print(f"采样命中: {nhit}/{len(pts)} ({nhit/len(pts):.1%})")
    # 填色: 采样点颜色
    # 向量化填充: numpy 数组一次性写入(替代 210万次 Python 循环)
    img_arr = np.zeros((resolution, resolution, 3), dtype=np.uint8)
    if pix_list:
        pix_arr = np.array(pix_list, dtype=np.int64)  # (N,2) xx,yy
        img_arr[pix_arr[:, 1], pix_arr[:, 0]] = colors
    img = Image.fromarray(img_arr)
    # 未采样像素用最近采样点颜色填充(避免跳步空隙)
    if sample_step > 1:
        a = np.array(img.convert('RGB'))
        mask = (a.sum(axis=2) > 30)
        if mask.any() and not mask.all():
            from scipy.ndimage import distance_transform_edt
            dist, (iy, ix) = distance_transform_edt(~mask, return_indices=True)
            a[~mask] = a[iy[~mask], ix[~mask]]
            img = Image.fromarray(a)
    # UV 边缘扩散: 只对 UV 岛边缘向外扩散, 内部纹理保持清晰
    # (消除 UV 岛之间的黑边/接缝, 类似 Substance 的 dilation)
    if dilate > 0:
        a = np.array(img.convert('RGB'))
        mask = (a.sum(axis=2) > 30)  # 非黑 = UV 岛
        if mask.any() and not mask.all():
            # 迭代扩张 mask, 每次只填新扩展的边缘环
            cur = mask.copy()
            for _ in range(dilate):
                expanded = binary_dilation(cur)
                new_edge = expanded & ~cur  # 新增的边缘像素
                if not new_edge.any():
                    break
                # 新边缘像素用相邻的非黑像素颜色填充(从原图找最近)
                from scipy.ndimage import distance_transform_edt
                # 对每个新边缘像素, 找最近的非黑像素
                dist, (iy, ix) = distance_transform_edt(~mask, return_indices=True)
                new_a = a.copy()
                ny, nx = np.nonzero(new_edge)
                new_a[ny, nx] = a[iy[ny, nx], ix[ny, nx]]
                a = new_a
                cur = expanded
            img = Image.fromarray(a)
        if verbose:
            print(f"UV 边缘扩散: {dilate} px (仅边缘)")
    img.save(out_png)
    print(f"图集: {out_png}")
    return img


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='像素级纹理烘焙 v5: ±Z ray + 纹理采样')
    ap.add_argument('source_obj')
    ap.add_argument('simp_obj')
    ap.add_argument('out_png')
    ap.add_argument('--resolution', type=int, default=1024)
    ap.add_argument('--dilate', type=int, default=4, help='UV边缘扩散像素')
    args = ap.parse_args()
    src = BakeSource(args.source_obj)
    print(f"A: {len(src.mesh.vertices)}v, {len(src.tex_list)} 纹理组")
    bake(src, args.simp_obj, args.out_png, args.resolution, dilate=args.dilate)
