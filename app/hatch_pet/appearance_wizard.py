# -*- coding: utf-8 -*-
"""appearance_wizard — 更换形象向导

分步教学窗口：① 准备说明 → ② 选图/风格（实时预览 Q 版化效果）
→ ③ 后台生成（弹窗进度条 + 阶段提示）→ ④ 完成后自动换装（热重载，
无需重启）。

生成管线复用 q_pet_converter 的 Q 版化与帧变换，并按 Vivian 完整
规格组装精灵图：16 列 × 14 行（192×208/格），12 组动画 × 16 帧
（生气/素待机/wink 三组复用待机帧），第 9/10 行为注视基准帧。
产物写入 %APPDATA%/QPet/appearance/（含上一版备份），运行时优先
加载该目录——因此无需改动安装目录内任何文件。
"""
import json
import os
import shutil
import sys
import threading
import time
import tkinter as tk
from io import BytesIO
from pathlib import Path

CELL_W, CELL_H = 192, 208
ATLAS_COLS, ATLAS_ROWS = 16, 14
FRAME_COUNT = 16

# 复用待机帧补齐 Vivian 完整动作集（行号与其真实精灵图一致）
EXTRA_ANIMS = [
    {"name": "angry",      "row": 11, "label": "生气",   "fps": 8},
    {"name": "idle-plain", "row": 12, "label": "待机·素", "fps": 4},
    {"name": "wink",       "row": 13, "label": "wink",  "fps": 4},
]

AI_PROMPT = ("Q版chibi全身立绘，正面站姿，纯白背景，可爱卡通风格，"
             "2头身，头大身小，全身完整可见，边缘干净")

_BG = "#EEF1F5"
_CARD = "#FFFFFF"
_BORDER = "#E2E6EC"
_ACCENT = "#8B5CF6"
_TEXT = "#2D2A32"
_SUB = "#6B7280"


def appearance_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "QPet"
    else:
        base = Path(os.environ.get("APPDATA") or Path.home()) / "QPet"
    return base / "appearance"


def has_custom_appearance() -> bool:
    d = appearance_dir()
    return (d / "spritesheet.png").exists() and (d / "pet.json").exists()


