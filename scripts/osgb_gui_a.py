#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osgb_gui_a.py — 双段流程工具
  段A: OSGB 合并 + 简化 → 输出 OBJ(含转轴 Y-up + scale, 供手动修改)
  段B: 输入手动修改的 OBJ + OSGB 目录 → 自动分UV + GPU烘焙 → 输出 OBJ + 贴图
"""
import os
import sys
import shutil
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
import numpy as np

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)


class ToolTip:
    """悬浮提示: 鼠标悬停在控件上显示说明文字"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 24
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip.attributes("-topmost", True)
        lbl = tk.Label(self.tip, text=self.text, justify="left",
                       bg="#ffffe0", fg="#333333", relief="solid", borderwidth=1,
                       font=("Microsoft YaHei UI", 18), padx=10, pady=6)
        lbl.pack()

    def _hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class AppA(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OSGB 合并简化 → OBJ → 手动修改 → UV+烘焙")
        self.geometry("1000x960")
        self.minsize(880, 860)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        ctk.CTkLabel(header, text="OSGB 合并简化 → OBJ → UV烘焙",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        ctk.CTkLabel(header, text="段A输出OBJ(手动修改) → 段B分UV+烘焙",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(side="right")

        self.content = ctk.CTkScrollableFrame(self)
        self.content.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        self.content.grid_columnconfigure(0, weight=1)

        self._build_input_section()
        self._build_lod_section()
        self._build_simplify_section()
        self._build_output_section()
        self._build_output2_section()
        self._build_action_bar()
        self._build_section_b()
        self._build_action_bar_b()
        self._build_log_section()
        self.set_defaults()

    # ========== UI 工具 ==========
    def _section(self, title):
        """创建 section: 标题占独立一行, 内容区从下一行开始(避免标题与内容重叠)"""
        frame = ctk.CTkFrame(self.content)
        frame.grid(sticky="ew", padx=2, pady=6)
        frame.grid_columnconfigure(1, weight=1)
        # 标题独立一行, 占满宽度
        title_lbl = ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=14, weight="bold"),
                                 text_color=("#1a73e8", "#8ab4f8"), anchor="w", justify="left",
                                 wraplength=900)
        title_lbl.grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(8, 2))
        # 内容容器: 从 row=1 开始
        body = ctk.CTkFrame(frame, fg_color="transparent")
        body.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=(0, 4))
        body.grid_columnconfigure(1, weight=1)
        return body

    # ========== 段A: 输入 ==========
    def _build_input_section(self):
        frame = self._section("A1. 输入 OSGB")
        frame.grid_columnconfigure(1, weight=1)
        _lbl_in = ctk.CTkLabel(frame, text="OSGB 目录:")
        _lbl_in.grid(row=0, column=0, sticky="w", pady=3)
        self.input_path = ctk.CTkEntry(frame, placeholder_text="含 Data/ 的工程目录")
        self.input_path.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_input).grid(row=0, column=2)
        ToolTip(_lbl_in, "OSGB 工程目录: 含 Data/ 的文件夹")
        ToolTip(self.input_path, "每瓦片独立 OBJ: 输入含 Data/ 的工程目录, 逐瓦片输出")

    def _build_lod_section(self):
        frame = self._section("A2. LOD 与合并")
        frame.grid_columnconfigure(0, weight=1)
        # 横向一排: LOD层级 | 顶点融合阈值 | 边界缝合阈值 (每组均分撑满)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        for c in range(3):
            row.grid_columnconfigure(c, weight=1)

        g0 = ctk.CTkFrame(row, fg_color="transparent")
        g0.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        g0.grid_columnconfigure(1, weight=1)
        _lbl_lod = ctk.CTkLabel(g0, text="LOD 层级:")
        _lbl_lod.grid(row=0, column=0, sticky="w", pady=3)
        self.lod = ctk.CTkOptionMenu(g0, values=["root", "L16", "L17", "L18", "L19", "L20", "L21", "L22", "all"])
        self.lod.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(_lbl_lod, "加载层级: L22 最高细节; root 最粗; all 全部加载")

        g1 = ctk.CTkFrame(row, fg_color="transparent")
        g1.grid(row=0, column=1, sticky="ew", padx=8)
        g1.grid_columnconfigure(1, weight=1)
        _lbl_mr = ctk.CTkLabel(g1, text="顶点融合阈值:")
        _lbl_mr.grid(row=0, column=0, sticky="w", pady=3)
        self.merge_ratio = ctk.CTkEntry(g1, placeholder_text="0.022")
        self.merge_ratio.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(_lbl_mr, "合并重复顶点距离(单位: 米); 默认 0.022 对齐 OPEditor")

        g2 = ctk.CTkFrame(row, fg_color="transparent")
        g2.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        g2.grid_columnconfigure(1, weight=1)
        _lbl_sr = ctk.CTkLabel(g2, text="边界缝合阈值:")
        _lbl_sr.grid(row=0, column=0, sticky="w", pady=3)
        self.stitch_ratio = ctk.CTkEntry(g2, placeholder_text="0.2")
        self.stitch_ratio.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(_lbl_sr, "消除瓦片接缝点距离; 默认 0.2")

    def _build_simplify_section(self):
        frame = self._section("A3. 简化 (Garland-Heckbert)")
        frame.grid_columnconfigure(0, weight=1)
        # 横向一排: 目标面数 | 质量阈值 | 边界保持 | 法线保持 | 最优位置 (每组均分撑满)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        for c in range(5):
            row.grid_columnconfigure(c, weight=1)

        # 目标面数
        g0 = ctk.CTkFrame(row, fg_color="transparent")
        g0.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        g0.grid_columnconfigure(1, weight=1)
        _lbl_face = ctk.CTkLabel(g0, text="目标面数:")
        _lbl_face.grid(row=0, column=0, sticky="w", pady=3)
        fm = ctk.CTkFrame(g0, fg_color="transparent")
        fm.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        fm.grid_columnconfigure(1, weight=1)
        self.face_mode = ctk.CTkOptionMenu(fm, width=64, values=["绝对值", "百分比"],
                                           command=self._on_face_mode)
        self.face_mode.grid(row=0, column=0)
        self.faces = ctk.CTkEntry(fm, placeholder_text="10000")
        self.faces.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ToolTip(_lbl_face, "简化目标面数: 绝对值(如 10000) 或 百分比(如 10 = 10%)")
        ToolTip(self.face_mode, "绝对值: 精确到 N 面; 百分比: 减为原面数的比例")
        ToolTip(self.faces, "目标面数数值, 与左侧模式配合")

        # 质量阈值
        g1 = ctk.CTkFrame(row, fg_color="transparent")
        g1.grid(row=0, column=1, sticky="ew", padx=8)
        g1.grid_columnconfigure(1, weight=1)
        _lbl_qt = ctk.CTkLabel(g1, text="质量阈值:")
        _lbl_qt.grid(row=0, column=0, sticky="w", pady=3)
        self.quality_thr = ctk.CTkEntry(g1, placeholder_text="0.3")
        self.quality_thr.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(_lbl_qt, "折叠质量阈值 0~1: 越小保留越多细节, 越大约束少")

        # 边界保持
        g2 = ctk.CTkFrame(row, fg_color="transparent")
        g2.grid(row=0, column=2, sticky="ew", padx=8)
        g2.grid_columnconfigure(0, weight=1)
        self.preserve_boundary = ctk.CTkCheckBox(g2, text="边界保持")
        self.preserve_boundary.grid(row=0, column=0, sticky="w")
        ToolTip(self.preserve_boundary, "保留边界边不折叠(避免破洞)")

        # 法线保持
        g3 = ctk.CTkFrame(row, fg_color="transparent")
        g3.grid(row=0, column=3, sticky="ew", padx=8)
        g3.grid_columnconfigure(0, weight=1)
        self.preserve_normal = ctk.CTkCheckBox(g3, text="法线保持")
        self.preserve_normal.grid(row=0, column=0, sticky="w")
        ToolTip(self.preserve_normal, "保留法线方向(避免表面翻转)")

        # 最优位置
        g4 = ctk.CTkFrame(row, fg_color="transparent")
        g4.grid(row=0, column=4, sticky="ew", padx=(8, 0))
        g4.grid_columnconfigure(0, weight=1)
        self.optimal_placement = ctk.CTkCheckBox(g4, text="最优位置")
        self.optimal_placement.grid(row=0, column=0, sticky="w")
        ToolTip(self.optimal_placement, "边折叠后顶点取最优位置(GH 标准)")

    def _build_output_section(self):
        frame = self._section("A4. UV 分配")
        frame.grid_columnconfigure(1, weight=1)
        # 横向一排: 自动分UV | UV分辨率 (两组均分撑满)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        for c in range(2):
            row.grid_columnconfigure(c, weight=1)

        g0 = ctk.CTkFrame(row, fg_color="transparent")
        g0.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        g0.grid_columnconfigure(0, weight=1)
        self.auto_uv = ctk.CTkCheckBox(g0, text="自动分UV")
        self.auto_uv.grid(row=0, column=0, sticky="w", pady=3)
        ToolTip(self.auto_uv, "勾选: 输出 OBJ 后用 xatlas 自动展 UV; 不勾选: 保持原始")

        g1 = ctk.CTkFrame(row, fg_color="transparent")
        g1.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        g1.grid_columnconfigure(1, weight=1)
        _lbl_uv = ctk.CTkLabel(g1, text="UV分辨率:")
        _lbl_uv.grid(row=0, column=0, sticky="w", pady=3)
        self.b_uv_res = ctk.CTkEntry(g1, placeholder_text="2048")
        self.b_uv_res.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        ToolTip(_lbl_uv, "xatlas 分UV 图集分辨率(像素), 默认 2048")

    def _build_output2_section(self):
        frame = self._section("A5. 段A输出")
        frame.grid_columnconfigure(1, weight=1)  # 与 A1 相同: col1 撑满, col2 浏览按钮
        # 横向一排: 缩放 | 输出目录(撑满) | 浏览(col2 与 A1 对齐)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 6))
        row.grid_columnconfigure(3, weight=1)  # 输出目录 entry 弹性

        _lbl_scale = ctk.CTkLabel(row, text="缩放:")
        _lbl_scale.grid(row=0, column=0, sticky="w", pady=3)
        self.scale = ctk.CTkEntry(row, width=80, placeholder_text="100")
        self.scale.grid(row=0, column=1, sticky="w", padx=(4, 18))
        ToolTip(_lbl_scale, "顶点×倍数; 转轴固定 Z-up→Y-up: x,z,-y")

        _lbl_out = ctk.CTkLabel(row, text="输出目录:")
        _lbl_out.grid(row=0, column=2, sticky="w", pady=3, padx=(8, 0))
        self.output_path = ctk.CTkEntry(row, placeholder_text="输出 <瓦片名>.obj")
        self.output_path.grid(row=0, column=3, sticky="ew", padx=(4, 8))
        ToolTip(_lbl_out, "输出 OBJ 保存目录, 每个瓦片一个 <瓦片名>.obj")

        # 浏览按钮: 放 frame 的 col2, 与 A1(OSGB目录)的浏览按钮同一列对齐
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_output).grid(row=0, column=2)

    def _build_action_bar(self):
        bar = ctk.CTkFrame(self.content, fg_color="transparent")
        bar.grid(sticky="ew", padx=2, pady=(4, 2))
        bar.grid_columnconfigure(1, weight=1)
        self.run_btn = ctk.CTkButton(bar, text="▶ A段: 合并简化 → OBJ", height=38,
                                     font=ctk.CTkFont(size=14, weight="bold"),
                                     command=self.start_processing)
        self.run_btn.grid(row=0, column=0, sticky="w")
        self.progress = ctk.CTkProgressBar(bar, height=12)
        self.progress.grid(row=0, column=1, sticky="ew", padx=12)
        self.progress.set(0)
        self.status = ctk.CTkLabel(bar, text="就绪", text_color="gray", font=ctk.CTkFont(size=12))
        self.status.grid(row=0, column=2, sticky="e")

    # ========== 段B: UV + 烘焙 ==========
    def _build_section_b(self):
        frame = self._section("B. 分UV + 纹理烘焙")
        frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(frame, text="修改后OBJ:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_obj = ctk.CTkEntry(frame, placeholder_text="OBJ 文件 或 目录(选目录=批量烘焙所有 .obj; Y-up 同坐标)")
        self.b_obj.grid(row=0, column=1, sticky="ew", padx=6)
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_b_obj).grid(row=0, column=2)

        ctk.CTkLabel(frame, text="输出目录:").grid(row=1, column=0, sticky="w", pady=3)
        self.b_out = ctk.CTkEntry(frame, placeholder_text="输出 <名>_texture.png (只输出贴图)")
        self.b_out.grid(row=1, column=1, sticky="ew", padx=6)
        ctk.CTkButton(frame, text="浏览", width=64, command=self._browse_b_out).grid(row=1, column=2)

        # 参数行: 横向一排 采样精度|A采样|接缝修复|ray偏移|烘焙分辨率 (每组均分撑满)
        params = ctk.CTkFrame(frame, fg_color="transparent")
        params.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        for c in range(5):
            params.grid_columnconfigure(c, weight=1)

        g0 = ctk.CTkFrame(params, fg_color="transparent")
        g0.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        g0.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g0, text="采样精度:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_step = ctk.CTkOptionMenu(g0, values=["1 (最高)", "2 (标准)", "3 (快速)"])
        self.b_step.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        g1 = ctk.CTkFrame(params, fg_color="transparent")
        g1.grid(row=0, column=1, sticky="ew", padx=8)
        g1.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g1, text="A采样:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_bilinear = ctk.CTkOptionMenu(g1,
            values=["双线性(平滑)", "最近邻(锐利)"])
        self.b_bilinear.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        g2 = ctk.CTkFrame(params, fg_color="transparent")
        g2.grid(row=0, column=2, sticky="ew", padx=8)
        g2.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g2, text="接缝修复:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_dilate = ctk.CTkEntry(g2, placeholder_text="4")
        self.b_dilate.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        g3 = ctk.CTkFrame(params, fg_color="transparent")
        g3.grid(row=0, column=3, sticky="ew", padx=8)
        g3.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g3, text="ray偏移:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_rayoff = ctk.CTkEntry(g3, placeholder_text="0.0001")
        self.b_rayoff.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        g4 = ctk.CTkFrame(params, fg_color="transparent")
        g4.grid(row=0, column=4, sticky="ew", padx=(8, 0))
        g4.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(g4, text="烘焙分辨率:").grid(row=0, column=0, sticky="w", pady=3)
        self.b_tex_res = ctk.CTkEntry(g4, placeholder_text="2048")
        self.b_tex_res.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # 悬浮提示(替代灰色/橙色提示文字)
        ToolTip(self.b_obj, "修改后的 OBJ: 文件 或 目录(目录=批量烘焙所有 .obj); 需 Y-up 同坐标")
        ToolTip(self.b_out, "输出目录: <名>_texture.png (只输出贴图)")
        ToolTip(self.b_uv_res, "xatlas 分UV 图集分辨率(像素), 默认 2048")
        ToolTip(self.b_tex_res, "烘焙输出纹理分辨率(像素), 默认 2048")
        ToolTip(self.b_step, "采样精度: 1 最高/2 标准/3 快速(越大越快但越糙)")
        ToolTip(self.b_dilate, "接缝修复: UV 边缘外扩像素数, 默认 4")
        ToolTip(self.b_bilinear, "A 源采样方式: 双线性平滑 或 最近邻锐利")
        ToolTip(self.b_rayoff, "射线起点偏移(避免自相交), 默认 0.0001")

    def _build_action_bar_b(self):
        bar = ctk.CTkFrame(self.content, fg_color="transparent")
        bar.grid(sticky="ew", padx=2, pady=(4, 2))
        bar.grid_columnconfigure(1, weight=1)
        self.run_btn_b = ctk.CTkButton(bar, text="▶ B段: 分UV + 烘焙", height=38,
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       fg_color="#b45309", hover_color="#92400e",
                                       command=self.start_b_processing)
        self.run_btn_b.grid(row=0, column=0, sticky="w")
        self.progress_b = ctk.CTkProgressBar(bar, height=12)
        self.progress_b.grid(row=0, column=1, sticky="ew", padx=12)
        self.progress_b.set(0)
        self.status_b = ctk.CTkLabel(bar, text="就绪", text_color="gray", font=ctk.CTkFont(size=12))
        self.status_b.grid(row=0, column=2, sticky="e")

    def _build_log_section(self):
        frame = ctk.CTkFrame(self)
        frame.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 12))
        # 日志区固定高度, 不随窗口拉伸(weight 留给上方内容区)
        ctk.CTkLabel(frame, text="处理日志", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        self.log_text = ctk.CTkTextbox(frame, height=90, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.pack(fill="x", expand=False, padx=8, pady=(0, 8))

    # ========== 默认值 / 工具 ==========
    def set_defaults(self):
        self.lod.set("L22")
        self.merge_ratio.insert(0, "0.022")
        self.stitch_ratio.insert(0, "0.2")
        self.faces.insert(0, "10000")
        self.face_mode.set("绝对值")
        self._on_face_mode("绝对值")
        self.preserve_normal.select()
        self.optimal_placement.select()
        self.quality_thr.insert(0, "0.3")
        self.scale.insert(0, "100")
        self.b_uv_res.insert(0, "2048")
        self.b_tex_res.insert(0, "2048")
        self.b_step.set("2 (标准)")
        self.b_dilate.insert(0, "4")
        self.b_bilinear.set("双线性(平滑)")
        self.b_rayoff.insert(0, "0.0001")

    def _on_face_mode(self, mode):
        if mode == "百分比":
            self.faces.configure(placeholder_text="10 = 10%")
        else:
            self.faces.configure(placeholder_text="10000")

    def _browse_input(self):
        p = filedialog.askdirectory(title="选择 OSGB 目录")
        if p:
            self.input_path.delete(0, "end")
            self.input_path.insert(0, p)

    def _browse_output(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.output_path.delete(0, "end")
            self.output_path.insert(0, p)

    def _browse_b_obj(self):
        # 支持选目录(批量烘焙多个 OBJ)或单个 OBJ 文件
        p = filedialog.askdirectory(title="选择 OBJ 目录(批量烘焙该目录所有 .obj)")
        if not p:
            p = filedialog.askopenfilename(title="或选择单个 OBJ 文件",
                                           filetypes=[("OBJ", "*.obj")])
        if p:
            self.b_obj.delete(0, "end")
            self.b_obj.insert(0, p)
            if not self.b_out.get():
                self.b_out.insert(0, os.path.dirname(p) if os.path.isfile(p) else p)

    def _browse_b_out(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.b_out.delete(0, "end")
            self.b_out.insert(0, p)

    def _log(self, msg):
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")

    def _set_status(self, text, color="gray"):
        self.status.configure(text=text, text_color=color)

    def _set_status_b(self, text, color="gray"):
        self.status_b.configure(text=text, text_color=color)

    # ========== 段A 参数 / 启动 ==========
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
        face_val = self.faces.get().strip() or "10000"
        a.face_mode = self.face_mode.get()
        if a.face_mode == "百分比":
            a.faces_pct = float(face_val) / 100.0
            a.faces = 0
        else:
            a.faces_pct = None
            a.faces = int(float(face_val))
        a.strategy = "planar"  # 固定平面策略(其他三种备用)
        a.preserve_boundary = bool(self.preserve_boundary.get())
        a.preserve_normal = bool(self.preserve_normal.get())
        a.optimal_placement = bool(self.optimal_placement.get())
        a.quality_thr = float(self.quality_thr.get()) if self.quality_thr.get() else None
        a.scale = float(self.scale.get()) if self.scale.get() else 1.0
        a.batch_mode = "每瓦片独立OBJ"
        a.auto_uv = bool(self.auto_uv.get())
        a.uv_res = int(self.b_uv_res.get().strip() or "2048")
        base = os.path.basename(inp.rstrip('\\/'))
        a.name = base.replace('+', '')
        os.makedirs(out, exist_ok=True)
        a.output = os.path.join(out, a.name + ".obj")
        return a

    def start_processing(self):
        try:
            args = self._collect_args()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return
        self.run_btn.configure(text="⏳ A段处理中...", state="disabled")
        self.progress.set(0)
        self._set_status("A处理中", "#f59e0b")
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _worker(self, args):
        try:
            import osgb_merge_export as ome
            import pymeshlab
            from pymeshlab.pmeshlab import PureValue
            osgconv = ome.find_osg()
            osgb_full = os.path.join(SCRIPT_DIR, '..', 'engine', 'osgb_full.exe')
            env = ome.osgb_env(osgconv)
            max_lod = 0 if args.lod == "all" else (None if args.lod == "root" else int(args.lod[1:]))
            tiles = ome.find_root_tiles(args.input)
            if not tiles:
                raise ValueError(f"未找到 OSGB 文件: {args.input}")

            # 每瓦片独立 OBJ(固定模式)
            self.after(0, lambda: self._log(f"[A] 每瓦片独立模式: {len(tiles)} 瓦片"))
            ok = 0
            for i, tile in enumerate(tiles):
                tname = os.path.basename(os.path.dirname(tile)).replace('+', '')
                t_out = os.path.join(os.path.dirname(args.output), tname + ".obj")
                self.after(0, lambda t=tname, i=i: self._log(f"  [{i+1}/{len(tiles)}] {t}"))
                try:
                    self._process_tile([tile], t_out, args, ome, pymeshlab, PureValue,
                                       osgconv, osgb_full, env, max_lod, log=self._log)
                    ok += 1
                except Exception as e:
                    self.after(0, lambda t=tname, e=e: self._log(f"  ❌ {t} 失败: {e}"))
                self.progress.set(0.1 + 0.9 * (i + 1) / len(tiles))
            self.after(0, lambda ok=ok, tiles=tiles: (
                self._log(f"A段批量完成! {ok}/{len(tiles)} 成功 — 请逐个手动修改后交给B段"),
                self.progress.set(1),
                self._set_status("A完成 ✓", "#22c55e"),
                self.run_btn.configure(text="▶ A段: 合并简化 → OBJ", state="normal"),
            ))
        except Exception as e:
            tb = traceback.format_exc()
            self.after(0, lambda e=e, tb=tb: (
                self._log("A错误: " + str(e)), self._log(tb),
                self._set_status("A失败 ✗", "#ef4444"),
                self.run_btn.configure(text="▶ A段: 合并简化 → OBJ", state="normal"),
                messagebox.showerror("A段失败", str(e)),
            ))

    def _process_tile(self, tiles, out_obj, args, ome, pymeshlab, PureValue,
                      osgconv, osgb_full, env, max_lod, log=None):
        """处理一组瓦片 → 合并+简化+转轴 → 输出 OBJ (单瓦片或全部合并共用)"""
        work = os.path.join(os.environ.get('TEMP', '/tmp'), "osgb_gui_a_work")
        os.makedirs(work, exist_ok=True)
        try:
            if log: log(f"  [A1] 加载 {len(tiles)} 瓦片 (LOD={args.lod})...")
            raw_obj = os.path.join(work, f"raw_{abs(hash(str(tiles))) % 100000}.obj")
            loaded_v, loaded_f = ome.osgb_full_load(osgb_full, osgconv, tiles, raw_obj, max_lod, env)
            if args.faces_pct:
                t_faces = max(100, int(loaded_f * args.faces_pct))
            else:
                t_faces = args.faces
            if log: log(f"      {loaded_v:,}v {loaded_f:,}f, 目标面数={t_faces:,}")
            merged_obj = os.path.join(work, f"merged_{abs(hash(str(tiles))) % 100000}.obj")
            ome.merge_mesh(raw_obj, merged_obj, args.merge_thr, args.stitch_thr, True)
            simp_obj = os.path.join(work, f"simp_{abs(hash(str(tiles))) % 100000}.obj")
            ms = pymeshlab.MeshSet()
            ms.load_new_mesh(merged_obj)
            before_f = ms.current_mesh().face_number()
            if t_faces > 0 and t_faces < before_f:
                # 固定平面策略(其他三种备用: prob_planar/triangular/prob_triangular)
                strat = dict(planarquadric=True, qualitythr=0.3)
                decim_params = dict(
                    targetfacenum=t_faces,
                    preserveboundary=bool(args.preserve_boundary),
                    preservenormal=bool(args.preserve_normal),
                    optimalplacement=bool(args.optimal_placement),
                )
                decim_params.update(strat)
                if getattr(args, 'quality_thr', None) is not None:
                    decim_params['qualitythr'] = float(args.quality_thr)
                ms.meshing_decimation_quadric_edge_collapse(**decim_params)
                m = ms.current_mesh()
                V = m.vertex_matrix(); F = m.face_matrix()
                with open(simp_obj, 'w') as f:
                    for v in V:
                        f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
                    for tri in F:
                        f.write(f"f {tri[0]+1} {tri[1]+1} {tri[2]+1}\n")
                if log: log(f"      简化: {before_f} → {len(F)} 面, {len(V)} 顶点")
            else:
                simp_obj = merged_obj
            # 转轴 Y-up + scale
            _v, _f = [], []
            for _line in open(simp_obj, encoding='utf-8', errors='replace'):
                _p = _line.split()
                if not _p: continue
                if _p[0] == 'v':
                    _v.append([float(_p[1]), float(_p[2]), float(_p[3])])
                elif _p[0] == 'f':
                    _idx = [int(x.split('/')[0])-1 for x in _p[1:]]
                    if len(_idx) >= 3:
                        _f.append(tuple(_idx[:3]))
            _V = np.array(_v)
            _V_rot = np.column_stack([_V[:,0], _V[:,2], -_V[:,1]])
            if args.scale != 1.0:
                _V_rot *= args.scale

            with open(out_obj, 'w', encoding='utf-8') as _fout:
                _fout.write("# OSGB merge+simplify, Y-up, scale=%g (A段输出, 供手动修改)\n" % args.scale)
                for _xyz in _V_rot:
                    _fout.write(f"v {_xyz[0]:.6f} {_xyz[1]:.6f} {_xyz[2]:.6f}\n")
                for _row in _f:
                    _fout.write(f"f {_row[0]+1} {_row[1]+1} {_row[2]+1}\n")
            if log: log(f"      输出: {out_obj} ({os.path.getsize(out_obj)//1024} KB)")
            # 自动分UV (xatlas): 勾选 auto_uv 则对输出 OBJ 重新分UV
            if getattr(args, 'auto_uv', False):
                import uv_unwrap
                if log: log("      [A5] 自动分UV (xatlas) ...")
                uv_obj = out_obj.replace('.obj', '_uv.obj')
                uv_unwrap.unwrap(out_obj, uv_obj, resolution=getattr(args, 'uv_res', 2048), padding=4,
                                 brute_force=False, verbose=True)
                if os.path.exists(uv_obj):
                    os.replace(uv_obj, out_obj)
                    if log: log(f"      分UV完成: {out_obj}")
                else:
                    if log: log("      [warn] 分UV输出未生成, 保留原OBJ")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ========== 段B 参数 / 启动 ==========
    def _collect_b_args(self):
        bobj = self.b_obj.get().strip()
        bout = self.b_out.get().strip()
        if not bobj or not os.path.exists(bobj):
            raise ValueError("请选择修改后的 OBJ")
        if not bout:
            raise ValueError("请填写输出目录")
        # OSGB 纹理源统一用 A1 的 OSGB 目录
        bosgb = self.input_path.get().strip()
        if not bosgb or not os.path.exists(bosgb):
            raise ValueError("请先填写 A1 的 OSGB 目录(作为纹理源)")
        class B: pass
        b = B()
        b.obj = bobj
        b.osgb = bosgb
        b.out_dir = bout
        b.uv_res = int(self.b_uv_res.get().strip() or "2048")
        b.tex_res = int(self.b_tex_res.get().strip() or "2048")
        b.step = 1 if "1" in self.b_step.get() else (3 if "3" in self.b_step.get() else 2)
        b.dilate = int(self.b_dilate.get().strip() or "4")
        b.bilinear = "双线性" in self.b_bilinear.get()
        b.rayoff = float(self.b_rayoff.get().strip() or "0.0001")
        base = os.path.splitext(os.path.basename(bobj))[0]
        b.name = base
        b.tex_out = os.path.join(bout, base + "_texture.png")
        return b

    def start_b_processing(self):
        try:
            args = self._collect_b_args()
        except Exception as e:
            messagebox.showerror("参数错误", str(e))
            return
        self.run_btn_b.configure(text="⏳ B段处理中...", state="disabled")
        self.progress_b.set(0)
        self._set_status_b("B处理中", "#f59e0b")
        threading.Thread(target=self._worker_b, args=(args,), daemon=True).start()

    def _worker_b(self, args):
        try:
            import osgb_merge_export as ome
            import uv_unwrap
            import texture_bake as tb
            from PIL import Image
            # B 输入: 单个 OBJ 文件 或 目录(批量处理所有 .obj)
            if os.path.isdir(args.obj):
                objs = sorted(f for f in os.listdir(args.obj) if f.lower().endswith('.obj'))
                if not objs:
                    raise ValueError(f"目录内没有 .obj 文件: {args.obj}")
                self.after(0, lambda: self._log(f"[B] 批量独立瓦片烘焙: {len(objs)} 个 OBJ"))
                ok = 0
                for i, fn in enumerate(objs):
                    full = os.path.join(args.obj, fn)
                    base = os.path.splitext(fn)[0]
                    t_out = os.path.join(args.out_dir, base + "_texture.png")
                    self.after(0, lambda fn=fn, i=i: self._log(f"  [{i+1}/{len(objs)}] {fn}"))
                    try:
                        # 批量独立瓦片: 自动匹配 obj 对应的 OSGB 瓦片(只加载该瓦片, 更快更准)
                        tile_dir = self._find_matching_tile(base, args.osgb)
                        if not tile_dir:
                            raise ValueError(f"未匹配到 OSGB 瓦片: {base}")
                        self.after(0, lambda tile_dir=tile_dir: self._log(f"    → 匹配瓦片: {os.path.basename(tile_dir)}"))
                        self._process_b_one(full, args, ome, uv_unwrap, tb, Image,
                                            work_dir=os.path.join(os.environ.get('TEMP','/tmp'), f"osgb_gui_b_{i}"),
                                            tile_dir=tile_dir)
                        ok += 1
                    except Exception as e:
                        self.after(0, lambda fn=fn, e=e: self._log(f"  ❌ {fn} 失败: {e}"))
                    self.progress_b.set(0.1 + 0.9 * (i + 1) / len(objs))
                self.after(0, lambda ok=ok, objs=objs: (
                    self._log(f"B段批量完成! {ok}/{len(objs)} 成功"),
                    self.progress_b.set(1),
                    self._set_status_b("B完成 ✓", "#22c55e"),
                    self.run_btn_b.configure(text="▶ B段: 分UV + 烘焙", state="normal"),
                ))
            else:
                # 单文件模式: 也自动匹配对应瓦片(只加载该瓦片, 更准)
                base_single = os.path.splitext(os.path.basename(args.obj))[0]
                tile_single = self._find_matching_tile(base_single, args.osgb)
                if tile_single:
                    self.after(0, lambda tile_single=tile_single: self._log(f"    → 匹配瓦片: {os.path.basename(tile_single)}"))
                self._process_b_one(args.obj, args, ome, uv_unwrap, tb, Image,
                                    work_dir=os.path.join(os.environ.get('TEMP','/tmp'), "osgb_gui_b_work"),
                                    tile_dir=tile_single)
                self.after(0, lambda: (
                    self._log("B段完成! 贴图烘焙输出成功"),
                    self.progress_b.set(1),
                    self._set_status_b("B完成 ✓", "#22c55e"),
                    self.run_btn_b.configure(text="▶ B段: 分UV + 烘焙", state="normal"),
                ))
        except Exception as e:
            tb2 = traceback.format_exc()
            self.after(0, lambda e=e, tb2=tb2: (
                self._log("B错误: " + str(e)), self._log(tb2),
                self._set_status_b("B失败 ✗", "#ef4444"),
                self.run_btn_b.configure(text="▶ B段: 分UV + 烘焙", state="normal"),
                messagebox.showerror("B段失败", str(e)),
            ))

    def _find_matching_tile(self, base, osgb_root):
        """从 OBJ 名(如 Tile_034_036)匹配 OSGB 瓦片目录(如 Tile_+034_+036)
        匹配规则: 提取数字对(去 _+ 和正负号), 在 Data/ 下找同名瓦片
        """
        import re
        # 提取 obj 名中的数字对 (Tile_034_036 → 034, 036)
        m = re.search(r'(\d+)[_+]*([+-]?\d+)', base)
        if not m:
            return None
        tx, ty = m.group(1).lstrip('+'), m.group(2).lstrip('+')
        # 在 osgb 工程 Data/ 下找匹配瓦片 (Tile_+034_+036)
        data_dir = os.path.join(osgb_root, 'Data')
        pat = re.compile(r'Tile[_+]*([+-]?\d+)[_+]*([+-]?\d+)')
        for cand in os.listdir(data_dir):
            cm = pat.search(cand)
            if cm and cm.group(1).lstrip('+') == tx and cm.group(2).lstrip('+') == ty:
                return os.path.join(data_dir, cand)
        return None

    def _process_b_one(self, obj_path, args, ome, uv_unwrap, tb, Image, work_dir, tile_dir=None):
        """处理单个 OBJ: 提取A源 → 对齐 → UV → 烘焙 → 输出贴图
        tile_dir: 指定瓦片目录时只加载该瓦片(批量独立); None 时用 args.osgb 全部
        """
        import os
        import shutil
        import numpy as _np
        os.makedirs(work_dir, exist_ok=True)
        self.progress_b.set(0.05)
        # B1: OSGB 提取带纹理 raw_obj (A源)
        self.after(0, lambda: self._log("[B1] 提取 OSGB 纹理源 ..."))
        osgconv = ome.find_osg()
        osgb_full = os.path.join(SCRIPT_DIR, '..', 'engine', 'osgb_full.exe')
        env = ome.osgb_env(osgconv)
        if tile_dir is not None:
            # 批量独立瓦片: 只加载匹配的单个瓦片
            tiles = [os.path.join(tile_dir, os.path.basename(tile_dir) + '.osgb')]
            if not os.path.exists(tiles[0]):
                raise ValueError(f"瓦片根文件不存在: {tiles[0]}")
        else:
            tiles = ome.find_root_tiles(args.osgb)
            if not tiles:
                raise ValueError(f"未找到 OSGB 文件: {args.osgb}")
        raw_obj = os.path.join(work_dir, "a_raw.obj")
        ome.osgb_full_load(osgb_full, osgconv, tiles, raw_obj, 22, env)

        # B2: 把 A 源转 Y-up ×scale (与用户OBJ坐标对齐) + 包围盒自动对齐
        self.after(0, lambda: self._log("[B2] A源转 Y-up ×scale + 自动对齐 ..."))
        user_scale = 100.0
        try:
            with open(obj_path, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if line.startswith('#') and 'scale=' in line:
                        import re
                        m = re.search(r'scale=([\d.]+)', line)
                        if m: user_scale = float(m.group(1))
                        break
        except Exception:
            pass
        def _bbox_center(path, n=100000):
            xs, ys, zs = [], [], []
            for line in open(path, encoding='utf-8', errors='replace'):
                p = line.split()
                if p and p[0]=='v' and len(p)>=4:
                    xs.append(float(p[1])); ys.append(float(p[2])); zs.append(float(p[3]))
                if len(xs) >= n: break
            xs, ys, zs = _np.array(xs), _np.array(ys), _np.array(zs)
            return _np.array([(xs.min()+xs.max())/2, (ys.min()+ys.max())/2, (zs.min()+zs.max())/2])
        user_center = _bbox_center(obj_path)
        a_yup = os.path.join(work_dir, "a_yup.obj")
        a_pts = []
        with open(raw_obj, encoding='utf-8', errors='replace') as fin, \
             open(a_yup, 'w', encoding='utf-8') as fout:
            for line in fin:
                p = line.split()
                if not p: continue
                if p[0] == 'v' and len(p) >= 4:
                    x, y, z = float(p[1]), float(p[2]), float(p[3])
                    nx, ny, nz = x*user_scale, z*user_scale, -y*user_scale
                    a_pts.append([nx, ny, nz])
                    fout.write(f"v {nx:.6f} {ny:.6f} {nz:.6f}\n")
                elif p[0] == 'vt':
                    fout.write(line)
                elif p[0] == 'f':
                    fout.write(line)
                elif p[0] == 'mtllib' or p[0].startswith('#'):
                    fout.write(line)
                else:
                    fout.write(line)
        a_pts = _np.array(a_pts)
        if len(a_pts) > 0:
            a_center = _np.array([(a_pts[:,0].min()+a_pts[:,0].max())/2,
                                  (a_pts[:,1].min()+a_pts[:,1].max())/2,
                                  (a_pts[:,2].min()+a_pts[:,2].max())/2])
            delta = user_center - a_center
            if _np.max(_np.abs(delta)) > 1e-6:
                with open(a_yup, 'w', encoding='utf-8') as fout:
                    for line in open(raw_obj, encoding='utf-8', errors='replace'):
                        p = line.split()
                        if not p: continue
                        if p[0] == 'v' and len(p) >= 4:
                            x, y, z = float(p[1]), float(p[2]), float(p[3])
                            nx, ny, nz = x*user_scale + delta[0], z*user_scale + delta[1], -y*user_scale + delta[2]
                            fout.write(f"v {nx:.6f} {ny:.6f} {nz:.6f}\n")
                        elif p[0] == 'vt':
                            fout.write(line)
                        elif p[0] == 'f':
                            fout.write(line)
                        elif p[0] == 'mtllib' or p[0].startswith('#'):
                            fout.write(line)
                        else:
                            fout.write(line)
        self.progress_b.set(0.45)

        # B3: UV 处理 — 用户OBJ自带UV则直接用, 否则自动分UV
        b_uv = os.path.join(work_dir, "b_uv.obj")
        _has_uv = False
        try:
            for _l in open(obj_path, encoding='utf-8', errors='replace'):
                _p = _l.split()
                if _p and _p[0] == 'f' and len(_p) >= 4 and '/' in _p[1]:
                    _has_uv = True
                    break
        except Exception:
            pass
        if _has_uv:
            self.after(0, lambda: self._log("[B3] 检测到用户OBJ自带UV → 直接用"))
            shutil.copyfile(obj_path, b_uv)
        else:
            self.after(0, lambda: self._log("[B3] 用户OBJ无UV → 自动分UV (xatlas) ..."))
            uv_unwrap.unwrap(obj_path, b_uv, resolution=args.uv_res, padding=4,
                             brute_force=False, verbose=True)
        self.progress_b.set(0.6)

        # B4: GPU 烘焙 (A源纹理 → B新UV)
        self.after(0, lambda: self._log("[B4] GPU 纹理烘焙 ..."))
        _cwd = os.getcwd()
        os.chdir(os.path.dirname(a_yup))
        _src = tb.BakeSource(os.path.basename(a_yup))
        os.chdir(_cwd)
        tex_png = os.path.join(work_dir, "texture.png")
        tb.bake(_src, b_uv, tex_png,
                resolution=args.tex_res, verbose=True,
                dilate=args.dilate, sample_step=args.step,
                bilinear=args.bilinear, ray_offset=args.rayoff)
        self.progress_b.set(0.9)

        # B5: 只输出贴图(垂直翻转, 与主GUI一致)
        self.after(0, lambda: self._log("[B5] 输出贴图 ..."))
        base = os.path.splitext(os.path.basename(obj_path))[0]
        tex_out = os.path.join(args.out_dir, base + "_texture.png")
        img = Image.open(tex_png).transpose(Image.FLIP_TOP_BOTTOM)
        img.save(tex_out)
        size = os.path.getsize(tex_out) // 1024
        self.after(0, lambda tex_out=tex_out, size=size: self._log(f"  贴图输出: {tex_out} ({size} KB)"))
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    app = AppA()
    app.mainloop()
