# -*- coding: utf-8 -*-
"""float_panel — 跨平台「逐像素透明」浮层窗口（菜单 / 气泡等小面板用）。

为什么需要它：
    右键扇形菜单原先在 Toplevel 画布上以色键（Windows `-transparentcolor`
    洋红）抠透明。该属性是 Windows 专属——macOS 上静默失效，整个菜单窗
    口连底带按钮显示为一块洋红/紫色（V1.0.8 用户报告 BUG）。同时色键方
    案无法表现 Apple 风格的半透明与柔和阴影。
本模块按平台选择「真 alpha」载体：
    Windows  Tk Toplevel + UpdateLayeredWindow（预乘 BGRA DIB）。
             alpha=0 像素自动点击穿透；`-alpha` 渐隐改走混合常数。
    macOS    原生透明 NSWindow + NSImageView（macos_overlay.MacFloatPanel，
             与 BUG-01 宠物覆盖层同一套机制）。
    回退     上两者不可用时退回「色键画布」：RGBA 按阈值二值化后合成到
             键色上（Windows 键=洋红；其余平台键=浅灰）。可见但边缘无
             柔影、无半透明，功能等价。

对外只暴露一个类：FloatPanel( 常规窗口语义 )——
    panel = FloatPanel(root, image, x, y, on_click=..., on_move=...,
                       on_escape=..., on_focus_out=..., key=...)
    panel.set_image(pil) / panel.set_alpha(0~255) / panel.move(x, y)
    panel.alive() / panel.close()

on_click/on_move 的 (x, y) 为图内 1x 坐标；on_escape/on_focus_out 无参。
"""
import collections
import logging
import sys

from PIL import Image, ImageChops

from . import macos_overlay

logger = logging.getLogger(__name__)

PLATFORM = ("windows" if sys.platform == "win32"
            else "macos" if sys.platform == "darwin" else "linux")

_IS_WINDOWS = PLATFORM == "windows"
_IS_MACOS = PLATFORM == "macos"


# ---------------------------------------------------------------------------
# Windows：UpdateLayeredWindow
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes as wt

    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32

    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TOOLWINDOW = 0x00000080
    _WS_EX_TOPMOST = 0x00000008
    _ULW_ALPHA = 0x00000002
    _AC_SRC_OVER = 0
    _AC_SRC_ALPHA = 1
    _DIB_RGB_COLORS = 0

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class _BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte),
                    ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte)]

    class _BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    def _premultiplied_bgra(img):
        """PIL RGBA → 预乘 alpha 的 BGRA 字节（ULW 要求预乘）。"""
        img = img.convert("RGBA")
        r, g, b, a = img.split()
        r = ImageChops.multiply(r, a)
        g = ImageChops.multiply(g, a)
        b = ImageChops.multiply(b, a)
        # merge 成 (B, G, R, A) 带序后按 raw RGBA 顺序输出即 BGRA 字节流
        return Image.merge("RGBA", (b, g, r, a)).tobytes("raw", "RGBA")

    def _update_layered(hwnd, img, x=None, y=None, alpha=255):
        """把 RGBA 图推送到分层窗口。失败抛 OSError。"""
        w, h = img.size
        hdc_screen = _user32.GetDC(None)
        if not hdc_screen:
            raise OSError("GetDC(None) 失败")
        hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
        bmi = _BMIH()
        bmi.biSize = ctypes.sizeof(_BMIH)
        bmi.biWidth = w
        bmi.biHeight = -h          # 负高 = 自上而下行序，与 PIL 一致
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0      # BI_RGB
        bits = ctypes.c_void_p()
        try:
            hbm = _gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi),
                                          _DIB_RGB_COLORS,
                                          ctypes.byref(bits), None, 0)
            if not hbm or not bits:
                raise OSError("CreateDIBSection 失败")
            data = _premultiplied_bgra(img)
            ctypes.memmove(bits, data, len(data))
            prev = _gdi32.SelectObject(hdc_mem, hbm)
            pt_dst = _POINT(x, y) if x is not None else None
            size = _SIZE(w, h)
            pt_src = _POINT(0, 0)
            blend = _BLENDFUNCTION(_AC_SRC_OVER, 0, int(alpha), _AC_SRC_ALPHA)
            ok = _user32.UpdateLayeredWindow(
                hwnd, hdc_screen,
                ctypes.byref(pt_dst) if pt_dst else None,
                ctypes.byref(size), hdc_mem, ctypes.byref(pt_src),
                0, ctypes.byref(blend), _ULW_ALPHA)
            _gdi32.SelectObject(hdc_mem, prev)
            _gdi32.DeleteObject(hbm)
            if not ok:
                raise OSError(f"UpdateLayeredWindow 失败 err={ctypes.GetLastError()}")
        finally:
            _gdi32.DeleteDC(hdc_mem)
            _user32.ReleaseDC(None, hdc_screen)


