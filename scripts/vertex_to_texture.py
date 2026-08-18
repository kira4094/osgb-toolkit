"""vertex_to_texture.py — B 顶点色 → UV 图集
输入: B 简化模型(带 UV) + B 顶点色(pymeshlab 转移后)
输出: 图集 PNG
"""
import sys, os
import numpy as np
from PIL import Image

def load_obj_with_color(obj_path):
    """读 OBJ 的 v/vt/f(vi/vti 分离)"""
    v, vt, f = [], [], []
    for line in open(obj_path, encoding='utf-8', errors='replace'):
        p = line.split()
        if not p: continue
        if p[0]=='v': v.append([float(p[1]),float(p[2]),float(p[3])])
        elif p[0]=='vt': vt.append([float(p[1]),float(p[2])])
        elif p[0]=='f':
            idx = [x.split('/') for x in p[1:]]
            if len(idx)>=3:
                f.append([int(idx[0][0])-1,int(idx[0][1])-1,
                          int(idx[1][0])-1,int(idx[1][1])-1,
                          int(idx[2][0])-1,int(idx[2][1])-1])
    return np.array(v), np.array(vt), np.array(f)

def rasterize(obj_path, vertex_colors, out_png, resolution=2048, dilate=2):
    """顶点色 → UV 图集(重心插值 + 边缘膨胀防缝隙)"""
    v, vt, f = load_obj_with_color(obj_path)
    print(f"网格: {len(v)}v {len(f)}f, UV {len(vt)}, 顶点色 {vertex_colors.shape}")

    img = Image.new('RGB', (resolution, resolution), (0,0,0))
    px = img.load()
    tri_v = np.array([[f[i][0],f[i][2],f[i][4]] for i in range(len(f))])
    tri_uv = np.array([[f[i][1],f[i][3],f[i][5]] for i in range(len(f))])
    colors = np.clip(vertex_colors[:, :3], 0, 1) * 255

    count = 0
    for i in range(len(f)):
        t0,t1,t2 = tri_uv[i]
        u0,u1,u2 = vt[t0],vt[t1],vt[t2]
        umin = max(0, int(min(u0[0],u1[0],u2[0])*resolution))
        umax = min(resolution-1, int(max(u0[0],u1[0],u2[0])*resolution))
        vmin = max(0, int(min(u0[1],u1[1],u2[1])*resolution))
        vmax = min(resolution-1, int(max(u0[1],u1[1],u2[1])*resolution))
        if umax<umin or vmax<vmin: continue
        A = np.array([[u1[0]-u0[0],u2[0]-u0[0]],[u1[1]-u0[1],u2[1]-u0[1]]])
        det = A[0,0]*A[1,1]-A[0,1]*A[1,0]
        if abs(det)<1e-12: continue
        Ainv = np.linalg.inv(A)
        # 顶点颜色
        c0,c1,c2 = colors[tri_v[i][0]],colors[tri_v[i][1]],colors[tri_v[i][2]]
        for yy in range(vmin,vmax+1):
            for xx in range(umin,umax+1):
                su = (xx+0.5)/resolution; sv = (yy+0.5)/resolution
                d = np.array([su-u0[0],sv-u0[1]])
                lam = Ainv@d
                if lam[0]<-1e-9 or lam[1]<-1e-9 or lam[0]+lam[1]>1+1e-9: continue
                w0 = 1-lam[0]-lam[1]
                col = (w0*c0 + lam[0]*c1 + lam[1]*c2).astype(int)
                px[xx,yy] = tuple(col)
                count += 1
    print(f"填充像素: {count} ({count/(resolution*resolution):.1%})")
    img.save(out_png)
    print(f"图集: {out_png}")
    return img

if __name__ == '__main__':
    obj = sys.argv[1]
    colors_npy = sys.argv[2]
    out = sys.argv[3]
    res = int(sys.argv[4]) if len(sys.argv)>4 else 2048
    vc = np.load(colors_npy)
    rasterize(obj, vc, out, res)
