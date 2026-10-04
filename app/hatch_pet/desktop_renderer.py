import json
import logging
import math
import queue
import random
import sys
import threading
import time
from pathlib import Path
from typing import Optional

tk = None
ImageTk = None

from PIL import Image

from .config import (
    CELL_WIDTH, CELL_HEIGHT, COLS, ROWS,
    ANIMATION_STATES, GAZE_DIRECTIONS,
)
from .animation_engine import (
    SpringAnimation, TransitionAnimator,
    interpolate,
)
from .random_mode import (
    RandomBehaviorEngine, RandomEffectTrigger,
    BEHAVIOR_PRESETS,
)
from .status_watcher import StatusWatcher, create_watcher

logger = logging.getLogger(__name__)


class _SynthEvent:
    """原生渲染层事件转发用的最小 Tk 事件替身。

    现有拖拽/菜单处理器只读 ``x_root`` / ``y_root``（全局左上原点坐标），
    其余字段按 Tk 事件惯例补齐。
    """

    def __init__(self, x_root, y_root):
        self.x = 0
        self.y = 0
        self.x_root = x_root
        self.y_root = y_root
        self.num = 1
        self.time = 0


def get_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "darwin":
        return "macos"
    else:
        return "linux"


PLATFORM = get_platform()
# 注意：PLATFORM 的值是 "macos"，而 sys.platform 的值才是 "darwin"。
# 判断平台一律用 PLATFORM / IS_* 常量，别再直接比 "darwin"。
IS_WINDOWS = PLATFORM == "windows"
IS_MACOS = PLATFORM == "macos"
IS_LINUX = PLATFORM == "linux"

if PLATFORM == "windows":
    try:
        import ctypes
        from ctypes import wintypes
        HAS_WIN32 = True
    except ImportError:
        HAS_WIN32 = False
else:
    HAS_WIN32 = False

# BUG-01（详见 macos_overlay 模块 docstring）：macOS Tk 的
# systemTransparent 画布不渲染任何 PhotoImage，宠物会整体不可见。
# 优先用原生 NSWindow 覆盖层保持全透明；无 PyObjC 时退回彩色卡片
# 模式（可见但非透明），保证宠物永不静默隐形。
# macos_overlay 在所有平台都可安全导入（Windows 上仅作为帧载体工厂，
# _frame_to_tk 的 Windows 分支同样依赖它），必须顶层无条件导入。
from . import macos_overlay
from . import apple_ui
from .float_panel import FloatPanel

if PLATFORM == "windows":
    TRANSPARENT_BG = "magenta"
    CARD_BG = None
else:
    TRANSPARENT_BG = "systemTransparent"
    CARD_BG = None if macos_overlay.AVAILABLE else "#F6F5F2"

_BUBBLE_THEMES = {
    "error":      {"bg": "#FFF5F5", "border": "#FF8787", "text": "#C92A2A"},
    "done":       {"bg": "#EBFBEE", "border": "#69DB7C", "text": "#2B8A3E"},
    "happy":      {"bg": "#EBFBEE", "border": "#69DB7C", "text": "#2B8A3E"},
    "greet":      {"bg": "#E7F5FF", "border": "#74C0FC", "text": "#1864AB"},
    "working":    {"bg": "#FFF9DB", "border": "#FFE066", "text": "#866A04"},
    "thinking":   {"bg": "#E7F5FF", "border": "#74C0FC", "text": "#1864AB"},
    "needsinput": {"bg": "#FFF4E6", "border": "#FFA94D", "text": "#A04A00"},
    "waiting":    {"bg": "#FFF4E6", "border": "#FFA94D", "text": "#A04A00"},
    "juggling":   {"bg": "#F3F0FF", "border": "#9775FA", "text": "#5F3DC4"},
    "loafing":    {"bg": "#FFF5F5", "border": "#FFA8A8", "text": "#C92A2A"},
    "sleeping":   {"bg": "#F8F9FA", "border": "#CED4DA", "text": "#495057"},
}
_BUBBLE_DEFAULT_THEME = {"bg": "#FFFFFF", "border": "#DEE2E6", "text": "#343A40"}
_BUBBLE_TRANSPARENT = "#F0F0F0"
_BUBBLE_FADE_STEPS = 5
_BUBBLE_FADE_INTERVAL = 30