def generate_appearance(image_path, style, pet_name, out_dir,
                        progress_cb=None) -> dict:
    """后台线程执行：参考图 → Q 版化 → 12 组动画帧 → 精灵图 + 配置。

    progress_cb(fraction 0~1, stage_text, preview_png_bytes|None)
    返回 {"sheet","config","meta","anims","frames"}。
    """
    from PIL import Image
    from .config import ANIMATION_STATES, GAZE_DIRECTIONS
    from .q_pet_converter import QPetConverter, CHIBI_STYLES

    def post(stage, frac, preview=None):
        if progress_cb is not None:
            try:
                progress_cb(frac, stage, preview)
            except Exception:
                pass

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    conv = QPetConverter(style=style)
    post("解析参考图…", 0.04)
    ref = conv.load_image(str(image_path))

    post("Q 版化处理…", 0.12)
    base = Image.open(BytesIO(conv.convert_to_chibi(ref)))

    frames = {}
    states = list(ANIMATION_STATES)
    for i, state in enumerate(states):
        part = conv.generate_sprite_frames(ref, [state], num_frames=FRAME_COUNT,
                                           base_image=base)
        frames.update(part)
        preview = part[state["name"]][0]
        post("生成动画：%s（%d/%d 组）" % (state.get("label", state["name"]),
                                        i + 1, len(states)),
             0.15 + 0.70 * (i + 1) / len(states), preview)

    post("组装精灵图…", 0.88)
    atlas = Image.new("RGBA", (CELL_W * ATLAS_COLS, CELL_H * ATLAS_ROWS),
                      (0, 0, 0, 0))

    def put_row(row, png_list):
        for col in range(ATLAS_COLS):
            img = Image.open(BytesIO(png_list[col % len(png_list)]))
            atlas.paste(img, (col * CELL_W, row * CELL_H))

    for state in states:
        put_row(state["row"], frames[state["name"]])
    idle_png = frames["idle"]
    put_row(9, idle_png)    # 注视基准帧（运行时在此之上重绘眼睛）
    put_row(10, idle_png)
    for extra in EXTRA_ANIMS:
        put_row(extra["row"], frames["idle"])

    sheet_path = out / "spritesheet.png"
    atlas.save(str(sheet_path), "PNG")

    post("写入动画配置…", 0.96)
    animations = []
    for st in states:
        animations.append({"name": st["name"], "label": st.get("label", st["name"]),
                           "row": st["row"], "frameCount": FRAME_COUNT,
                           "fps": st.get("fps", 6),
                           "repeat": st.get("repeat", True),
                           "loop": st.get("repeat", True)})
    for extra in EXTRA_ANIMS:
        animations.append({"name": extra["name"], "label": extra["label"],
                           "row": extra["row"], "frameCount": FRAME_COUNT,
                           "fps": extra["fps"], "repeat": True, "loop": True})
    gazes = [{"name": g["name"], "label": g.get("label", ""),
              "angle": g["angle"], "row": g["row"], "col": g["col"],
              "type": "gaze"} for g in GAZE_DIRECTIONS]

    config = {
        "name": pet_name,
        "description": "%s - Q版桌面宠物（%s·形象向导生成）"
                       % (pet_name, CHIBI_STYLES[style]["name"]),
        "author": "Appearance Wizard",
        "version": "1.0.5",
        "spriteVersionNumber": 2,
        "sprite": {"image": "spritesheet.png",
                   "cell": {"width": CELL_W, "height": CELL_H},
                   "cols": ATLAS_COLS, "rows": ATLAS_ROWS,
                   "atlasWidth": CELL_W * ATLAS_COLS,
                   "atlasHeight": CELL_H * ATLAS_ROWS},
        "animations": animations,
        "gazes": gazes,
    }
    config_path = out / "pet.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    with open(out / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"name": pet_name, "style": style,
                   "style_name": CHIBI_STYLES[style]["name"],
                   "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "source": str(image_path)}, f, ensure_ascii=False, indent=2)

    post("完成", 1.0)
    return {"sheet": str(sheet_path), "config": str(config_path),
            "anims": len(animations), "frames": FRAME_COUNT,
            "preview": base}