class FloatPanel:
    """逐像素透明浮层。用法见模块 docstring。"""

    def __init__(self, root, image, x, y,
                 on_click=None, on_move=None, on_escape=None,
                 on_focus_out=None, key=False):
        self._root = root
        self._on_click = on_click
        self._on_move = on_move
        self._on_escape = on_escape
        self._on_focus_out = on_focus_out
        self._image = image
        self._alpha = 255
        self._closed = False
        self._hover_idx = None  # Windows 悬停去抖（由调用方管理亦可）
        # 原生层（macOS）事件队列：ObjC 回调内严禁直接调 Tk（Tcl 重入会
        # 触发 GIL 状态错乱直接 abort），只入队，由 pump_events() 在
        # Tk 主循环里取出派发（DesktopPet._drain_panels 每 30ms 调用）。
        self._events = collections.deque()

        if _IS_MACOS and macos_overlay.AVAILABLE:
            self._mode = "native"
            self._native = macos_overlay.MacFloatPanel(
                image.size[0], image.size[1],
                on_click=lambda x, y: self._queue("click", x, y),
                on_move=lambda x, y: self._queue("move", x, y),
                on_focus_out=lambda: self._queue("focusout"),
                key=key,
            )
            self._native.set_image(image)
            self._native.set_position(x, y)
            self._native.show(key=key)
            return

        # ---- Tk 窗口（Windows ULW / 通用色键回退）----
        import tkinter as tk
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        w, h = image.size
        win.geometry(f"{w}x{h}+{x}+{y}")
        self._win = win
        self._x, self._y = int(x), int(y)

        self._mode = "ulw" if (_IS_WINDOWS and self._try_ulw()) else "key"
        if self._mode == "key":
            self._build_key_canvas(image)

        win.bind("<Button-1>", self._tk_click)
        win.bind("<Motion>", self._tk_move)
        win.bind("<Escape>", lambda e: self._escape())
        win.bind("<FocusOut>", lambda e: self._focus_out())
        win.bind("<Destroy>", self._on_destroy, add="+")
        try:
            win.focus_set()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Windows ULW
    # ------------------------------------------------------------------
    def _try_ulw(self):
        try:
            self._win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self._win.winfo_id())
            if not hwnd:
                hwnd = self._win.winfo_id()
            self._hwnd = hwnd
            ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE,
                                   ex | _WS_EX_LAYERED | _WS_EX_TOOLWINDOW
                                   | _WS_EX_TOPMOST)
            _update_layered(self._hwnd, self._image, self._x, self._y,
                            self._alpha)
            logger.info("浮层走 UpdateLayeredWindow（真 alpha）")
            return True
        except Exception as e:
            logger.warning("UpdateLayeredWindow 不可用（%s），回退色键模式", e)
            return False

    # ------------------------------------------------------------------
    # 色键回退
    # ------------------------------------------------------------------
    def _build_key_canvas(self, image):
        import tkinter as tk
        key_rgb = (255, 0, 255) if _IS_WINDOWS else (240, 240, 240)
        self._win.configure(bg="#%02X%02X%02X" % key_rgb)
        if _IS_WINDOWS:
            try:
                self._win.attributes("-transparentcolor", "#%02X%02X%02X"
                                     % key_rgb)
            except tk.TclError:
                pass
        # 阈值二值化后贴到键色，避免半透明像素与键色混出彩边
        a = image.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        flat = Image.new("RGBA", image.size, key_rgb + (255,))
        flat.paste(image, (0, 0), a)
        from PIL import ImageTk
        self._photo = ImageTk.PhotoImage(flat, master=self._win)
        cv = tk.Canvas(self._win, width=image.size[0], height=image.size[1],
                       bg="#%02X%02X%02X" % key_rgb, highlightthickness=0)
        cv.pack()
        cv.create_image(0, 0, image=self._photo, anchor="nw")
        logger.info("浮层回退色键画布模式（key=#%02X%02X%02X）", *key_rgb)

    # ------------------------------------------------------------------
    # 事件桥
    # ------------------------------------------------------------------
    def _queue(self, kind, *args):
        """原生层回调入口：只入队，不碰 Tk（回调可能来自 ObjC 栈）。"""
        if not self._closed:
            self._events.append((kind, args))

    def pump_events(self):
        """在 Tk 主循环上下文中派发积压的原生层事件。"""
        while self._events and not self._closed:
            kind, args = self._events.popleft()
            if kind == "click" and self._on_click is not None:
                self._on_click(int(args[0]), int(args[1]))
            elif kind == "move" and self._on_move is not None:
                self._on_move(int(args[0]), int(args[1]))
            elif kind == "focusout" and self._on_focus_out is not None:
                self._on_focus_out()

    def _tk_click(self, event):
        if self._on_click and not self._closed:
            self._on_click(event.x, event.y)

    def _tk_move(self, event):
        if self._on_move and not self._closed:
            self._on_move(event.x, event.y)

    def _escape(self):
        if self._on_escape and not self._closed:
            self._on_escape()

    def _focus_out(self):
        if self._on_focus_out and not self._closed:
            self._on_focus_out()

    def _on_destroy(self, _e):
        self._closed = True
        if self._mode == "native" and getattr(self, "_native", None):
            self._native = None

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def alive(self):
        if self._closed:
            return False
        if self._mode == "native":
            return self._native is not None and self._native.alive()
        try:
            return bool(self._win.winfo_exists())
        except Exception:
            return False

    def set_image(self, image):
        self._image = image
        if self._closed:
            return
        if self._mode == "native":
            self._native.set_image(image)
        elif self._mode == "ulw":
            try:
                _update_layered(self._hwnd, image, alpha=self._alpha)
            except Exception as e:
                logger.warning("ULW set_image 失败: %s", e)

    def set_alpha(self, alpha):
        self._alpha = max(0, min(255, int(alpha)))
        if self._closed:
            return
        if self._mode == "native":
            self._native.set_alpha(self._alpha)
        elif self._mode == "ulw":
            try:
                _update_layered(self._hwnd, self._image, alpha=self._alpha)
            except Exception:
                pass
        else:
            try:
                self._win.attributes("-alpha", self._alpha / 255.0)
            except Exception:
                pass

    def move(self, x, y):
        self._x, self._y = int(x), int(y)
        if self._closed:
            return
        if self._mode == "native":
            self._native.set_position(x, y)
        elif self._mode == "ulw":
            try:
                _update_layered(self._hwnd, self._image, x=self._x, y=self._y,
                                alpha=self._alpha)
            except Exception:
                pass
        else:
            try:
                w, h = self._image.size
                self._win.geometry(f"{w}x{h}+{self._x}+{self._y}")
            except Exception:
                pass

    def size(self):
        return self._image.size

    def position(self):
        return self._x, self._y

    def focus(self):
        if self._mode != "native":
            try:
                self._win.focus_set()
            except Exception:
                pass
        # 原生层在 show(key=True) 时已抢键

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._mode == "native":
            if self._native is not None:
                self._native.close()
                self._native = None
            return
        try:
            self._win.destroy()
        except Exception:
            pass