class DesktopPet:

    def __init__(self,
                 spritesheet_path: str,
                 config_path: str,
                 random_preset: str = "playful",
                 start_x: int = 100,
                 start_y: int = 100,
                 scale: float = 1.0,
                 enable_tray: bool = True,
                 enable_watcher: bool = False,
                 status_path: str = "~/.hatch-pet/status.json",
                 events_path: str = "~/.hatch-pet/events.jsonl"):
        global tk, ImageTk
        import tkinter as _tk
        from PIL.ImageTk import PhotoImage as _ImageTk
        tk = _tk
        ImageTk = _ImageTk
        """
        Args:
            spritesheet_path: 精灵图路径
            config_path: pet.json 路径
            random_preset: 随机行为预设
            start_x/start_y: 初始位置
            scale: 缩放比例
            enable_tray: 是否启用系统托盘
            enable_watcher: 是否启用 AI agent 状态监听
            status_path: 状态文件路径（enable_watcher=True 时生效）
            events_path: 事件流文件路径（enable_watcher=True 时生效）
        """
        self.root = tk.Tk()
        self.root.title("Desktop Pet")
        self.scale = scale

        self.win_w = int(CELL_WIDTH * scale)
        self.win_h = int(CELL_HEIGHT * scale)

        self._setup_transparent_window()

        self.config = self._load_config(config_path)
        self.gif_dir = None
        self.gif_groups: dict[str, list[list]] = {}
        self._anim_gif_config: dict[str, list[str]] = {}
        self._anim_fps: dict[str, int] = {}
        if self.config.get("gifMode"):

            self.frames, self.gaze_frames, gif_size = self._load_gif_frames()
            if gif_size:
                self.win_w = int(gif_size[0] * scale)
                self.win_h = int(gif_size[1] * scale)
        else:

            self.frames, self.gaze_frames = self._load_spritesheet(spritesheet_path)

        self.current_anim = "idle"
        self.current_frame = 0
        self.animating = True
        self.anim_counter = 0
        self._anim_accumulator = 0.0
        self._anim_start_time = time.time()
        self._pool_rotate_s = 60.0
        self._rotateable_states = {"working", "thinking", "loafing"}

        self.spring_x = SpringAnimation(stiffness=0.12, damping=0.65)
        self.spring_y = SpringAnimation(stiffness=0.12, damping=0.65)
        self.transition = TransitionAnimator()

        self.follow_mode = False
        self.watch_mode = False
        self.follow_target_x: Optional[int] = None
        self.follow_target_y: Optional[int] = None
        self.current_gaze: Optional[str] = None

        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_offset_x = 0
        self.drag_offset_y = 0

        self._tk_queue = queue.Queue()
        self._closing = False
        self.root.after(100, self._drain_tk_queue)

        self._after_ids = set()
        _orig_after = self.root.after

        def _tracked_after(ms, fn, *args):
            holder = []

            def _run():
                if holder:
                    self._after_ids.discard(holder[0])
                fn(*args)

            aid = _orig_after(ms, _run)
            holder.append(aid)
            self._after_ids.add(aid)
            return aid

        self.root.after = _tracked_after

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.random_engine = RandomBehaviorEngine(
            preset=random_preset,
            screen_width=screen_w,
            screen_height=screen_h,
            pet_width=self.win_w,
            pet_height=self.win_h,
            on_anim_change=self._on_random_anim_change,
            on_move=self._on_random_move,
        )
        self.effect_trigger = RandomEffectTrigger()

        self.watcher: Optional[StatusWatcher] = None
        self._events_path = events_path
        if enable_watcher:
            self._start_watcher(status_path, events_path)

        self._bubble_active = False
        self._bubble_text_id = None
        self._bubble_bg_id = None
        self._bubble_timer = None
        self._bubble_win = None
        self._bubble_alpha = 0.0

        self._ctx_menu: Optional["tk.Menu"] = None
        self._ctx_menu_preset: Optional["tk.Menu"] = None
        self._idx_follow: int = 0
        self._idx_watch: int = 0
        self._idx_random: int = 0

        self.root.geometry(f"{self.win_w}x{self.win_h}+{start_x}+{start_y}")
        self.spring_x.reset(start_x)
        self.spring_y.reset(start_y)

        self.canvas = tk.Canvas(
            self.root,
            width=self.win_w,
            height=self.win_h,
            bg=CARD_BG or TRANSPARENT_BG,
            highlightthickness=0,
        )
        self.canvas.pack()
        self.image_id = self.canvas.create_image(
            self.win_w // 2, self.win_h // 2, anchor="center",
        )

        # ---- macOS 原生渲染层（BUG-01 修复）----
        # Tk 画布在此模式下不再负责显示（保持隐形），由 macos_overlay
        # 的原生 NSWindow 贴在正上方显示精灵帧并转发鼠标事件。
        self._overlay = None
        self._overlay_pil = None
        if IS_MACOS:
            if macos_overlay.AVAILABLE:
                try:
                    self._overlay = macos_overlay.MacPetOverlay(
                        self.win_w, self.win_h,
                        on_event=self._overlay_event,
                    )
                    self._overlay.sync_position(start_x, start_y)
                    self._overlay.show()
                except Exception:
                    logger.exception("原生渲染层创建失败，回退彩色卡片模式")
                    self._overlay = None
            if self._overlay is None:
                logger.warning(
                    "macOS 原生渲染层未启用（%r），回退彩色卡片模式；"
                    "如需透明效果请安装 pyobjc-framework-Cocoa",
                    getattr(macos_overlay, "_IMPORT_ERROR", "unavailable"),
                )
            else:
                # 记录当前显示帧的 PIL 源图（原生层取像素用）：
                # 包一层 itemconfig，孵化/眨眼/gaze 等任何直绘路径都能捕获
                _orig_itemconfig = self.canvas.itemconfig

                def _itemconfig(*args, **kw):
                    result = _orig_itemconfig(*args, **kw)
                    try:
                        if args and args[0] == self.image_id:
                            photo = kw.get("image")
                            if photo is None and len(args) > 2:
                                for i in range(1, len(args) - 1, 2):
                                    if str(args[i]) == "image":
                                        photo = args[i + 1]
                                        break
                            if photo is not None:
                                src = getattr(photo, "source", None)
                                if src is not None:
                                    self._overlay_pil = src
                    except Exception:
                        pass
                    return result

                self.canvas.itemconfig = _itemconfig

        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

        self.canvas.bind("<Button-3>", self._on_right_click)
        if IS_MACOS:
            self.canvas.bind("<Button-2>", self._on_right_click)

        # V1.0.9：菜单/气泡浮层可用性。macOS 无 PyObjC 时原生面板不可用，
        # 退回 V1.0.8 的矢量画布实现（该场景下唯一的透明方案）。
        self._panels_ok = not (IS_MACOS and not macos_overlay.AVAILABLE)
        self._panel_pump_scheduled = False

        self.root.bind("<Control-Shift-Alt-Key-P>", lambda e: self._restore_from_hidden())

        self.tray_icon = None
        if enable_tray:
            self._setup_tray()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._frame_count = 0
        self._fps_timer = 0
        self._fps = 0

        self.root.after(16, self._game_loop)

    def _setup_transparent_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=CARD_BG or TRANSPARENT_BG)

        if PLATFORM == "windows":

            self.root.attributes("-transparentcolor", "magenta")
        else:

            try:
                self.root.attributes("-transparent", True)
            except tk.TclError:
                pass

        if PLATFORM == "windows" and HAS_WIN32:
            try:
                hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())

                GWL_EXSTYLE = -20
                WS_EX_LAYERED = 0x00080000
                WS_EX_TOOLWINDOW = 0x00000080
                ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(
                    hwnd, GWL_EXSTYLE,
                    ex_style | WS_EX_LAYERED | WS_EX_TOOLWINDOW,
                )
            except Exception:
                pass

    def _setup_tray(self):
        try:
            self._setup_tray_pystray()
        except ImportError:
            logger = __import__('logging').getLogger(__name__)
            logger.info("pystray 未安装，跳过系统托盘设置。可执行 pip install pystray")

    def _setup_tray_pystray(self):
        try:
            import pystray
            from PIL import Image as PILImage, ImageDraw as PILImageDraw

            icon_img = PILImage.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = PILImageDraw.Draw(icon_img)
            draw.ellipse([8, 8, 56, 56], fill=(120, 160, 220, 255))
            draw.ellipse([20, 18, 44, 42], fill=(255, 255, 255, 255))
            draw.ellipse([24, 22, 34, 34], fill=(40, 40, 40, 255))
            draw.ellipse([36, 22, 46, 34], fill=(40, 40, 40, 255))

            menu = pystray.Menu(
                pystray.MenuItem("显示/隐藏", self._toggle_visibility, default=True),
                pystray.MenuItem("模式切换", pystray.Menu(
                    pystray.MenuItem("调皮模式", lambda: self._set_random_preset("playful")),
                    pystray.MenuItem("悠闲模式", lambda: self._set_random_preset("relaxed")),
                    pystray.MenuItem("好奇模式", lambda: self._set_random_preset("curious")),
                    pystray.MenuItem("活跃模式", lambda: self._set_random_preset("active")),
                )),
                pystray.MenuItem("跟随模式", self._toggle_follow_tray,
                                 checked=lambda item: self.follow_mode),
                pystray.MenuItem("观察模式", self._toggle_watch_tray,
                                 checked=lambda item: self.watch_mode),
                *self._extra_tray_items(),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit_from_tray),
            )

            self._tray = pystray.Icon(
                "DesktopPet", icon_img, "Desktop Pet", menu,
            )

            threading.Thread(target=self._tray.run, daemon=True).start()
        except Exception:
            pass

    def _post_to_main(self, fn):
        self._tk_queue.put(fn)

    def _extra_tray_items(self):
        return []

    def _drain_tk_queue(self):
        while True:
            try:
                fn = self._tk_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                logger.exception("main-thread task failed")
            if self._closing:
                return
        if not self._closing:
            self.root.after(100, self._drain_tk_queue)

    def _toggle_visibility(self, icon=None, item=None):
        self._post_to_main(self._do_toggle_visibility)

    def _do_toggle_visibility(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self._overlay_show()
            self.animating = True
            self.root.after(16, self._game_loop)
        else:
            self.root.withdraw()
            self._overlay_hide()
            self.animating = False

    def _set_random_preset(self, preset: str):
        self.random_engine.set_preset(preset)

    def _toggle_follow_tray(self, icon, item):
        self._post_to_main(self._toggle_follow)

    def _toggle_watch_tray(self, icon, item):
        self._post_to_main(self._toggle_watch)

    def _quit_from_tray(self, icon=None, item=None):
        self._post_to_main(self._quit)

    def _on_close(self):
        self._quit()

    def _quit(self):
        if self._closing:
            return
        self._closing = True
        self.animating = False
        self._overlay_hide()
        ov = self._overlay
        if ov is not None:
            try:
                ov.close()
            except Exception:
                pass
            self._overlay = None

        for aid in list(self._after_ids):
            try:
                self.root.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()

        tray = getattr(self, "_tray", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        try:
            self.root.destroy()
        except Exception:
            pass

    def _load_config(self, path: str) -> dict:
        path = Path(path)
        if not path.exists():
            return {
                "animations": [
                    {"name": s["name"], "row": s["row"],
                     "frameCount": 8, "fps": s.get("fps", 6),
                     "repeat": s.get("repeat", True)}
                    for s in ANIMATION_STATES
                ],
                "gazes": GAZE_DIRECTIONS,
            }
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_spritesheet(self, path: str):
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"精灵图未找到: {path}")

        sheet = Image.open(path).convert("RGBA")
        anim_frames = {}
        gaze_frames = {}

        sprite_cfg = self.config.get("sprite", {})
        cell_w = sprite_cfg.get("cell", {}).get("width", CELL_WIDTH)
        cell_h = sprite_cfg.get("cell", {}).get("height", CELL_HEIGHT)
        cols_max = sprite_cfg.get("cols", COLS)

        anims = self.config.get("animations", [])
        for anim in anims:
            name = anim.get("name", "idle")
            row = anim.get("row", 0)
            count = anim.get("frameCount", 8)
            frame_list = []
            for col in range(min(count, cols_max)):
                x = col * cell_w
                y = row * cell_h
                cell = sheet.crop((x, y, x + cell_w, y + cell_h))
                if self.scale != 1.0:
                    cell = cell.resize(
                        (self.win_w, self.win_h), Image.LANCZOS
                    )
                frame_list.append(macos_overlay.make_source_photo(
                    cell, keep_source=IS_MACOS))
            anim_frames[name] = frame_list

        gazes = self.config.get("gazes", [])
        for gaze in gazes:
            name = gaze.get("name")
            row = gaze.get("row", 9)
            col = gaze.get("col", 0)
            x = col * cell_w
            y = row * cell_h
            cell = sheet.crop((x, y, x + cell_w, y + cell_h))
            if self.scale != 1.0:
                cell = cell.resize((self.win_w, self.win_h), Image.LANCZOS)
            gaze_frames[name] = macos_overlay.make_source_photo(
                cell, keep_source=IS_MACOS)

        return anim_frames, gaze_frames

    def _load_gif_frames(self):
        from PIL import Image as PILImage

        config = self.config
        gif_dir = Path(config.get("gifDir", "."))
        if not gif_dir.is_absolute():
            gif_dir = Path.cwd() / gif_dir
        self.gif_dir = gif_dir

        self._anim_gif_config = {}
        for anim in config.get("animations", []):
            name = anim.get("name", "idle")
            gif_names = anim.get("gif")
            if not gif_names:
                continue
            if isinstance(gif_names, str):
                gif_names = [gif_names]
            self._anim_gif_config[name] = gif_names

        anim_frames = {}
        gif_size = None
        target_size = None

        idle_gif_names = self._anim_gif_config.get("idle", [])
        for gif_name in idle_gif_names:
            gif_path = gif_dir / gif_name
            if not gif_path.exists():
                logger.warning(f"GIF 文件不存在: {gif_path}")
                continue

            try:
                img = PILImage.open(gif_path)
                if gif_size is None:
                    gif_size = img.size
                    target_size = (
                        int(gif_size[0] * self.scale),
                        int(gif_size[1] * self.scale),
                    )

                total = 0
                try:
                    while True:
                        img.seek(total)
                        total += 1
                except EOFError:
                    pass

                if total == 0:
                    continue

                group_frames = []
                for i in range(total):
                    img.seek(i)
                    frame = img.convert("RGBA")
                    if target_size and frame.size != target_size:
                        frame = frame.resize(target_size, PILImage.LANCZOS)
                    tk_frame = self._frame_to_tk(frame)
                    group_frames.append(tk_frame)

                self._anim_fps["idle"] = self._calc_gif_fps(gif_path)

                self.gif_groups["idle"] = [group_frames]
                anim_frames["idle"] = group_frames
                logger.info(f"  加载 idle GIF: {gif_name} ({total} 帧)")

            except Exception as e:
                logger.warning(f"加载 idle GIF 失败 {gif_path}: {e}")

        if gif_size is None:
            for name, gif_names in self._anim_gif_config.items():
                if name == "idle":
                    continue
                for gif_name in gif_names:
                    gif_path = gif_dir / gif_name
                    if gif_path.exists():
                        try:
                            img = PILImage.open(gif_path)
                            gif_size = img.size
                            target_size = (
                                int(gif_size[0] * self.scale),
                                int(gif_size[1] * self.scale),
                            )
                            break
                        except Exception:
                            continue
                if gif_size:
                    break

        gaze_frames = {}

        return anim_frames, gaze_frames, gif_size

    @staticmethod
    def _calc_gif_fps(gif_path) -> int:
        from PIL import Image as PILImage
        try:
            img = PILImage.open(gif_path)
            total = 0
            durations = []
            try:
                while True:
                    img.seek(total)
                    durations.append(img.info.get("duration", 100))
                    total += 1
            except EOFError:
                pass
            if total > 0 and durations:
                avg = sum(durations) / len(durations)
                return max(1, round(1000 / avg)) if avg > 0 else 6
        except Exception:
            pass
        return 6

    def _frame_to_tk(self, frame):
        from PIL import Image as PILImage
        if PLATFORM != "windows":
            # macOS/Linux：真 alpha 交给渲染层合成（去紫边阈值化是
            # Windows -transparentcolor 色键方案的伴生步骤，真 alpha
            # 下反而会毁掉软边）
            if frame.mode != "RGBA":
                frame = frame.convert("RGBA")
            return macos_overlay.make_source_photo(
                frame, keep_source=IS_MACOS)
        r, g, b, a = frame.split()
        magenta_bg = PILImage.new("RGB", frame.size, (255, 0, 255))
        rgb = PILImage.merge("RGB", (r, g, b))
        composite = PILImage.composite(rgb, magenta_bg, a)
        return macos_overlay.make_source_photo(composite, keep_source=False)

    # ---- macOS 原生渲染层（BUG-01 修复）----

    def _overlay_sync(self):
        """每帧把当前帧与窗口位置推给原生渲染层（幂等，无变化即跳过）。"""
        ov = self._overlay
        if ov is None:
            return
        try:
            ov.sync_position(self.root.winfo_x(), self.root.winfo_y())
            if self._overlay_pil is not None:
                ov.set_frame(self._overlay_pil)
        except Exception:
            logger.exception("原生渲染层同步失败")

    def _overlay_event(self, kind, x, y, x_root, y_root):
        """原生渲染层 → Tk：复用既有拖拽/菜单逻辑。"""
        ev = _SynthEvent(x_root, y_root)
        if kind == "press":
            self._on_drag_start(ev)
        elif kind == "drag":
            self._on_drag_move(ev)
        elif kind == "release":
            self._on_drag_end(ev)
        elif kind == "right":
            self._on_right_click(ev)

    def _overlay_hide(self):
        if self._overlay is not None:
            try:
                self._overlay.hide()
            except Exception:
                pass

    def _overlay_show(self):
        if self._overlay is not None:
            try:
                self._overlay.show()
            except Exception:
                pass

    def _load_single_gif(self, name: str):
        from PIL import Image as PILImage

        gif_names = self._anim_gif_config.get(name)
        if not gif_names:
            logger.warning(f"按需加载失败: 未知动画 '{name}'")
            return

        gif_dir = self.gif_dir
        target_size = (self.win_w, self.win_h)
        all_frames = []
        groups = []

        for gif_name in gif_names:
            gif_path = gif_dir / gif_name
            if not gif_path.exists():
                logger.warning(f"GIF 文件不存在: {gif_path}")
                continue

            try:
                img = PILImage.open(gif_path)

                total = 0
                try:
                    while True:
                        img.seek(total)
                        total += 1
                except EOFError:
                    pass

                if total == 0:
                    continue

                group_frames = []
                for i in range(total):
                    img.seek(i)
                    frame = img.convert("RGBA")
                    if frame.size != target_size:
                        frame = frame.resize(target_size, PILImage.LANCZOS)
                    tk_frame = self._frame_to_tk(frame)
                    group_frames.append(tk_frame)
                    all_frames.append(tk_frame)

                self._anim_fps[name] = self._calc_gif_fps(gif_path)

                groups.append(group_frames)
                logger.info(f"  按需加载 '{name}': {gif_name} ({total} 帧)")

            except Exception as e:
                logger.warning(f"加载 GIF 失败 {gif_path}: {e}")

        if all_frames:
            if len(groups) > 1:
                self.gif_groups[name] = groups
            self.frames[name] = groups[0] if groups else all_frames
            logger.info(f"  → '{name}' 总计 {len(all_frames)} 帧，{len(groups)} 组")

    def _game_loop(self):
        if not self.animating:
            return

        dt = 0.016

        if not self.dragging:
            sx = self.spring_x.update(dt * 2)
            sy = self.spring_y.update(dt * 2)
            if not self.spring_x.is_settled or not self.spring_y.is_settled:
                self.root.geometry(f"+{int(sx)}+{int(sy)}")

        self.random_engine.update(dt)

        if self.watch_mode:
            self._update_watch()

        if self.follow_mode:
            self._update_follow(dt)

        self._render_frame()
        self._overlay_sync()

        if (self.current_anim in self._rotateable_states
                and self.current_anim in self.gif_groups
                and time.time() - self._anim_start_time >= self._pool_rotate_s):
            self._rotate_gif()

        if self._bubble_win:
            try:
                if hasattr(self._bubble_win, "size"):
                    bw, bh = self._bubble_win.size()
                else:
                    bw = self._bubble_win.winfo_width()
                    bh = self._bubble_win.winfo_height()
                bx, by, _, _ = self._bubble_position(bw, bh)
                if hasattr(self._bubble_win, "move"):
                    if self._bubble_win.position() != (bx, by):
                        self._bubble_win.move(bx, by)
                else:
                    self._bubble_win.geometry(f"+{bx}+{by}")
            except Exception:
                pass

        self._frame_count += 1
        self._fps_timer += dt

        self.root.after(16, self._game_loop)

    def _rotate_gif(self):
        groups = self.gif_groups.get(self.current_anim)
        if not groups or len(groups) < 2:
            return
        current = self.frames.get(self.current_anim)
        if current in groups:
            idx = (groups.index(current) + 1) % len(groups)
        else:
            idx = 0
        self.frames[self.current_anim] = groups[idx]
        self.current_frame = 0
        self.anim_counter = 0
        self._anim_start_time = time.time()
        logger.debug(f"GIF 轮换 '{self.current_anim}': 第 {idx + 1}/{len(groups)} 组")

    def _render_frame(self):

        if self.watch_mode and self.current_gaze:
            frame = self.gaze_frames.get(self.current_gaze)
            if frame:
                self.canvas.itemconfig(self.image_id, image=frame)
                return

        anim = self.frames.get(self.current_anim)
        if not anim:
            return

        frame = anim[self.current_frame]
        self.canvas.itemconfig(self.image_id, image=frame)

        fps = self._get_current_fps()
        frame_interval = 1.0 / fps
        self._anim_accumulator += 0.016
        while self._anim_accumulator >= frame_interval:
            self._anim_accumulator -= frame_interval
            self.current_frame += 1
            if self.current_frame >= len(anim):
                self.current_frame = 0

    def _get_current_fps(self) -> int:
        if self.current_anim in self._anim_fps:
            return self._anim_fps[self.current_anim]
        for a in self.config.get("animations", []):
            if a.get("name") == self.current_anim:
                return a.get("fps", 6)
        return 6

    def _update_follow(self, dt: float):
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()

        tx = mx - self.win_w // 2

        ty = my - self.win_h // 2 - 10

        self.follow_target_x = tx
        self.follow_target_y = ty

        self.spring_x.set_target(tx)
        self.spring_y.set_target(ty)

        cx = self.root.winfo_x()
        dx = tx - cx
        if abs(dx) > 15:
            self._switch_anim("running-right" if dx > 0 else "running-left")
        else:
            if self.current_anim in ("running-right", "running-left"):
                self._switch_anim("idle")

    def _update_watch(self):
        mx = self.root.winfo_pointerx()
        my = self.root.winfo_pointery()
        cx = self.root.winfo_x() + self.win_w // 2
        cy = self.root.winfo_y() + self.win_h // 2

        angle = math.degrees(math.atan2(mx - cx, cy - my))
        if angle < 0:
            angle += 360

        best_gaze = None
        best_diff = 999
        for gaze in self.config.get("gazes", []):
            g_angle = gaze.get("angle", 0)
            diff = abs(angle - g_angle)
            if diff > 180:
                diff = 360 - diff
            if diff < best_diff:
                best_diff = diff
                best_gaze = gaze.get("name")

        if best_gaze and best_gaze != self.current_gaze:
            self.current_gaze = best_gaze

    def _on_drag_start(self, event):
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._press_win_x = self.root.winfo_x()
        self._press_win_y = self.root.winfo_y()
        self._moved = False

        if self.follow_mode:
            self.follow_mode = False

    def _on_drag_move(self, event):
        dx = event.x_root - self._press_x
        dy = event.y_root - self._press_y
        if not self._moved and (abs(dx) + abs(dy) > 4):
            self._moved = True
            self.dragging = True
        if self._moved:
            new_x = self._press_win_x + dx
            new_y = self._press_win_y + dy
            self.root.geometry(f"+{new_x}+{new_y}")
            self.spring_x.reset(new_x)
            self.spring_y.reset(new_y)
            self.random_engine.current_x = new_x
            self.random_engine.current_y = new_y

    def _on_drag_end(self, event):
        if self._moved:
            self.dragging = False
            self._switch_anim("idle")
            return

        self._show_left_menu(event)

    def _show_left_menu(self, event):
        """左键动画菜单：Windows 用 Apple 风格列表面板；macOS 系统原生
        弹出菜单本就是 Apple 风格，继续沿用。"""
        anims = self.config.get("animations", [])

        if self._panels_ok and IS_WINDOWS:
            rows, acts = [], []
            for anim in anims:
                name = anim.get("name", "")
                label = anim.get("label", name)
                rows.append((apple_ui.anim_icon(name), label))
                acts.append(name)
            rows.append(("sep", ""))
            acts.append(None)
            rows.append(("quit", "退出"))
            acts.append("quit")

            art = apple_ui.ListMenuArt(rows)
            x, y = self._clamp_panel_pos(event.x_root - 6, event.y_root - 8,
                                         *art.size)
            panel = FloatPanel(self.root, art.image, x, y,
                               on_click=lambda px, py:
                                   self._list_menu_click(px, py, acts),
                               on_move=lambda px, py:
                                   self._list_menu_move(px, py, art),
                               on_escape=self._close_left_menu,
                               on_focus_out=self._close_left_menu,
                               key=True)
            panel.focus()
            self._left_menu_panel = panel
            self._left_menu_art = art
            self._ensure_panel_pump()
            return

        menu = tk.Menu(self.root, tearoff=0)
        self._left_menu = menu
        for anim in anims:
            name = anim.get("name", "")
            label = anim.get("label", name)
            menu.add_command(
                label=label,
                command=lambda n=name: self._switch_anim(n, force=True),
            )
        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _list_menu_click(self, x, y, acts):
        art = getattr(self, "_left_menu_art", None)
        panel = getattr(self, "_left_menu_panel", None)
        if art is None or panel is None or not panel.alive():
            return
        idx = art.hit(x, y)
        if idx is None:
            self._close_left_menu()
            return
        act = acts[idx]
        self._close_left_menu()
        if act == "quit":
            self._quit()
        elif act is not None:
            self._switch_anim(act, force=True)

    def _list_menu_move(self, x, y, art):
        panel = getattr(self, "_left_menu_panel", None)
        if panel is None or not panel.alive():
            return
        idx = art.hit(x, y)
        if idx == getattr(self, "_left_menu_hot", "sentinel"):
            return
        self._left_menu_hot = idx
        panel.set_image(art.hover_images.get(idx, art.image)
                        if idx is not None else art.image)

    def _close_left_menu(self):
        panel = getattr(self, "_left_menu_panel", None)
        if panel is not None:
            panel.close()
        self._left_menu_panel = None
        self._left_menu_art = None
        self._left_menu_hot = None

    def _clamp_panel_pos(self, x, y, w, h):
        """把 (x, y) 尺寸 (w, h) 的面板钳制在宠物所在显示器工作区内。"""
        wa_l, wa_t, wa_r, wa_b = self._monitor_workarea()
        margin = 2
        x = max(wa_l + margin, min(x, wa_r - w - margin))
        y = max(wa_t + margin, min(y, wa_b - h - margin))
        return x, y

    def _ensure_panel_pump(self):
        """开启原生面板事件泵（每 30ms 把 macOS 原生层入队的事件
        在 Tk 主循环上下文里派发；Windows Tk 直调路径不经过队列）。"""
        if self._panel_pump_scheduled:
            return
        self._panel_pump_scheduled = True
        self.root.after(30, self._drain_panels)

    def _drain_panels(self):
        self._panel_pump_scheduled = False
        alive = False
        for attr in ("_radial_panel", "_left_menu_panel", "_bubble_win"):
            p = getattr(self, attr, None)
            if p is None or not hasattr(p, "pump_events"):
                continue
            try:
                if p.alive():
                    alive = True
                    p.pump_events()
            except Exception:
                logger.exception("面板事件派发失败 (%s)", attr)
        if alive:
            self._ensure_panel_pump()

    def _hide_to_tray(self):
        self.animating = False
        self.root.withdraw()
        self._overlay_hide()
        if getattr(self, "_tray", None) is None:
            logger.info("窗口已隐藏，按 Ctrl+Shift+Alt+P 恢复")

    def _restore_from_hidden(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self._overlay_show()
            self.animating = True
            self.root.after(16, self._game_loop)
            logger.info("窗口已恢复")

    def _menu_items(self):
        """右键扇形菜单项：(图标 key, 标签, 动作)。子类可扩展。"""
        items = [("follow", "跟随", self._toggle_follow)]
        if not self.config.get("gifMode"):
            items.append(("watch", "观察", self._toggle_watch))
        items += [
            ("activity", "活动", self._cycle_behavior),
            ("hide", "隐藏", self._hide_to_tray),
            ("quit", "退出", self._quit),
        ]
        return items

    def _on_menu_open(self):
        """菜单打开前钩子（子类用于交互计时等）。"""

    def _on_right_click(self, event):
        if getattr(self, "_radial_panel", None) and self._radial_panel.alive():
            self._close_radial()
            return
        self._on_menu_open()

        if not self._panels_ok:
            self._show_radial_canvas(event)
            return

        items = self._menu_items()
        art = apple_ui.RadialMenuArt([k for k, _, _ in items])
        # 扇形圆心放在宠物顶边中点略上方（与旧版视觉一致）
        px, py = self.root.winfo_x(), self.root.winfo_y()
        pet_cx = px + self.win_w // 2
        fan_cy_local = art.size[1] - art.btn_r - 20  # 画内扇形圆心 y
        x = pet_cx - art.size[0] // 2
        y = py - 43 - fan_cy_local
        x, y = self._clamp_panel_pos(x, y, *art.size)

        panel = FloatPanel(self.root, art.image, x, y,
                           on_click=self._radial_on_click,
                           on_move=self._radial_on_move,
                           on_escape=self._close_radial,
                           on_focus_out=self._close_radial,
                           key=True)
        panel.focus()
        self._radial_panel = panel
        self._radial_art = art
        self._radial_actions = [act for _, _, act in items]
        self._radial_hot = None
        self._ensure_panel_pump()

    def _radial_on_click(self, x, y):
        art = getattr(self, "_radial_art", None)
        panel = getattr(self, "_radial_panel", None)
        if art is None or panel is None or not panel.alive():
            return
        idx = art.hit(x, y)
        if idx is None:
            self._close_radial()          # 点到面板空白处 → 收起
            return
        act = self._radial_actions[idx]
        self._close_radial()
        logger.info("radial 点击: %s", getattr(act, "__name__", act))
        try:
            act()
        except Exception as e:
            logger.exception(f"radial 菜单项执行失败: {e}")

    def _radial_on_move(self, x, y):
        art = getattr(self, "_radial_art", None)
        panel = getattr(self, "_radial_panel", None)
        if art is None or panel is None or not panel.alive():
            return
        idx = art.hit(x, y)
        if idx == getattr(self, "_radial_hot", "sentinel"):
            return
        self._radial_hot = idx
        if idx is None:
            panel.set_image(art.image)
        else:
            panel.set_image(art.hover_images.get(idx, art.image))

    def _close_radial(self):
        panel = getattr(self, "_radial_panel", None)
        if panel is not None:
            panel.close()
        self._radial_panel = None
        self._radial_art = None
        self._radial_actions = None
        self._radial_hot = None
        # 画布回退窗口一并清理
        win = getattr(self, "_radial_win", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
            self._radial_win = None
            self._radial_canvas = None

    # ------------------------------------------------------------------
    # 画布回退（macOS 无 PyObjC 时的 V1.0.8 行为；矢量元素不受 BUG-01 影响）
    # ------------------------------------------------------------------
    def _show_radial_canvas(self, event):
        items = self._menu_items()
        n = len(items)
        radius = 70
        btn_r = 22

        start_a, end_a = 180, 360
        cx = self.win_w // 2

        win_size = (radius + btn_r) * 2 + 10
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=TRANSPARENT_BG)
        try:
            if PLATFORM == "windows":
                win.attributes("-transparentcolor", "magenta")
            else:
                win.attributes("-transparent", True)
        except tk.TclError:
            pass

        px = self.root.winfo_x()
        py = self.root.winfo_y()
        win_x = px + cx - win_size // 2
        win_y = py - radius - btn_r - 5
        win.geometry(f"{win_size}x{win_size}+{win_x}+{win_y}")

        cv = tk.Canvas(win, width=win_size, height=win_size,
                       bg=TRANSPARENT_BG, highlightthickness=0)
        cv.pack()

        local_cx = win_size // 2
        local_cy = win_size - btn_r - 5

        for i, it in enumerate(items):
            a = math.radians(start_a + (end_a - start_a) * (i / (n - 1) if n > 1 else 0.5))
            bx = local_cx + radius * math.cos(a)
            by = local_cy + radius * math.sin(a)

            cv.create_oval(bx - btn_r, by - btn_r, bx + btn_r, by + btn_r,
                           fill="#FFFFFF", outline="#888888", width=2,
                           tags=f"btn{i}")
            cv.create_text(bx, by - 4, text=apple_ui.MENU_LABELS.get(it[0], it[1]),
                           font=("PingFang SC" if IS_MACOS else "Microsoft YaHei", 10),
                           fill="#1D1D1F", tags=f"btn{i}")
            cv.tag_bind(f"btn{i}", "<Button-1>",
                        lambda e, act=it[2]: self._radial_click(act))

        self._radial_win = win
        self._radial_canvas = cv

        cv.bind("<Button-1>", lambda e: self._close_radial() if not self._radial_hit_btn(e) else None)
        win.bind("<Escape>", lambda e: self._close_radial())
        win.bind("<FocusOut>", lambda e: self._close_radial())
        win.focus_set()

    def _radial_hit_btn(self, event):
        cv = getattr(self, "_radial_canvas", None)
        if cv is None:
            return False
        return "current" in cv.gettags(cv.find_closest(event.x, event.y))

    def _radial_click(self, act):
        logger.info(f"radial 点击: {getattr(act, '__name__', act)}")
        self._close_radial()
        try:
            act()
        except Exception as e:
            logger.exception(f"radial 菜单项执行失败: {e}")

    def _toggle_follow(self):
        self.follow_mode = not self.follow_mode
        if self.follow_mode:
            self.watch_mode = False

    def _toggle_watch(self):
        self.watch_mode = not self.watch_mode
        if self.watch_mode:
            self.follow_mode = False
        if not self.watch_mode:
            self.current_gaze = None

    def _cycle_behavior(self):
        if not self.random_engine.enabled:
            self.random_engine.enabled = True
            self.random_engine.set_preset("playful")
            self._show_bubble("活动: 调皮模式", "idle")
        else:
            presets = ["playful", "relaxed", "curious", "active"]
            current = self.random_engine.preset_name
            idx = presets.index(current) if current in presets else 0
            if idx + 1 >= len(presets):

                self.random_engine.enabled = False
                self._show_bubble("活动: 已关闭", "idle")
            else:
                next_preset = presets[(idx + 1) % len(presets)]
                self.random_engine.set_preset(next_preset)
                self._show_bubble(f"活动: {self.random_engine.preset['name']}", "idle")

    def _set_random_preset(self, preset: str):
        self.random_engine.set_preset(preset)

    def _switch_anim(self, name: str, force: bool = False):
        if not force and name == self.current_anim:
            return
        old = self.current_anim
        self.current_anim = name
        self.current_frame = 0
        self.anim_counter = 0
        self._anim_start_time = time.time()

        if name not in self.frames:
            if name not in self._anim_gif_config:
                self.current_anim = old
                return
            self._load_single_gif(name)

        if name in self.gif_groups:
            groups = self.gif_groups[name]
            chosen = random.choice(groups)
            self.frames[name] = chosen
            logger.debug(f"随机切换 '{name}': 选第 {groups.index(chosen) + 1}/{len(groups)} 组 ({len(chosen)} 帧)")

        self._render_frame()

    def _on_random_anim_change(self, anim_name: str):

        if self.config.get("gifMode") and anim_name not in self._anim_gif_config:
            gif_states = list(self._anim_gif_config.keys())
            anim_name = random.choice(gif_states) if gif_states else "idle"
        self._switch_anim(anim_name)

    def _on_random_move(self, x: int, y: int):
        self.spring_x.set_target(x)
        self.spring_y.set_target(y)

    def _start_watcher(self, status_path: str, events_path: str = "~/.hatch-pet/events.jsonl"):
        self.watcher = create_watcher(
            status_path=status_path,
            events_path=events_path,
            pet=self,
            auto_start=True,
        )
        logger.info(f"AI Agent 状态监听已启动: status={status_path}, events={events_path}")

    def _monitor_workarea(self):
        try:
            import ctypes

            class _RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            class _MONINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint),
                            ("rcMonitor", _RECT), ("rcWork", _RECT),
                            ("dwFlags", ctypes.c_uint)]

            user32 = ctypes.WinDLL("user32")
            user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.GetAncestor.restype = ctypes.c_void_p
            user32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p,
                                               ctypes.POINTER(_MONINFO)]
            user32.GetMonitorInfoW.restype = ctypes.c_int

            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            hmon = user32.MonitorFromWindow(hwnd, 1)
            mi = _MONINFO()
            mi.cbSize = ctypes.sizeof(_MONINFO)
            if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                return (mi.rcWork.left, mi.rcWork.top,
                        mi.rcWork.right, mi.rcWork.bottom)
        except Exception:
            pass
        try:
            return (0, 0, self.root.winfo_screenwidth(),
                    self.root.winfo_screenheight())
        except Exception:
            return (0, 0, 1920, 1080)

    def _bubble_position(self, total_w, total_h):
        """计算气泡位置：优先宠物上方，放不下则下方；四边钳制在
        宠物所在显示器的工作区内（避开任务栏），并返回箭头应指向的
        宠物中心 x 坐标。"""
        px = self.root.winfo_x()
        py = self.root.winfo_y()
        wa_l, wa_t, wa_r, wa_b = self._monitor_workarea()
        margin = 4
        x = px + (self.win_w - total_w) // 2
        x = max(wa_l + margin, min(x, wa_r - total_w - margin))
        y = py - total_h - 2
        below = False
        if y < wa_t + margin:
            y = py + self.win_h + 2
            below = True
        if y + total_h > wa_b - margin:
            y = wa_b - total_h - margin
            if y < wa_t + margin:
                y = wa_t + margin
        pet_cx = px + self.win_w // 2
        return x, y, below, pet_cx

    def _show_bubble(self, msg, state=""):
        self.root.after(0, self._do_show_bubble, msg, state)

    def _do_show_bubble(self, msg, state=""):
        try:
            self._hide_bubble_immediate()
        except Exception as e:
            self.root.title(f"BubbleErr: {e}")
        if self._bubble_timer:
            self.root.after_cancel(self._bubble_timer)
            self._bubble_timer = None

        if len(msg) > 60:
            msg = msg[:57] + "\u2026"

        if not self._panels_ok:
            self._do_show_bubble_canvas(msg, state)
            return

        art = apple_ui.BubbleArt(msg, state)
        total_w, total_h = art.size
        bubble_x, bubble_y, below, pet_cx = self._bubble_position(total_w,
                                                                  total_h)
        img = art.render(pet_cx - bubble_x,
                         side="top" if below else "bottom")

        panel = FloatPanel(self.root, img, bubble_x, bubble_y)
        self._bubble_win = panel
        self._bubble_alpha = 0.0
        self._ensure_panel_pump()

        self._bubble_fade_in(0)

        self._bubble_timer = self.root.after(3000, self._hide_bubble)

    def _do_show_bubble_canvas(self, msg, state=""):
        """画布气泡回退（macOS 无 PyObjC；矢量元素不受 BUG-01 影响）。"""
        theme = _BUBBLE_THEMES.get(state, _BUBBLE_DEFAULT_THEME)
        bg_color = theme["bg"]
        border_color = theme["border"]
        text_color = theme["text"]

        max_w = 260
        pad_x = 16
        pad_y = 10
        radius = 10
        arrow_w = 14
        arrow_h = 7

        import tkinter.font as _tf
        font = _tf.Font(family="PingFang SC" if IS_MACOS
                        else "Microsoft YaHei", size=10)
        line_h = font.metrics("linespace")

        remain = msg
        lines = []
        while remain:
            for i in range(len(remain), 0, -1):
                if font.measure(remain[:i]) <= max_w - pad_x * 2:
                    lines.append(remain[:i])
                    remain = remain[i:]
                    break
            else:
                lines.append(remain)
                remain = ""

        text_w = max(font.measure(l) for l in lines) if lines else 0
        text_h = len(lines) * line_h
        bw = min(max(text_w + pad_x * 2, 50), max_w)
        bh = max(text_h + pad_y * 2, 32)

        shadow_dx, shadow_dy = 2, 3
        total_w = bw + shadow_dx + 4
        total_h = bh + arrow_h + shadow_dy + 4

        bubble_x, bubble_y, below, pet_cx = self._bubble_position(total_w, total_h)

        bubble_win = tk.Toplevel(self.root)
        bubble_win.overrideredirect(True)
        bubble_win.attributes("-topmost", True)
        bubble_bg = _BUBBLE_TRANSPARENT if PLATFORM == "windows" else TRANSPARENT_BG
        try:
            if PLATFORM == "windows":
                bubble_win.attributes("-transparentcolor", _BUBBLE_TRANSPARENT)
            else:
                bubble_win.attributes("-transparent", True)
        except Exception:
            pass
        bubble_win.configure(bg=bubble_bg)
        bubble_win.geometry(f"{total_w}x{total_h}+{bubble_x}+{bubble_y}")
        bubble_win.lift()
        try:
            bubble_win.attributes("-alpha", 0.0)
        except Exception:
            pass

        canvas = tk.Canvas(bubble_win, width=total_w, height=total_h,
                           bg=bubble_bg, highlightthickness=0)
        canvas.pack()

        bx1, by1 = 2, 2
        bx2, by2 = bx1 + bw - 1, by1 + bh - 1
        arrow_cx = pet_cx - bubble_x
        arrow_cx = max(bx1 + arrow_w + 2, min(arrow_cx, bx2 - arrow_w - 2))
        arrow_side = "top" if below else "bottom"

        bubble_pts = self._bubble_polygon(bx1, by1, bx2, by2, radius,
                                          arrow_w, arrow_h, arrow_cx, arrow_side)

        for dx, dy, sc in [(3, 4, "#E0E0E0"), (2, 3, "#D5D5D5"), (1, 1, "#C8C8C8")]:
            shadow_pts = self._offset_pts(bubble_pts, dx, dy)
            canvas.create_polygon(shadow_pts, fill=sc, outline="")

        canvas.create_polygon(bubble_pts, fill=bg_color, outline=border_color, width=1.5)

        for i, line in enumerate(lines):
            canvas.create_text(
                (bx1 + bx2) // 2,
                by1 + pad_y + i * line_h + line_h // 2,
                text=line, anchor="center", fill=text_color,
                font=("PingFang SC" if IS_MACOS else "Microsoft YaHei", 10, "normal")
            )

        self._bubble_win = bubble_win
        self._bubble_alpha = 0.0

        self._bubble_fade_in(0)

        self._bubble_timer = self.root.after(3000, self._hide_bubble)

    @staticmethod
    def _bubble_polygon(x1, y1, x2, y2, r, aw, ah, ax, side="bottom"):
        pts = []

        for a in range(180, 271, 15):
            rad = math.radians(a)
            pts.append(x1 + r + r * math.cos(rad))
            pts.append(y1 + r + r * math.sin(rad))

        pts.append(x2 - r)
        pts.append(y1)

        if side == "top":
            aw2 = aw // 2
            pts.extend([ax - aw2, y1, ax, y1 - ah, ax + aw2, y1])

        for a in range(270, 361, 15):
            rad = math.radians(a)
            pts.append(x2 - r + r * math.cos(rad))
            pts.append(y1 + r + r * math.sin(rad))

        pts.append(x2)
        pts.append(y2 - r)

        for a in range(0, 91, 15):
            rad = math.radians(a)
            pts.append(x2 - r + r * math.cos(rad))
            pts.append(y2 - r + r * math.sin(rad))

        if side == "bottom":
            aw2 = aw // 2
            pts.extend([ax + aw2, y2, ax, y2 + ah, ax - aw2, y2])

        for a in range(90, 181, 15):
            rad = math.radians(a)
            pts.append(x1 + r + r * math.cos(rad))
            pts.append(y2 - r + r * math.sin(rad))
        return pts

    @staticmethod
    def _offset_pts(pts, dx, dy):
        result = []
        for i in range(0, len(pts), 2):
            result.append(pts[i] + dx)
            result.append(pts[i + 1] + dy)
        return result

    def _bubble_fade_in(self, step):
        if not self._bubble_alive():
            return
        if step >= _BUBBLE_FADE_STEPS:
            self._bubble_set_alpha(255)
            self._bubble_alpha = 1.0
            return
        alpha = (step + 1) / _BUBBLE_FADE_STEPS
        self._bubble_set_alpha(int(alpha * 255))
        self._bubble_alpha = alpha
        self.root.after(_BUBBLE_FADE_INTERVAL, self._bubble_fade_in, step + 1)

    def _bubble_fade_out(self, step):
        if not self._bubble_alive():
            return
        if step >= _BUBBLE_FADE_STEPS:
            self._hide_bubble_immediate()
            return
        alpha = 1.0 - (step + 1) / _BUBBLE_FADE_STEPS
        self._bubble_set_alpha(int(alpha * 255))
        self.root.after(_BUBBLE_FADE_INTERVAL, self._bubble_fade_out, step + 1)

    def _bubble_alive(self):
        win = self._bubble_win
        if not win:
            return False
        if hasattr(win, "alive"):
            return win.alive()
        try:
            return bool(win.winfo_exists())
        except Exception:
            return False

    def _bubble_set_alpha(self, a255):
        win = self._bubble_win
        if not win:
            return
        if hasattr(win, "set_alpha"):
            win.set_alpha(a255)
        else:
            try:
                win.attributes("-alpha", a255 / 255.0)
            except Exception:
                pass

    def _hide_bubble(self):
        # 取消尚未触发的自动关闭定时器：手动提前关闭时若只置空句柄，
        # 定时器稍后仍会触发并把「下一个」气泡误当超时气泡淡出销毁
        # （V1.0.9 测试 M7→M8 序列实测暴露的潜在缺陷）。
        if self._bubble_timer:
            try:
                self.root.after_cancel(self._bubble_timer)
            except Exception:
                pass
            self._bubble_timer = None
        if self._bubble_win:
            self._bubble_fade_out(0)
        self._bubble_active = False

    def _hide_bubble_immediate(self):
        if self._bubble_win:
            win = self._bubble_win
            try:
                if hasattr(win, "close"):
                    win.close()
                else:
                    win.destroy()
            except Exception:
                pass
            self._bubble_win = None
        if self._bubble_timer:
            try:
                self.root.after_cancel(self._bubble_timer)
            except Exception:
                pass
            self._bubble_timer = None

    def run(self):

        if hasattr(self, "watcher") and self.watcher is not None:
            self.root.after(500, lambda: self._show_bubble("🐱 DesktopBuddy 上线，开始盯任务啦！", "greet"))
        self.root.mainloop()

