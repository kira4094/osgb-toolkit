#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osgb_gui.py — OSGB 合并 + GH 简化 + 纹理烘焙 + FBX 导出 图形界面
=============================================================
基于 customtkinter, 功能与 osgb_simplifier.py 完全对应
"""
import os
import sys
import threading
import traceback

import customtkinter as ctk
from tkinter import filedialog, messagebox

# 确保能 import osgb_simplifier
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import osgb_simplifier as osgb

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# 设置 OSG 环境(供子进程 osgb_named/osgb_full 加载 DLL)
_osg_root = os.environ.get('OSGROOT')
if not _osg_root:
    _candidates = [
        r'E:\Resource\StadiumZG\osgb-toolkit\thirdparty\OpenSceneGraph',
    ]
    for _c in _candidates:
        if os.path.exists(os.path.join(_c, 'bin', 'osgconv.exe')):
            _osg_root = _c
            break
if _osg_root:
    _osg_bin = os.path.join(_osg_root, 'bin')
    os.environ['OSGROOT'] = _osg_root
    os.environ.setdefault('OSG_LIBRARY_PATH', _osg_bin)
    _path = os.environ.get('PATH', '')
    if _osg_bin not in _path:
        os.environ['PATH'] = _osg_bin + os.pathsep + _path


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OSGB 网格简化工具")
        self.geometry("760x860")
        self.minsize(700, 780)

        # ---------- 顶栏 ----------
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(header, text="OSGB 网格合并 · GH 简化 · 纹理烘焙",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="Garland-Heckbert / pymeshlab",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(side="right")

        # ---------- 主内容区 ----------
        self.content = ctk.CTkScrollableFrame(self)
        self.content.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_input_section()
        self._build_lod_section()
        self._build_simplify_section()
        self._build_bake_section()
        self._build_output_section()
        self._build_action_bar()
        self._build_log_section()

        # 默认值
        self.set_defaults()

    # ========== 输入区 ==========
    def _build_input_section(self):
        frame = self._section("📂 输入")
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="OSGB 目录:").grid(row=0, column=0, sticky="w", pady=3)
        self.input_path = ctk.CTkEntry(frame, placeholder_text="含 Data/ 的工程目录, 或单个瓦片目录")
        self.input_path.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_input).grid(row=0, column=2)

    # ========== LOD 区 ==========
    def _build_lod_section(self):
        frame = self._section("🗂 LOD 层级(选择减面输入对象)")
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="LOD 层级:").grid(row=0, column=0, sticky="w", pady=3)
        self.lod = ctk.CTkOptionMenu(frame, values=["root", "L16", "L17", "L18", "L19", "L20", "L21", "L22", "all"])
        self.lod.grid(row=0, column=1, sticky="ew", padx=6)

        ctk.CTkLabel(frame, text="顶点融合阈值:").grid(row=1, column=0, sticky="w", pady=3)
        self.merge_ratio = ctk.CTkEntry(frame, width=120, placeholder_text="0.022")
        self.merge_ratio.grid(row=1, column=1, sticky="w", padx=6)
        ctk.CTkLabel(frame, text="(合并重复顶点距离; 默认0.022对齐OPEditor)",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(row=1, column=2, sticky="w")

        ctk.CTkLabel(frame, text="边界缝合阈值:").grid(row=2, column=0, sticky="w", pady=3)
        self.stitch_ratio = ctk.CTkEntry(frame, width=120, placeholder_text="0.2")
        self.stitch_ratio.grid(row=2, column=1, sticky="w", padx=6)
        ctk.CTkLabel(frame, text="(消除瓦片接缝点距离; 默认0.2, 越大缝合越多)",
                     text_color="gray", font=ctk.CTkFont(size=11)).grid(row=2, column=2, sticky="w")

    # ========== 简化区 ==========
    def _build_simplify_section(self):
        frame = self._section("✂️ 网格简化 (Garland-Heckbert / QEM)")
        frame.grid_columnconfigure(1, weight=1)

        # 目标面数: 两种输入方式(绝对值 / 百分比)
        ctk.CTkLabel(frame, text="目标面数:").grid(row=0, column=0, sticky="w", pady=3)
        face_mode_frame = ctk.CTkFrame(frame, fg_color="transparent")
        face_mode_frame.grid(row=0, column=1, sticky="w", padx=6)
        self.face_mode = ctk.CTkOptionMenu(face_mode_frame, width=70, values=["绝对值", "百分比"],
                                           command=self._on_face_mode)
        self.face_mode.grid(row=0, column=0)
        self.faces = ctk.CTkEntry(face_mode_frame, width=120, placeholder_text="10000")
        self.faces.grid(row=0, column=1, padx=(6, 0))
        self.face_hint = ctk.CTkLabel(face_mode_frame, text="", text_color="gray",
                                      font=ctk.CTkFont(size=11))
        self.face_hint.grid(row=0, column=2, padx=(6, 0))

        # 策略
        ctk.CTkLabel(frame, text="简化策略:").grid(row=1, column=0, sticky="w", pady=3)
        self.strategy = ctk.CTkOptionMenu(frame,
            values=["triangular(三角形)", "prob_triangular(概率三角形)",
                    "planar(平面)", "prob_planar(概率平面)"])
        self.strategy.grid(row=1, column=1, sticky="ew", padx=6)

        # 选项复选框
        opts = ctk.CTkFrame(frame, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self.preserve_boundary = ctk.CTkCheckBox(opts, text="边界保持", width=110)
        self.preserve_boundary.grid(row=0, column=0, padx=(0, 8))
        self.preserve_normal = ctk.CTkCheckBox(opts, text="法线保持", width=110)
        self.preserve_normal.grid(row=0, column=1, padx=8)
        self.optimal_placement = ctk.CTkCheckBox(opts, text="最优位置", width=110)
        self.optimal_placement.grid(row=0, column=2, padx=8)
        self.texcoord_weight = ctk.CTkCheckBox(opts, text="纹理权重", width=110)
        self.texcoord_weight.grid(row=0, column=3, padx=8)

        # 质量阈值
        ctk.CTkLabel(frame, text="质量阈值:").grid(row=3, column=0, sticky="w", pady=3)
        self.quality_thr = ctk.CTkEntry(frame, width=120, placeholder_text="0.3 (0~1)")
        self.quality_thr.grid(row=3, column=1, sticky="w", padx=6)

        # 布线优化(重网格化)
        self.remesh = ctk.CTkCheckBox(frame, text="布线优化(各向同性重网格化, 模拟OPEditor)")
        self.remesh.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # UV 打包设置
        ctk.CTkLabel(frame, text="UV打包:").grid(row=5, column=0, sticky="w", pady=3)
        uvpack = ctk.CTkFrame(frame, fg_color="transparent")
        uvpack.grid(row=5, column=1, sticky="w", padx=6)
        self.uv_mode = ctk.CTkOptionMenu(uvpack, width=90, values=["padding", "bruteForce"],
                                         command=self._on_uv_mode)
        self.uv_mode.grid(row=0, column=0)
        self.uv_value = ctk.CTkEntry(uvpack, width=70, placeholder_text="auto")
        self.uv_value.grid(row=0, column=1, padx=(6, 0))
        self.uv_hint = ctk.CTkLabel(uvpack, text="px或auto(=分辨率/256)", text_color="gray",
                                    font=ctk.CTkFont(size=11))
        self.uv_hint.grid(row=0, column=2, padx=(6, 0))
        self.uv_res = ctk.CTkEntry(frame, width=70, placeholder_text="2048")
        self.uv_res.grid(row=5, column=2, sticky="w")

    # ========== 纹理烘焙区 ==========
    def _build_bake_section(self):
        frame = self._section("🎨 纹理烘焙(GPU)")
        frame.grid_columnconfigure(1, weight=1)

        # GPU 烘焙开关
        self.bake = ctk.CTkCheckBox(frame, text="纹理烘焙(GPU, 从OSGB采样到UV图集)",
                                     command=self._toggle_bake)
        self.bake.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        # 参数面板
        self.bake_panel = ctk.CTkFrame(frame, fg_color="transparent")
        self.bake_panel.grid(row=1, column=0, columnspan=3, sticky="ew")

        ctk.CTkLabel(self.bake_panel, text="分辨率:").grid(row=0, column=0, sticky="w", pady=3)
        self.tex_size = ctk.CTkEntry(self.bake_panel, width=120, placeholder_text="2048")
        self.tex_size.grid(row=0, column=1, sticky="w", padx=6)

        ctk.CTkLabel(self.bake_panel, text="采样精度:").grid(row=1, column=0, sticky="w", pady=3)
        self.bake_step = ctk.CTkOptionMenu(self.bake_panel, width=120,
            values=["1 (最高, 全像素)", "2 (标准)", "3 (快速)"])
        self.bake_step.grid(row=1, column=1, sticky="w", padx=6)

        ctk.CTkLabel(self.bake_panel, text="A纹理采样:").grid(row=2, column=0, sticky="w", pady=3)
        self.bake_bilinear = ctk.CTkOptionMenu(self.bake_panel, width=120,
            values=["双线性(平滑)", "最近邻(锐利)"])
        self.bake_bilinear.grid(row=2, column=1, sticky="w", padx=6)

        ctk.CTkLabel(self.bake_panel, text="ray偏移:").grid(row=3, column=0, sticky="w", pady=3)
        self.bake_rayoff = ctk.CTkEntry(self.bake_panel, width=120, placeholder_text="0.0001")
        self.bake_rayoff.grid(row=3, column=1, sticky="w", padx=6)

        ctk.CTkLabel(self.bake_panel, text="接缝修复(dilate):").grid(row=4, column=0, sticky="w", pady=3)
        self.bake_dilate = ctk.CTkEntry(self.bake_panel, width=120, placeholder_text="4")
        self.bake_dilate.grid(row=4, column=1, sticky="w", padx=6)

    # ========== 输出区 ==========
    def _build_output_section(self):
        frame = self._section("💾 输出")
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="输出目录:").grid(row=0, column=0, sticky="w", pady=3)
        self.output_path = ctk.CTkEntry(frame, placeholder_text="选择输出目录, 文件自动命名为 <瓦片名>.fbx")
        self.output_path.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_output).grid(row=0, column=2)

        ctk.CTkLabel(frame, text="格式:").grid(row=1, column=0, sticky="w", pady=3)
        self.format = ctk.CTkOptionMenu(frame, values=[".obj", ".fbx"], command=self._on_format)
        self.format.grid(row=1, column=1, sticky="w", padx=6)

        ctk.CTkLabel(frame, text="缩放:").grid(row=2, column=0, sticky="w", pady=3)
        self.scale = ctk.CTkEntry(frame, width=80, placeholder_text="1.0")
        self.scale.grid(row=2, column=1, sticky="w", padx=6)
        self.scale_hint = ctk.CTkLabel(frame, text="顶点×倍数(OBJ用; 100≈FBX scale)", text_color="gray",
                                       font=ctk.CTkFont(size=11))
        self.scale_hint.grid(row=2, column=2, sticky="w")


    # ========== 操作区 ==========
    def _build_action_bar(self):
        bar = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=16, pady=8)
        bar.grid_columnconfigure(1, weight=1)

        self.run_btn = ctk.CTkButton(bar, text="▶ 开始处理", height=42,
                                     font=ctk.CTkFont(size=15, weight="bold"),
                                     command=self.start_processing)
        self.run_btn.grid(row=0, column=0, sticky="w")

        self.progress = ctk.CTkProgressBar(bar, height=14)
        self.progress.grid(row=0, column=1, sticky="ew", padx=16)
        self.progress.set(0)

        self.status = ctk.CTkLabel(bar, text="就绪", text_color="gray", font=ctk.CTkFont(size=12))
        self.status.grid(row=0, column=2, sticky="e")

    # ========== 日志区 ==========
    def _build_log_section(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=4, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(frame, text="处理日志", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        self.log_text = ctk.CTkTextbox(frame, height=160, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ========== 工具方法 ==========
    def _section(self, title):
        frame = ctk.CTkFrame(self.content)
        frame.grid(sticky="ew", padx=2, pady=6)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=("#1a73e8", "#8ab4f8")).grid(row=0, column=0, columnspan=3,
                                                              sticky="w", padx=10, pady=(8, 2))
        return frame

    def set_defaults(self):
        self.lod.set("L22")
        self.merge_ratio.insert(0, "0.022")
        self.stitch_ratio.insert(0, "0.2")
        self.faces.insert(0, "10000")
        self.face_mode.set("绝对值")
        self._on_face_mode("绝对值")
        self.strategy.set("planar(平面)")
        self.uv_mode.set("padding")
        self.uv_value.delete(0, "end"); self.uv_value.insert(0, "auto")
        self.uv_res.delete(0, "end"); self.uv_res.insert(0, "2048")
        self._on_uv_mode("padding")
        # 边界保持默认不勾选(对齐 OPEditor: 保边界会导致顶点过多)
        # self.preserve_boundary.select()  ← 不勾选
        self.preserve_normal.select()
        self.optimal_placement.select()
        # 纹理权重默认不勾选(纯几何减面无纹理, 勾选无实际效果)
        # self.texcoord_weight.select()  ← 不勾选
        self.remesh.select()  # 默认开启布线优化
        self.quality_thr.insert(0, "0.3")
        self.tex_size.insert(0, "2048")
        self.bake_step.set("2 (标准)")
        self.bake_bilinear.set("双线性(平滑)")
        self.bake_rayoff.insert(0, "0.0001")
        self.bake_dilate.insert(0, "4")
        self.format.set(".obj")
        self.scale.insert(0, "100")
        self._on_format(".obj")
        self._toggle_bake()

    def _toggle_bake(self):
        state = "normal" if self.bake.get() else "disabled"
        for child in self.bake_panel.winfo_children():
            # Entry/OptionMenu/CheckBox 支持 state; Label 不支持, 跳过
            if isinstance(child, (ctk.CTkEntry, ctk.CTkOptionMenu, ctk.CTkCheckBox)):
                try:
                    child.configure(state=state)
                except Exception:
                    pass

    def _browse_input(self):
        p = filedialog.askdirectory(title="选择 OSGB 目录")
        if p:
            self.input_path.delete(0, "end")
            self.input_path.insert(0, p)
            # 自动填输出
            if not self.output_path.get():
                self.output_path.insert(0, os.path.join(os.path.dirname(p),
                                          os.path.basename(p) + "_simplified" + self.format.get()))

    def _browse_output(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.output_path.delete(0, "end")
            self.output_path.insert(0, p)

    def _log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def _set_status(self, msg, color="gray"):
        self.status.configure(text=msg, text_color=color)

    # ========== 处理流程 ==========
    def start_processing(self):
        if self.run_btn.cget("text").startswith("停止"):
            return
        # 收集参数
        try:
            args = self._collect_args()
        except ValueError as e:
            messagebox.showerror("参数错误", str(e))
            return
        self.run_btn.configure(text="处理中...", state="disabled")
        self.progress.set(0)
        self._set_status("处理中...", "#f0a020")
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _on_format(self, fmt):
        """切换输出格式: OBJ 提示 scale, FBX 提示命名"""
        if fmt == ".obj":
            self.scale_hint.configure(text="顶点×倍数(OBJ用; 100≈FBX scale)")
        else:
            self.scale_hint.configure(text="FBX 自动 scale=100(GlobalSettings)")

    def _on_uv_mode(self, mode):
        """切换 UV 打包模式: padding 提示岛间距, bruteForce 提示无参"""
        if mode == "bruteForce":
            self.uv_hint.configure(text="密集打包(慢,质量最高)")
            self.uv_value.configure(state="disabled")
        else:
            self.uv_hint.configure(text="px或auto(=分辨率/256)")
            self.uv_value.configure(state="normal")

    def _on_face_mode(self, mode):
        """切换目标面数输入模式: 绝对值 / 百分比"""
        if mode == "百分比":
            self.faces.configure(placeholder_text="10 = 10%")
            self.face_hint.configure(text="% (减为原面数的比例)")
        else:
            self.faces.configure(placeholder_text="10000")
            self.face_hint.configure(text="")
        self.face_hint.update_idletasks()

    def _collect_args(self):
        inp = self.input_path.get().strip()
        out = self.output_path.get().strip()
        if not inp or not os.path.exists(inp):
            raise ValueError("请选择有效的 OSGB 目录")
        if not out:
            raise ValueError("请填写输出目录")

        class A: pass
        a = A()
        a.input = inp
        a.lod = self.lod.get()
        a.merge_thr = float(self.merge_ratio.get()) if self.merge_ratio.get() else 0.022
        a.stitch_thr = float(self.stitch_ratio.get()) if self.stitch_ratio.get() else 0.2
        # 目标面数: 绝对值直接取; 百分比需加载后换算(见 _worker 第1步)
        face_val = self.faces.get().strip()
        if not face_val:
            face_val = "10000"
        a.face_mode = self.face_mode.get()
        if a.face_mode == "百分比":
            a.faces_pct = float(face_val) / 100.0
            a.faces = 0  # 占位, _worker 里用 loaded_f 换算
        else:
            a.faces_pct = None
            a.faces = int(float(face_val))
        strat = self.strategy.get().split("(")[0]
        a.strategy = strat
        # 瓦片名: 从输入目录提取, 去 + (与 Data/ 文件夹名语义一致)
        base = os.path.basename(inp.rstrip('\\/'))
        tile_name = base.replace('+', '')
        a.name = tile_name
        # 输出 = 输出目录 + <瓦片名>.<格式>
        os.makedirs(out, exist_ok=True)
        a.output = os.path.join(out, tile_name + self.format.get())
        a.scale = float(self.scale.get()) if self.scale.get() else 1.0
        a.fmt = self.format.get()
        a.bake = bool(self.bake.get())
        self._toggle_bake()  # 确保烘焙面板 state 正确(勾选时 normal)
        _ts = self.tex_size.get().strip()
        a.bake_res = int(_ts) if _ts else 2048
        _dl = self.bake_dilate.get().strip()
        a.dilate = int(_dl) if _dl else 4  # UV 接缝修复像素
        _st = self.bake_step.get()
        a.bake_step = 1 if "1" in _st else (3 if "3" in _st else 2)
        a.bake_bilinear = "双线性" in self.bake_bilinear.get()
        a.bake_rayoff = float(self.bake_rayoff.get().strip() or "0.0001")
        a.uv_mode = self.uv_mode.get()
        a.uv_resolution = int(self.uv_res.get()) if self.uv_res.get() else 2048
        uvval = self.uv_value.get().strip().lower()
        if uvval in ('', 'auto'):
            a.uv_padding = max(1, a.uv_resolution // 256)  # 512→2, 1024→4, 2048→8, 4096→16
        else:
            a.uv_padding = int(uvval)
        a.uv_brute = (a.uv_mode == "bruteForce")
        a.preserve_boundary = bool(self.preserve_boundary.get())
        a.preserve_normal = bool(self.preserve_normal.get())
        a.optimal_placement = bool(self.optimal_placement.get())
        a.texcoord_weight = 1.0 if self.texcoord_weight.get() else 0.0
        a.quality_thr = float(self.quality_thr.get()) if self.quality_thr.get() else None
        a.bake = bool(self.bake.get())
        a.remesh = bool(self.remesh.get())
        a.remesh_iterations = 10
        a.remesh_targetlen = None
        a.tex_size = getattr(a, 'bake_res', int(self.tex_size.get() or 2048))
        a.rotation = ""  # 坐标变换在 OBJ 层完成, FBX 导出不再旋转
        a.coords = 'geographic'
        a.keep_obj = False
        a.verbose = True
        return a

    def _worker(self, args):
        try:
            import osgb_merge_export as ome
            osgconv = ome.find_osg()
            if not osgconv:
                raise RuntimeError("找不到 osgconv.exe, 请设置 OSGROOT 环境变量")

            def step(n, msg):
                self.after(0, lambda: (self._log(msg), self.progress.set(n / 5)))
                self._set_status(msg[:40], "#f0a020")

            env = ome.osgb_env(osgconv)
            osgb_full = os.path.join(os.path.dirname(os.path.abspath(ome.__file__)),
                                     '..', 'engine', 'osgb_full.exe')
            import tempfile, shutil, os as _os
            work = tempfile.mkdtemp(prefix="osgb_gui_")
            try:
                # 第1步: 分层回退加载
                step(0, "[1/5] 加载 OSGB (分层回退 LOD)...")
                raw_obj = _os.path.join(work, "raw.obj")
                tiles = ome.find_root_tiles(args.input)
                if not tiles:
                    raise RuntimeError("未找到 OSGB 瓦片")
                max_lod = 0 if args.lod == 'root' else int(args.lod.replace('L',''))
                loaded_v, loaded_f = ome.osgb_full_load(osgb_full, osgconv, tiles, raw_obj, max_lod, env)
                # 百分比模式: 加载后按比例换算目标面数
                if getattr(args, 'faces_pct', None):
                    args.faces = max(100, int(loaded_f * args.faces_pct))
                self.after(0, lambda: self._log(
                    f"  加载 {len(tiles)} 瓦片, {loaded_v:,} 顶点, {loaded_f:,} 面"
                    + (f", 目标面数={args.faces:,} ({getattr(args,'faces_pct',0)*100:.0f}%)" if getattr(args,'faces_pct',None) else "")))

                # 第2步: 合并 + 缝合
                step(1, "[2/5] 网格合并 + 边界缝合 ...")
                merged_obj = _os.path.join(work, "merged.obj")
                ome.merge_mesh(raw_obj, merged_obj, args.merge_thr, args.stitch_thr, True)

                # 第3步: 减面
                step(2, f"[3/5] 减面 (策略={args.strategy}, 目标={args.faces}) ...")
                simp_obj = _os.path.join(work, "simplified.obj")
                import pymeshlab
                from pymeshlab.pmeshlab import PureValue
                ms = pymeshlab.MeshSet()
                ms.load_new_mesh(merged_obj)
                before_f = ms.current_mesh().face_number()
                if args.faces > 0 and args.faces < before_f:
                    strat = {
                        'planar': dict(planarquadric=True, qualitythr=0.3),
                        'prob_planar': dict(planarquadric=True, qualitythr=0.1),
                        'triangular': dict(planarquadric=False, qualitythr=0.3),
                        'prob_triangular': dict(planarquadric=False, qualitythr=0.5),
                    }.get(args.strategy, dict(planarquadric=True, qualitythr=0.3))
                    # 使用 GUI 选项(边界保持/法线保持/最优位置/纹理权重)
                    decim_params = dict(
                        targetfacenum=args.faces,
                        preserveboundary=bool(args.preserve_boundary),
                        preservenormal=bool(args.preserve_normal),
                        optimalplacement=bool(args.optimal_placement),
                    )
                    decim_params.update(strat)
                    # GUI 质量阈值覆盖策略默认(用户可调)
                    if getattr(args, 'quality_thr', None) is not None:
                        decim_params['qualitythr'] = float(args.quality_thr)
                    if getattr(args, 'texcoord_weight', 0) and args.texcoord_weight > 0:
                        decim_params['extratcoordw'] = float(args.texcoord_weight)
                    ms.meshing_decimation_quadric_edge_collapse(**decim_params)
                    m = ms.current_mesh()
                    V = m.vertex_matrix(); F = m.face_matrix()
                    with open(simp_obj, 'w') as f:
                        for v in V:
                            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                        for tri in F:
                            f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
                    self.after(0, lambda: self._log(
                        f"  减面: {before_f} → {len(F)} 面, {len(V)} 顶点"))
                else:
                    simp_obj = merged_obj

                # 第4步: UV 展开 (在 Z-up 坐标, 与 A 源同坐标系)
                step(3, "[4/5] UV 展开...")
                import numpy as np
                uv_obj = _os.path.join(work, "unwrapped.obj")
                if getattr(args, 'uv', True):  # OBJ 默认展开 UV
                    import uv_unwrap
                    uv_unwrap.unwrap(simp_obj, uv_obj,
                                      resolution=getattr(args, 'uv_resolution', 2048),
                                      padding=getattr(args, 'uv_padding', 4),
                                      brute_force=getattr(args, 'uv_brute', False),
                                      verbose=False)
                    export_obj = uv_obj
                else:
                    export_obj = simp_obj

                # 纹理烘焙(可选): UV展开后, B(export_obj) 与 A(merged) 都是 Z-up, 坐标重叠
                if getattr(args, 'bake', False):
                    step(4, "[4.5/5] 纹理烘焙 (GPU)...")
                    import texture_bake as _tb
                    _cwd = _os.getcwd()
                    _os.chdir(_os.path.dirname(raw_obj))
                    _src = _tb.BakeSource(_os.path.basename(raw_obj))  # A 源 = osgb_full 输出(带纹理), Z-up
                    _os.chdir(_cwd)
                    tex_png = _os.path.join(work, "texture.png")
                    _tb.bake(_src, export_obj, tex_png,
                             resolution=getattr(args, 'bake_res', 2048),
                             verbose=True,
                             dilate=getattr(args, 'dilate', 4),
                             sample_step=getattr(args, 'bake_step', 2),
                             bilinear=getattr(args, 'bake_bilinear', True),
                             ray_offset=getattr(args, 'bake_rayoff', 1e-4))
                    args._tex_png = tex_png
                    self.after(0, lambda: self._log(f"  烘焙完成: {tex_png}"))

                # 第5步: 转轴 Y-up + scale + 导出
                if getattr(args, 'fmt', '.obj') == '.obj':
                    step(5, "[5/5] 转轴 Y-up + scale + 导出...")
                    # 读 UV 展开后的几何(vi/vti 分离) + 转轴 + scale
                    _v, _vt, _f = [], [], []
                    for _line in open(export_obj, encoding='utf-8', errors='replace'):
                        _p = _line.split()
                        if not _p: continue
                        if _p[0] == 'v':
                            _v.append([float(_p[1]), float(_p[2]), float(_p[3])])
                        elif _p[0] == 'vt':
                            _vt.append([float(_p[1]), float(_p[2])])
                        elif _p[0] == 'f':
                            _idx = [x.split('/') for x in _p[1:]]
                            if len(_idx) >= 3:
                                _f.append((int(_idx[0][0])-1, int(_idx[0][1])-1,
                                           int(_idx[1][0])-1, int(_idx[1][1])-1,
                                           int(_idx[2][0])-1, int(_idx[2][1])-1))
                    _V = np.array(_v)
                    # 转轴 (x,y,z)Z-up → (x,z,-y)Y-up
                    _V_rot = np.column_stack([_V[:,0], _V[:,2], -_V[:,1]])
                    # scale
                    if args.scale != 1.0:
                        _V_rot *= args.scale
                    # 写最终 OBJ(几何 + vt V翻转对齐图集 + f 分离)
                    with open(args.output, 'w', encoding='utf-8') as _fout:
                        for _xyz in _V_rot:
                            _fout.write(f"v {_xyz[0]:.6f} {_xyz[1]:.6f} {_xyz[2]:.6f}\n")
                        for _uvt in _vt:
                            _fout.write(f"vt {_uvt[0]:.6f} {_uvt[1]:.6f}\n")  # 烘焙已用 1-v 对齐, vt 保持原样
                        for _row in _f:
                            _fout.write(f"f {_row[0]+1}/{_row[1]+1} {_row[2]+1}/{_row[3]+1} {_row[4]+1}/{_row[5]+1}\n")
                    # 有烘焙: 写 MTL + 复制 texture
                    if getattr(args, '_tex_png', None):
                        import shutil as _shu
                        _base = _os.path.splitext(args.output)[0]
                        _mtl = _base + '.mtl'
                        _tex = _base + '_texture.png'
                        # 导出贴图上下翻转(垂直翻转, OBJ vt 保持原样)
                        from PIL import Image as _PILImage
                        _timg = _PILImage.open(args._tex_png).transpose(_PILImage.FLIP_TOP_BOTTOM)
                        _timg.save(_tex)
                        with open(_mtl, 'w') as _f:
                            _f.write("newmtl material_0\n")
                            _f.write("Ka 0.2 0.2 0.2\nKd 0.8 0.8 0.8\nKs 0 0 0\n")
                            _f.write("map_Kd " + _os.path.basename(_tex) + "\n")
                        # OBJ 头部加 mtllib
                        _obj_data = open(args.output, encoding='utf-8').read()
                        _obj_data = f"mtllib {_os.path.basename(_mtl)}\n" + _obj_data
                        open(args.output, 'w', encoding='utf-8').write(_obj_data)
                        self.after(0, lambda: self._log(f"  纹理: {_tex}"))
                    self.after(0, lambda: self._log(f"  输出: {args.output}"))
                else:
                    step(4, "[5/5] 导出 FBX + 命名 + GlobalSettings...")
                    model_name = args.name.replace('+', '')
                    ome.obj_to_fbx(osgconv, axis_obj, args.output, env, model_name=model_name)
                    ome.patch_fbx_global(args.output)

                size = _os.path.getsize(args.output) // 1024
                self.after(0, lambda: (
                    self._log(f"完成! 输出: {args.output} ({size} KB)"),
                    self.progress.set(1),
                    self._set_status("完成 ✓", "#22c55e"),
                    self.run_btn.configure(text="▶ 开始处理", state="normal"),
                ))
            finally:
                shutil.rmtree(work, ignore_errors=True)
        except Exception as e:
            tb = traceback.format_exc()
            self.after(0, lambda: (
                self._log("错误: " + str(e)),
                self._log(tb),
                self._set_status("失败 ✗", "#ef4444"),
                self.run_btn.configure(text="▶ 开始处理", state="normal"),
                messagebox.showerror("处理失败", str(e)),
            ))


if __name__ == "__main__":
    app = App()
    app.mainloop()