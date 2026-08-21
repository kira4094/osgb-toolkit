"""texture_bake.py v6 — GPU 像素级纹理烘焙(逐 texel ray cast + A 纹理采样)
   仅 GPU 渲染(cupy), 无 CPU fallback
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
# GPU 加速(必需): 纹理烘焙仅支持 GPU(cupy), 无 GPU 时报错
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
        # 场景中心: 用于栅格/射线坐标平移(大坐标下 float32 精度不足会漏采样)
        # 注意: 只平移 GPU 栅格和射线几何, 颜色采样(_batch_face_colors)用绝对坐标不动
        self.scene_center = self.mesh.vertices.mean(axis=0).astype(np.float64)
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

        # 关键: 构建"只含带纹理组"的 ray 网格(ray_verts/ray_faces)
        # _gpu_raycast 用这个网格, 返回的 face_id 与 _batch_face_colors 的
        # group_start/faces_list 索引完全对齐(否则含无纹理三角形时错位→黑块)
        self.ray_verts = np.concatenate(self.verts_list) if self.verts_list else np.zeros((0,3))
        rv = []
        base = 0
        for gi, f in enumerate(self.faces_list):
            rv.append(f + base)
            base += len(self.verts_list[gi])
        self.ray_faces = np.concatenate(rv) if rv else np.zeros((0,3), dtype=np.int64)

        # 3D 栅格加速结构: 三角形按空间分桶, ray 只测命中桶的三角形
        self._build_grid()
        if y_up:
            # 同步 verts_list(用于 _batch_face_colors 的重心/UV计算)
            for gi in range(len(self.verts_list)):
                vv = np.column_stack([self.verts_list[gi][:, 0],
                                      self.verts_list[gi][:, 2],
                                      -self.verts_list[gi][:, 1]])
                self.verts_list[gi] = vv.astype(np.float64)

    def _build_grid(self, cell_div=64):
        """3D 栅格: 把三角形按包围盒分桶
        cell_div: 每个轴分桶数(64^3 桶)
        每个 ray 只测它穿过的桶里的三角形(替代遍历全部 M)
        """
        # 用只含带纹理组的 ray 网格(与 group_start 索引对齐)
        vv = self.ray_verts
        ff = self.ray_faces
        tri = vv[ff].astype(np.float64)  # (M,3,3)
        # 平移到原点附近(大坐标下 float32 精度不足会漏采样)
        tri = tri - self.scene_center
        self._grid_tri = tri.reshape(-1, 9)
        M = len(self._grid_tri)
        # 包围盒(平移后)
        self._grid_min = tri.reshape(-1, 3).min(axis=0)
        self._grid_max = tri.reshape(-1, 3).max(axis=0)
        self._grid_cell = (self._grid_max - self._grid_min) / cell_div
        self._grid_cell[self._grid_cell < 1e-9] = 1e-9
        # 每个三角形落入哪些桶(用三角形 3 顶点的包围盒)
        tv = tri.reshape(M, 3, 3)
        tmin = tv.min(axis=1)  # (M,3)
        tmax = tv.max(axis=1)
        ci_min = np.floor((tmin - self._grid_min) / self._grid_cell).astype(np.int64)
        ci_max = np.floor((tmax - self._grid_min) / self._grid_cell).astype(np.int64)
        ci_min = np.clip(ci_min, 0, cell_div-1)
        ci_max = np.clip(ci_max, 0, cell_div-1)
        # 构建 桶→三角形 映射 (用列表, 后面转 GPU)
        from collections import defaultdict
        cell_tris = defaultdict(list)
        for m in range(M):
            for ix in range(ci_min[m,0], ci_max[m,0]+1):
                for iy in range(ci_min[m,1], ci_max[m,1]+1):
                    for iz in range(ci_min[m,2], ci_max[m,2]+1):
                        key = ix * cell_div*cell_div + iy * cell_div + iz
                        cell_tris[key].append(m)
        # 转成固定数组: cell_start/cell_tri (CSR)
        n_cells = cell_div**3
        cell_start = np.zeros(n_cells+1, dtype=np.int64)
        total = sum(len(v) for v in cell_tris.values())
        cell_tri_arr = np.empty(total, dtype=np.int64)
        acc = 0
        for c in range(n_cells):
            cell_start[c] = acc
            if c in cell_tris:
                cell_tri_arr[acc:acc+len(cell_tris[c])] = cell_tris[c]
                acc += len(cell_tris[c])
        cell_start[n_cells] = total
        self._grid_cell_start = cell_start.astype(np.int64)
        self._grid_cell_tri = cell_tri_arr.astype(np.int32)
        self._grid_div = cell_div
        self._grid_min = self._grid_min.astype(np.float32)
        self._grid_cell = self._grid_cell.astype(np.float32)

    _GPU_KERNEL = r'''
// 栅格加速 ray cast: ray 沿 3D 栅格 DDA 步进, 只测穿过的桶里的三角形
extern "C" __global__ void raycast(
    const float* origins, const float* dirs,
    const float* tri,             // (M,9) 三角形
    const long long* cell_start,  // (n_cells+1)
    const int* cell_tri,          // 桶→三角形
    const float* grid_min, const float* grid_cell,
    int* out_hit, float* out_t, int N, int M, int D)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    float ox = origins[i*3], oy = origins[i*3+1], oz = origins[i*3+2];
    float dx = dirs[i*3], dy = dirs[i*3+1], dz = dirs[i*3+2];
    float best_t = 1e30f;
    int best_m = -1;

    // 栅格 DDA: 从起点开始, 沿方向步进访问穿过的桶
    // 起点格
    float gx = (ox - grid_min[0]) / grid_cell[0];
    float gy = (oy - grid_min[1]) / grid_cell[1];
    float gz = (oz - grid_min[2]) / grid_cell[2];
    int ix = (int)floorf(gx);
    int iy = (int)floorf(gy);
    int iz = (int)floorf(gz);
    // DDA 参数
    float inv_dx = (fabsf(dx) > 1e-12f) ? 1.0f/dx : 1e30f;
    float inv_dy = (fabsf(dy) > 1e-12f) ? 1.0f/dy : 1e30f;
    float inv_dz = (fabsf(dz) > 1e-12f) ? 1.0f/dz : 1e30f;
    int step_x = (dx > 0) ? 1 : -1;
    int step_y = (dy > 0) ? 1 : -1;
    int step_z = (dz > 0) ? 1 : -1;
    float tmax_x = (dx > 0) ? ((ix+1 - gx) * inv_dx) : ((gx - ix) * inv_dx);
    float tmax_y = (dy > 0) ? ((iy+1 - gy) * inv_dy) : ((gy - iy) * inv_dy);
    float tmax_z = (dz > 0) ? ((iz+1 - gz) * inv_dz) : ((gz - iz) * inv_dz);
    float tdelta_x = fabsf(inv_dx);
    float tdelta_y = fabsf(inv_dy);
    float tdelta_z = fabsf(inv_dz);

    // 步进上限(ray 最长距离 + 安全余量)
    float ray_len = 1e6f;
    float t = 0.0f;
    int guard = 0;
    int max_steps = D * D * 2;  // 增大: 高分辨率密集采样射线可能步进很多桶(远射线/平行地面)才命中
    while (t < ray_len && guard < max_steps) {
        guard++;
        // 当前桶
        if (ix >= 0 && ix < D && iy >= 0 && iy < D && iz >= 0 && iz < D) {
            int cell = ix*D*D + iy*D + iz;
            long long s = cell_start[cell], e = cell_start[cell+1];
            for (long long k = s; k < e; k++) {
                int m = cell_tri[k];
                const float* tp = &tri[m*9];
                float ax = tp[0], ay = tp[1], az = tp[2];
                float bx = tp[3], by = tp[4], bz = tp[5];
                float cx = tp[6], cy = tp[7], cz = tp[8];
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
                float tt = (e2x*qx + e2y*qy + e2z*qz) * inv;
                if (tt > 1e-4f && tt < best_t) { best_t = tt; best_m = m; }
            }
        }
        // DDA 步进到下一个桶
        if (tmax_x < tmax_y && tmax_x < tmax_z) { t = tmax_x; tmax_x += tdelta_x; ix += step_x; }
        else if (tmax_y < tmax_z) { t = tmax_y; tmax_y += tdelta_y; iy += step_y; }
        else { t = tmax_z; tmax_z += tdelta_z; iz += step_z; }
    }
    out_hit[i] = best_m;
    out_t[i] = (best_m >= 0) ? best_t : 1e30f;
}
'''

    def _gpu_raycast(self, origins, dirs):
        """GPU 批量 ray cast (3D 栅格加速): 返回命中面索引数组"""
        N = len(origins)
        if N == 0: return np.full(0, -1, dtype=np.int64)
        tri_flat = self._grid_tri.astype(np.float32)  # (M,9) 已平移
        M = len(tri_flat)
        # rays 起点也平移到同一坐标系
        origins = np.asarray(origins, dtype=np.float64) - self.scene_center
        o_g = cp.asarray(np.ascontiguousarray(origins, dtype=np.float32).ravel())
        d_g = cp.asarray(np.ascontiguousarray(dirs, dtype=np.float32).ravel())
        t_g = cp.asarray(np.ascontiguousarray(tri_flat).ravel())
        cs_g = cp.asarray(self._grid_cell_start)     # (n_cells+1) int64
        ct_g = cp.asarray(self._grid_cell_tri)       # (total) int32
        gm_g = cp.asarray(self._grid_min)            # (3) float32
        gc_g = cp.asarray(self._grid_cell)           # (3) float32
        hit_g = cp.full(N, -1, dtype=cp.int32)
        t_out_g = cp.full(N, 1e30, dtype=cp.float32)
        D = self._grid_div
        k = cp.RawKernel(self._GPU_KERNEL, 'raycast')
        block = 256
        BS = 65536
        for s in range(0, N, BS):
            e = min(s+BS, N)
            n = e - s
            grid = (n + block - 1) // block
            k((grid,), (block,),
              (o_g[s*3:e*3], d_g[s*3:e*3], t_g, cs_g, ct_g, gm_g, gc_g,
               hit_g[s:e], t_out_g[s:e], n, M, D))
        cp.cuda.Stream.null.synchronize()
        return hit_g.get().astype(np.int64)

    def sample_points_gpu(self, points, normals=None, ray_offset=1e-4, bilinear=True):
        """GPU 像素级采样: points (N,3) → colors (N,3)
        沿法线双向 + 固定上下(±Y)兜底 ray
        开放表面大平面: 法线双向可能都打空(悬空平面下方无遮挡),
        加固定 +Y/-Y 兜底, 覆盖地面朝上等水平大平面"""
        N = len(points)
        colors = np.zeros((N, 3), dtype=np.uint8)
        if N == 0: return colors
        try:
            if normals is None:
                normals = np.tile([0, 0, 1], (N, 1))
            normals = np.asarray(normals, dtype=np.float32)
            off = float(ray_offset)
            # 四方向: 沿法线正向/反向 + 固定 +Y/-Y
            dirs = np.vstack([normals, -normals,
                              np.tile([0,1,0],(N,1)).astype(np.float32),
                              np.tile([0,-1,0],(N,1)).astype(np.float32)])
            origins = np.vstack([points + normals*off, points - normals*off,
                                 points + np.array([0,off,0]), points + np.array([0,-off,0])])
            hit = self._gpu_raycast(origins, dirs)
            fwd = hit[:N].astype(np.int64)
            bwd = hit[N:2*N].astype(np.int64)
            up = hit[2*N:3*N].astype(np.int64)
            dn = hit[3*N:4*N].astype(np.int64)
            # 优先级: 反向(朝表面内/下) > 正向 > 下 > 上
            # 对开放表面多层模型(树/地面交错): 反向优先, 避免地面采样到上方树的颜色
            face_ids = np.where(bwd >= 0, bwd, fwd)
            face_ids = np.where(face_ids >= 0, face_ids, dn)
            face_ids = np.where(face_ids >= 0, face_ids, up)
            valid = face_ids >= 0
            if valid.any():
                cols = self._batch_face_colors(face_ids[valid], points[valid], bilinear=bilinear)
                colors[valid] = cols
        except Exception as e:
            raise RuntimeError(f"GPU 纹理采样失败: {e}") from e
        return colors

    def _batch_face_colors(self, face_ids, points, bilinear=True):
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
            # 越界点: 最近顶点 (向量化, 消除 Python 循环)
            if (~inside).any():
                d0 = np.linalg.norm(proj[~inside] - v0[~inside], axis=1)
                d1 = np.linalg.norm(proj[~inside] - v1[~inside], axis=1)
                d2 = np.linalg.norm(proj[~inside] - v2[~inside], axis=1)
                nearest = np.argmin(np.stack([d0, d1, d2], axis=1), axis=1)
                neg_uv = np.stack([uv0[~inside], uv1[~inside], uv2[~inside]], axis=1)
                s_neg = neg_uv[np.arange(len(nearest)), nearest]
                s[~inside] = s_neg
            # UV → 像素 (双线性插值, 消除锯齿)
            W, H = img.size
            fx = np.clip(s[:, 0] * (W - 1), 0, W - 1)
            fy = np.clip((1 - s[:, 1]) * (H - 1), 0, H - 1)  # V 翻转
            arr = np.array(img, dtype=np.float32)
            if bilinear:
                x0 = np.floor(fx).astype(int); y0 = np.floor(fy).astype(int)
                x1 = np.minimum(x0 + 1, W - 1); y1 = np.minimum(y0 + 1, H - 1)
                wx = fx - x0; wy = fy - y0
                c00 = arr[y0, x0]; c10 = arr[y0, x1]; c01 = arr[y1, x0]; c11 = arr[y1, x1]
                top = c00 * (1 - wx)[:, None] + c10 * wx[:, None]
                bot = c01 * (1 - wx)[:, None] + c11 * wx[:, None]
                out[mask] = (top * (1 - wy)[:, None] + bot * wy[:, None]).astype(np.uint8)
            else:
                pxs = fx.astype(int); pys = fy.astype(int)
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
                # 容错: f v//vn (无UV) 或 f v 的面跳过(烘焙需要UV)
                if len(idx[0]) < 2 or len(idx[1]) < 2 or len(idx[2]) < 2:
                    continue
                if idx[0][1] == '' or idx[1][1] == '' or idx[2][1] == '':
                    continue
                f.append((int(idx[0][0])-1, int(idx[0][1])-1,
                          int(idx[1][0])-1, int(idx[1][1])-1,
                          int(idx[2][0])-1, int(idx[2][1])-1))
    return np.array(v), np.array(vt), np.array(f)


def bake(src, simp_obj, out_png, resolution=1024, verbose=True, dilate=4, sample_step=2, bilinear=True, ray_offset=1e-4):
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
    if not _HAS_GPU:
        raise RuntimeError("GPU (cupy) 不可用, 纹理烘焙需要 GPU 渲染")
    import time as _t
    colors = src.sample_points_gpu(pts, np.array(norm_list), ray_offset=ray_offset, bilinear=bilinear)
    if verbose: print(f"  [采样] {_t.time()-_t_stage:.1f}s")
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
    ap.add_argument('--sample-step', type=int, default=2, help='采样跳步(1=全分辨率)')
    ap.add_argument('--bilinear', action='store_true', default=True, help='双线性采样')
    ap.add_argument('--ray-offset', type=float, default=1e-4, help='ray 偏移避免自相交')
    ap.add_argument('--dilate', type=int, default=4, help='UV边缘扩散像素')
    args = ap.parse_args()
    src = BakeSource(args.source_obj)
    print(f"A: {len(src.mesh.vertices)}v, {len(src.tex_list)} 纹理组")
    bake(src, args.simp_obj, args.out_png, args.resolution, dilate=args.dilate, sample_step=args.sample_step, bilinear=args.bilinear, ray_offset=args.ray_offset)