def run_desktop(
    spritesheet: str = "output/spritesheet.webp",
    config: str = "output/pet.json",
    gif_path: Optional[str] = None,
    random_preset: str = "playful",
    scale: float = 1.0,
    enable_tray: bool = True,
    enable_watcher: bool = False,
    status_path: str = "~/.hatch-pet/status.json",
    events_path: str = "~/.hatch-pet/events.jsonl",
    start_x: Optional[int] = None,
    start_y: Optional[int] = None,
):
    global tk
    import tkinter as _tk
    tk = _tk

    temp = tk.Tk()
    temp.withdraw()
    if start_x is None:
        start_x = random.randint(50, temp.winfo_screenwidth() - 250)
    if start_y is None:
        start_y = random.randint(50, temp.winfo_screenheight() - 300)
    temp.destroy()

    if gif_path:
        from pathlib import Path as _Path
        import re as _re
        gif_abs = _Path(gif_path).resolve()

        if gif_abs.is_dir():

            gif_files = sorted(gif_abs.glob("*.gif"))
            if not gif_files:
                logger.error(f"目录中没有 GIF 文件: {gif_path}")
                return

            anim_groups: dict[str, list[str]] = {}
            for f in gif_files:
                stem = f.stem

                name = stem[4:] if stem.startswith("cat-") else stem

                state = _re.sub(r'-\d+$', '', name) if _re.search(r'-\d+$', name) else name
                anim_groups.setdefault(state, []).append(f.name)

            animations = []
            for state, files in anim_groups.items():
                gif_val = files[0] if len(files) == 1 else files
                animations.append({"name": state, "gif": gif_val, "fps": 6, "repeat": True})

            gif_config = {
                "gifMode": True,
                "gifDir": str(gif_abs),
                "animations": animations,
                "gazes": GAZE_DIRECTIONS,
            }
            logger.info(f"目录模式: 发现 {len(gif_files)} 个 GIF，{len(animations)} 个状态")
        else:

            gif_config = {
                "gifMode": True,
                "gifDir": str(gif_abs.parent),
                "animations": [
                    {
                        "name": "idle",
                        "gif": gif_abs.name,
                        "fps": 6,
                        "repeat": True,
                    }
                ],
                "gazes": GAZE_DIRECTIONS,
            }

        gif_parent = gif_abs if gif_abs.is_dir() else gif_abs.parent
        tmp_config = gif_parent / ".desktop-pet-tmp.json"
        with open(tmp_config, "w", encoding="utf-8") as f:
            json.dump(gif_config, f, ensure_ascii=False)
        config = str(tmp_config)

    pet = DesktopPet(
        spritesheet_path=spritesheet,
        config_path=config,
        random_preset=random_preset,
        start_x=start_x,
        start_y=start_y,
        scale=scale,
        enable_tray=enable_tray,
        enable_watcher=enable_watcher,
        status_path=status_path,
        events_path=events_path,
    )
    pet.run()