class AppearanceWizard:

    def __init__(self, pet):
        self.pet = pet
        self.tk = tk   # 模块级 tkinter 引用（供内部方法统一使用）
        self._closing = False
        self._preview_job = 0
        self._photo_refs = {}
        self._image_path = None
        self._base_preview = None     # Q 版化预览 (PNG bytes)
        self._style = "chibi_classic"
        self._result = None           # 生成结果（步骤④读取，未生成为 None）
        # 跨步骤共享的控件变量（在 __init__ 建好，避免直接跳步时 AttributeError）
        self._style_var = self.tk.StringVar(value="经典Q版")
        self._name_var = self.tk.StringVar(value="MyPet")

        self._build_window()
        self._show_step(0)

    # ---------- 窗口骨架 ----------
    def _build_window(self):
        tk, pet = self.tk, self.pet
        win = tk.Toplevel(pet.root)
        win.title("更换形象向导")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.withdraw()
        self.win = win

        CW, SBW = 540, 0
        self.CW = CW
        canvas = tk.Canvas(win, bg=_BG, highlightthickness=0, width=CW,
                           height=540)
        canvas.pack(side="left", fill="both", expand=True)
        self.canvas = canvas

        self._body = tk.Frame(canvas, bg=_BG)
        self._body_id = canvas.create_window((0, 0), anchor="nw",
                                             window=self._body)
        # Canvas 尺寸变化时把内容 Frame 拉宽到画布宽度（标准可滚动 Frame 模式）
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
            self._body_id, width=e.width))

        # 位置：宠物右侧（放不下则左侧），毛玻璃背景
        win.update_idletasks()
        sh = win.winfo_screenheight()
        sw = win.winfo_screenwidth()
        H = 560
        W = CW + SBW
        px, py = pet.root.winfo_x(), pet.root.winfo_y()
        x = px + pet.win_w + 14
        if x + W > sw - 8:
            x = px - W - 14
        x = max(8, min(x, sw - W - 8))
        y = max(8, min(py - 10, sh - H - 60))
        win.geometry("%dx%d+%d+%d" % (W, H, x, y))
        try:
            from PIL import ImageTk
            img = _frosted(x, y + glass_title_h(), W, H)
            if img is not None:
                self._glass = ImageTk.PhotoImage(img)
                gid = canvas.create_image(0, 0, anchor="nw",
                                          image=self._glass)
                canvas.tag_lower(gid)
        except Exception:
            pass
        try:
            from hatch_pet import glass_ui
            win.deiconify()
            win.attributes("-alpha", 0.0)
            win.grab_set()
            win.focus_set()
            win.protocol("WM_DELETE_WINDOW", self._close)
            glass_ui.animate_open(win)     # 淡入 + 上滑入场
        except Exception:
            win.deiconify()

    def _close(self):
        self._closing = True
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass

    def _post(self, fn):
        self.pet._post_to_main(fn)

    # ---------- 步骤切换 ----------
    _STEPS = ("① 准备", "② 选图", "③ 生成", "④ 完成")

    def _show_step(self, idx):
        for w in self._body.winfo_children():
            w.destroy()
        self._step = idx

        head = tk.Frame(self._body, bg=_BG)
        head.pack(fill="x", padx=16, pady=(14, 4))
        for i, s in enumerate(self._STEPS):
            color = _ACCENT if i == idx else "#C4C9D4"
            tk.Label(head, text=s, bg=_BG, fg=color,
                     font=("Microsoft YaHei", 11, "bold" if i == idx else "normal")
                     ).pack(side="left", padx=(0, 12))

        page = tk.Frame(self._body, bg=_BG)
        page.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        {"0": self._page_intro, "1": self._page_pick,
         "2": self._page_generate, "3": self._page_done}[str(idx)](page)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    # ---------- ① 准备 ----------
    def _page_intro(self, page):
        tk.Label(page, text="🧚 更换形象向导", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 16, "bold")).pack(anchor="w")
        tk.Label(page, text=(
            "跟着向导三步换上新形象，全程无需重启：\n"
            "①  准备一张角色图（AI 生成或手绘都行）\n"
            "②  选择图片与 Q 版风格，实时预览效果\n"
            "③  向导自动生成全套动画并立即换装\n\n"
            "素材建议：全身立绘、正面站姿、纯色或透明背景、\n"
            "尺寸 ≥ 512×512（PNG 透明背景最佳）。"),
            bg=_BG, fg=_TEXT, font=("Microsoft YaHei", 10),
            justify="left").pack(anchor="w", pady=(6, 8))

        card = tk.Frame(page, bg=_CARD, highlightbackground=_BORDER,
                        highlightthickness=1)
        card.pack(fill="x")
        tk.Label(card, text="💡 AI 出图提示词（可复制后粘贴到绘图 AI）",
                 bg=_CARD, fg=_ACCENT,
                 font=("Microsoft YaHei", 9, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2))
        row = tk.Frame(card, bg=_CARD)
        row.pack(fill="x", padx=12, pady=(0, 8))
        ent = tk.Entry(row, font=("Microsoft YaHei", 9))
        ent.insert(0, AI_PROMPT)
        ent.configure(state="readonly")
        ent.pack(side="left", fill="x", expand=True)

        def _copy():
            self.win.clipboard_clear()
            self.win.clipboard_append(AI_PROMPT)
            btn.config(text="已复制 ✓")
            self.win.after(1500, lambda: btn.config(text="复制"))

        btn = tk.Button(row, text="复制", font=("Microsoft YaHei", 9),
                        relief="flat", bg="#F3EFFE", fg=_ACCENT,
                        cursor="hand2", command=_copy)
        btn.pack(side="left", padx=(8, 0))

        cur = self._current_look_widget(page)
        if cur is not None:
            cur.pack(anchor="w", pady=(10, 0))
            tk.Label(page, text="（当前形象）", bg=_BG, fg=_SUB,
                     font=("Microsoft YaHei", 8)).pack(anchor="w")

        self._nav(page, back=False, next_label="下一步：选图")

    def _current_look_widget(self, parent):
        try:
            from PIL import Image as PILImage, ImageTk
            sheet = PILImage.open(self.pet._spritesheet_path).convert("RGBA")
            cell_w = self.pet.config.get("sprite", {}).get("cell", {}) \
                .get("width", 192)
            cell_h = self.pet.config.get("sprite", {}).get("cell", {}) \
                .get("height", 208)
            frame = sheet.crop((0, 0, cell_w, cell_h)).resize((96, 104))
            bg = PILImage.new("RGBA", frame.size, (255, 255, 255, 255))
            bg.alpha_composite(frame)
            photo = ImageTk.PhotoImage(bg)
            self._photo_refs["cur"] = photo
            return tk.Label(parent, image=photo, bg=_BG)
        except Exception:
            return None

    # ---------- ② 选图 ----------
    def _page_pick(self, page):
        tk.Label(page, text="选择角色图片", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")

        row = tk.Frame(page, bg=_BG)
        row.pack(fill="x", pady=(6, 4))
        tk.Button(row, text="📂 选择角色图片", font=("Microsoft YaHei", 10),
                  relief="flat", bg=_ACCENT, fg="#FFFFFF",
                  activebackground="#7C4DFF", activeforeground="#FFFFFF",
                  cursor="hand2", command=self._pick_image).pack(side="left")
        self._file_lbl = tk.Label(row, text="未选择文件", bg=_BG, fg=_SUB,
                                  font=("Microsoft YaHei", 9))
        self._file_lbl.pack(side="left", padx=(10, 0))

        prev = tk.Frame(page, bg=_BG)
        prev.pack(anchor="w", pady=6)
        self._orig_lbl = tk.Label(prev, bg=_CARD, text="原图\n\n（待选择）",
                                  fg=_SUB, width=18, height=8)
        self._orig_lbl.pack(side="left")
        tk.Label(prev, text="  ➜  ", bg=_BG, fg=_ACCENT,
                 font=("Segoe UI Emoji", 16)).pack(side="left", padx=6)
        self._chibi_lbl = tk.Label(prev, bg=_CARD,
                                   text="Q 版化预览\n\n（选图后自动生成）",
                                   fg=_SUB, width=18, height=8)
        self._chibi_lbl.pack(side="left")

        style_row = tk.Frame(page, bg=_BG)
        style_row.pack(fill="x", pady=(4, 0))
        tk.Label(style_row, text="Q 版风格：", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 10)).pack(side="left")
        # _style_var 已在 __init__ 创建（供各步骤安全引用）
        self._style_names = {}
        for key, meta in _styles().items():
            rb = tk.Radiobutton(style_row, text=meta["name"],
                                variable=self._style_var,
                                value=meta["name"], bg=_BG, fg=_TEXT,
                                activebackground=_BG,
                                command=self._on_style_change)
            rb.pack(side="left", padx=(4, 8))
            self._style_names[meta["name"]] = key

        name_row = tk.Frame(page, bg=_BG)
        name_row.pack(fill="x", pady=(4, 0))
        tk.Label(name_row, text="形象名字：", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 10)).pack(side="left")
        # _name_var 已在 __init__ 创建（供各步骤安全引用）
        tk.Entry(name_row, textvariable=self._name_var, width=16,
                 font=("Microsoft YaHei", 10)).pack(side="left", padx=(8, 0))

        self._pick_status = tk.Label(page, text="", bg=_BG, fg=_SUB,
                                     font=("Microsoft YaHei", 9))
        self._pick_status.pack(anchor="w", pady=(4, 0))

        self._nav(page, back=True, next_label="下一步：开始生成",
                  next_cmd=self._go_generate)

        if self._image_path:
            self._refresh_pick_page()

    def _pick_image(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择角色图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp"),
                       ("所有文件", "*.*")])
        if not path:
            return
        self._image_path = path
        self._refresh_pick_page()

    def _refresh_pick_page(self):
        self._file_lbl.config(text=os.path.basename(self._image_path))
        self._pick_status.config(text="正在生成 Q 版预览…", fg=_SUB)
        path, style = self._image_path, self._style_var.get()

        def _show_orig():
            from PIL import Image as PILImage, ImageTk
            img = PILImage.open(path).convert("RGBA")
            img.thumbnail((140, 150))
            bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
            bg.alpha_composite(img)
            self._photo_refs["orig"] = ImageTk.PhotoImage(bg)
            self._orig_lbl.config(image=self._photo_refs["orig"], text="")

        def _work(job):
            try:
                from hatch_pet.q_pet_converter import QPetConverter
                conv = QPetConverter(style=self._style_key(style))
                ref = conv.load_image(path)
                png = conv.convert_to_chibi(ref)
            except Exception as e:
                self._post(lambda: self._pick_status.config(
                    text="预览失败：%s" % str(e)[:60], fg="#C92A2A"))
                return
            if job != self._preview_job or self._closing:
                return
            def _show():
                from PIL import Image as PILImage, ImageTk
                from io import BytesIO
                img = PILImage.open(BytesIO(png))
                img.thumbnail((140, 150))
                bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
                bg.alpha_composite(img)
                self._photo_refs["chibi"] = ImageTk.PhotoImage(bg)
                self._chibi_lbl.config(image=self._photo_refs["chibi"], text="")
                self._base_preview = png
                self._pick_status.config(
                    text="✓ 预览已生成，满意就点「开始生成」", fg="#2B8A3E")
            self._post(_show)

        job = self._preview_job = self._preview_job + 1
        self._post(_show_orig)
        threading.Thread(target=_work, args=(job,), daemon=True).start()

    def _on_style_change(self):
        if self._image_path:
            self._refresh_pick_page()

    def _style_key(self, name):
        return self._style_names.get(name, "chibi_classic")

    # ---------- ③ 生成 ----------
    def _go_generate(self):
        if not self._image_path or not self._base_preview:
            return
        self._show_step(2)

    def _page_generate(self, page):
        tk.Label(page, text="⏳ 正在生成你的新形象…", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 14, "bold")).pack(anchor="w")
        tk.Label(page, text="12 组动画 × 16 帧，生成完成会自动换装，"
                            "无需重启。", bg=_BG, fg=_SUB,
                 font=("Microsoft YaHei", 9)).pack(anchor="w", pady=(2, 8))

        card = tk.Frame(page, bg=_CARD, highlightbackground=_BORDER,
                        highlightthickness=1)
        card.pack(fill="x")
        self._stage_lbl = tk.Label(card, text="准备中…", bg=_CARD, fg=_TEXT,
                                   font=("Microsoft YaHei", 10))
        self._stage_lbl.pack(anchor="w", padx=14, pady=(10, 2))
        from tkinter import ttk
        self._bar = ttk.Progressbar(card, length=460, maximum=100)
        self._bar.pack(fill="x", padx=14, pady=4)
        self._pct_lbl = tk.Label(card, text="0%", bg=_CARD, fg=_SUB,
                                 font=("Consolas", 9))
        self._pct_lbl.pack(anchor="e", padx=14, pady=(0, 4))

        prow = tk.Frame(page, bg=_BG)
        prow.pack(anchor="w", pady=8)
        tk.Label(prow, text="最新生成：", bg=_BG, fg=_SUB,
                 font=("Microsoft YaHei", 9)).pack(side="left")
        self._live_lbl = tk.Label(prow, bg=_CARD, width=12, height=6,
                                  text="")
        self._live_lbl.pack(side="left", padx=(6, 0))

        self._gen_error = tk.Label(page, text="", bg=_BG, fg="#C92A2A",
                                   font=("Microsoft YaHei", 9))
        self._gen_error.pack(anchor="w")

        threading.Thread(target=self._generation_work, daemon=True).start()

    def _generation_work(self):
        def progress(frac, stage, preview):
            def _ui():
                if self._closing:
                    return
                self._bar["value"] = frac * 100
                self._pct_lbl.config(text="%d%%" % round(frac * 100))
                self._stage_lbl.config(text=stage)
                if preview:
                    from PIL import Image as PILImage, ImageTk
                    from io import BytesIO
                    img = PILImage.open(BytesIO(preview)).resize((96, 104))
                    bg = PILImage.new("RGBA", img.size, (255, 255, 255, 255))
                    bg.alpha_composite(img)
                    self._photo_refs["live"] = ImageTk.PhotoImage(bg)
                    self._live_lbl.config(image=self._photo_refs["live"],
                                          text="")
            self._post(_ui)

        try:
            result = generate_appearance(
                self._image_path, self._style_key(self._style_var.get()),
                self._name_var.get().strip() or "MyPet",
                appearance_dir(), progress)
        except Exception as e:
            self._post(lambda: self._gen_error.config(
                text="✗ 生成失败：%s" % str(e)[:100]))
            return
        self._post(lambda: self._finish_generation(result))

    def _finish_generation(self, result):
        if self._closing:
            return
        try:
            self.pet._apply_appearance(result["sheet"], result["config"])
        except Exception as e:
            self._gen_error.config(text="✗ 应用失败：%s" % str(e)[:100])
            return
        self._result = result
        self._show_step(3)

    # ---------- ④ 完成 ----------
    def _page_done(self, page):
        tk.Label(page, text="🎉 换装完成！", bg=_BG, fg=_TEXT,
                 font=("Microsoft YaHei", 16, "bold")).pack(anchor="w")
        tk.Label(page, text=(
            "新形象已自动应用，正在你的桌面上活动啦～\n"
            "· 左键点她可以体验全套新动作\n"
            "· 音乐跳舞（若已开启）也会用新形象跳舞\n"
            "· 想换回默认形象：右键 → 设置 → 其他 → 恢复默认形象"),
            bg=_BG, fg=_TEXT, font=("Microsoft YaHei", 10),
            justify="left").pack(anchor="w", pady=(6, 8))

        card = tk.Frame(page, bg=_CARD, highlightbackground=_BORDER,
                        highlightthickness=1)
        card.pack(fill="x")
        info = self._result or {}
        tk.Label(card, text="形象：%s\n动作：%s 组 × %s 帧\n风格：%s"
                 % (self._name_var.get(), info.get("anims", "—"),
                    info.get("frames", "—"),
                    self._style_var.get()),
                 bg=_CARD, fg=_SUB, font=("Microsoft YaHei", 9),
                 justify="left").pack(anchor="w", padx=12, pady=8)

        self._nav(page, back=False, next_label="完成",
                  next_cmd=self._close)

    # ---------- 底部导航 ----------
    def _nav(self, page, back=True, next_label="下一步", next_cmd=None):
        row = tk.Frame(page, bg=_BG)
        row.pack(fill="x", side="bottom", pady=(10, 0))
        if back:
            tk.Button(row, text="上一步", width=9, font=("Microsoft YaHei", 10),
                      relief="flat", bg=_CARD, fg=_SUB,
                      activebackground="#E9E2FD", activeforeground=_ACCENT,
                      cursor="hand2",
                      command=lambda: self._show_step(self._step - 1)
                      ).pack(side="right", padx=(8, 0))
        if next_cmd is not None:
            tk.Button(row, text=next_label, width=14,
                      font=("Microsoft YaHei", 10, "bold"), relief="flat",
                      bg=_ACCENT, fg="#FFFFFF", activebackground="#7C4DFF",
                      activeforeground="#FFFFFF", cursor="hand2",
                      command=next_cmd).pack(side="right")


def _styles():
    from .q_pet_converter import CHIBI_STYLES
    return CHIBI_STYLES


def _frosted(x, y, w, h):
    from hatch_pet import glass_ui
    return glass_ui.frosted_image(x, y, w, h)


def glass_title_h():
    from hatch_pet import glass_ui
    return glass_ui.TITLE_H
