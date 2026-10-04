"""macOS 原生透明渲染层（修复 BUG-01：宠物窗口在 macOS 上完全不可见）。

背景（详见 docs/Vivian-Pet-macOS-V1.0.7-测试报告.md BUG-01，4 组对照实验）：
    macOS Tk 8.6 下，背景为 ``systemTransparent`` 的 canvas 不渲染任何
    PhotoImage（PIL ImageTk / Tk 原生 PNG、带不带 alpha 均验证失败；
    矢量元素正常）。app 原本的 ``-transparent`` + sysTrans 画布 +
    ``create_image`` 组合 → 精灵永远画不上 → 整窗只剩透明背景 → 不可见。

方案（本模块）：
    Tk 窗口继续承担逻辑与拖拽坐标，但不再负责显示（保持隐形）；另建一个
    原生 NSWindow（无边框 + 透明背景 + 悬浮层级）叠在 Tk 窗口正上方，
    由渲染循环把当前帧的 PIL RGBA 图画进 NSImageView；NSView 子类接管
    鼠标事件并换算成 Tk 全局坐标回调宿主。

    事件不走系统级点击穿透（``ignoresMouseEvents`` 在悬浮层级下实测
    不转发、``hitTest_→nil`` 亦然），而是覆盖层自己收事件后回调——
    确定性方案，与层级无关。

依赖：pyobjc-framework-Cocoa。缺失时 ``AVAILABLE=False``，调用方回退
「彩色卡片」模式（可见但非透明），保证宠物永远不会静默隐形。

⚠️ 初始化顺序：``NSApplication.sharedApplication()`` 必须在 ``tk.Tk()``
之后调用。顺序颠倒会触发 Tk 8.6 在新版 macOS 上的
``-[NSApplication macOSVersion]: unrecognized selector`` 崩溃
（Tk 的 GetRGBA 解析系统色时依赖 Tk 自己初始化的 NSApp）。
"""
import io
import logging
import sys

logger = logging.getLogger(__name__)

try:
    if sys.platform != "darwin":
        raise ImportError("仅 macOS 使用")
    import objc  # noqa: F401  （显式导入，便于缺失时给出一致报错）
    import AppKit as ak
    from Foundation import NSMakeRect
    AVAILABLE = True
    _IMPORT_ERROR = None
except Exception as _e:  # ImportError 或动态库加载失败
    AVAILABLE = False
    _IMPORT_ERROR = _e

# ---------------------------------------------------------------------------
# 帧载体：PhotoImage 携带 PIL 源图
# ---------------------------------------------------------------------------

_PhotoCls = None


def _photo_cls():
    global _PhotoCls
    if _PhotoCls is None:
        from PIL.ImageTk import PhotoImage

        class SourcePhoto(PhotoImage):
            """携带 PIL RGBA 源图的 PhotoImage。

            macOS 原生层需要源图取像素；``source`` 在不需要时为 None，
            避免 Windows 侧帧内存翻倍。
            """

            def __init__(self, pil, keep_source=True):
                PhotoImage.__init__(self, pil)
                self.source = pil if keep_source else None

        _PhotoCls = SourcePhoto
    return _PhotoCls


def make_source_photo(pil_image, keep_source=True):
    """生成携带 PIL 源图的 PhotoImage（所有平台通用）。"""
    return _photo_cls()(pil_image, keep_source)


if not AVAILABLE:  # 非 macOS / 无 PyObjC：只提供帧载体，其余为空壳
    class MacPetOverlay:  # noqa: D101 — 占位，调用方应先看 AVAILABLE
        def __init__(self, *a, **k):
            raise RuntimeError("macos_overlay 不可用: %r" % (_IMPORT_ERROR,))

    class _PetView:  # noqa: D101
        pass

else:

    # ------------------------------------------------------------------
    # 坐标换算（宠物覆盖层与浮层面板共用）
    # ------------------------------------------------------------------
    def _screen_frames():
        frames = []
        for s in ak.NSScreen.screens():
            f = s.frame()
            frames.append((f.origin.x, f.origin.y,
                           f.size.width, f.size.height))
        return frames or [(0, 0, 0, 0)]

    def tk_to_cocoa(x_tk, y_tk, win_h):
        """Tk 全局坐标(左上原点) → Cocoa 全局坐标(主屏左下原点)。"""
        frames = _screen_frames()
        mx, my, mw, mh = frames[0]
        for fx, fy, fw, fh in frames:
            top = (my + mh) - (fy + fh)   # 该屏在左上坐标系中的 y
            if fx <= x_tk < fx + fw and top <= y_tk < top + fh:
                return x_tk, fy + fh - (y_tk - top) - win_h
        return x_tk, mh - y_tk - win_h

    class _PetView(ak.NSImageView):
        """接管鼠标事件 → 换算 Tk 坐标 → 回调宿主。"""

        def mouseDown_(self, e):
            self.window() and self._owner_forward("press", e)

        def mouseDragged_(self, e):
            self._owner_forward("drag", e)

        def mouseUp_(self, e):
            self._owner_forward("release", e)

        def rightMouseDown_(self, e):
            self._owner_forward("right", e)

        @objc.python_method
        def _owner_forward(self, kind, e):
            owner = getattr(self, "_owner", None)
            if owner is not None:
                owner.forward_event(kind, e)

    class MacPetOverlay:
        """原生透明窗口：显示精灵帧 + 鼠标事件转发。

        参数
        ----
        width/height : 窗口尺寸（点，与 Tk 像素 1:1，无 Retina 缩放时）
        on_event     : callable(kind, x, y, x_root, y_root)
                       kind ∈ press/drag/release/right，
                       (x, y) 为 Tk 画布局部坐标，(x_root, y_root) 为
                       Tk 全局坐标（左上原点）。
        """

        def __init__(self, width, height, on_event=None):
            self._w = int(width)
            self._h = int(height)
            self._on_event = on_event
            self._x = 0          # Tk 全局坐标（左上原点）
            self._y = 0
            self._last_pil = None
            self._shown = False
            self._build()

        # ---- 窗口构建 ----
        def _build(self):
            # 前提：tk.Tk() 已创建（顺序见模块 docstring）
            ak.NSApplication.sharedApplication()
            win = ak.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, self._w, self._h), 0, 2, False)
            win.setOpaque_(False)
            win.setBackgroundColor_(ak.NSColor.clearColor())
            win.setHasShadow_(False)
            win.setReleasedWhenClosed_(False)
            try:
                win.setLevel_(ak.NSFloatingWindowLevel)
            except AttributeError:
                win.setLevel_(3)
            view = _PetView.alloc().initWithFrame_(
                NSMakeRect(0, 0, self._w, self._h))
            view._owner = self
            win.setContentView_(view)
            self._win = win
            self._view = view
            logger.info("macOS 原生渲染层已创建 (%dx%d)", self._w, self._h)

        # ---- 坐标换算 ----
        @staticmethod
        def _screen_frames():
            return _screen_frames()

        def _cocoa_point(self, x_tk, y_tk):
            return tk_to_cocoa(x_tk, y_tk, self._h)

        # ---- 显示 ----
        def set_frame(self, pil_frame):
            """更新显示帧（PIL RGBA）。"""
            if self._view is None or pil_frame is None:
                return
            w, h = pil_frame.size
            if (w, h) != (self._w, self._h):
                self._resize(w, h)
            if pil_frame is self._last_pil:
                return
            self._last_pil = pil_frame
            self._iv_set_image(pil_frame)
            self._redraw()

        def _iv_set_image(self, pil_frame):
            buf = io.BytesIO()
            pil_frame.save(buf, "PNG")
            data = ak.NSData.dataWithBytes_length_(buf.getvalue(),
                                                   len(buf.getvalue()))
            self._view.setImage_(ak.NSImage.alloc().initWithData_(data))

        def _resize(self, w, h):
            self._w, self._h = int(w), int(h)
            self._view.setFrame_(NSMakeRect(0, 0, self._w, self._h))
            self._win.setContentSize_((self._w, self._h))
            self._last_pil = None   # 尺寸变了，强制重画

        def sync_position(self, x_tk, y_tk):
            """把覆盖层对齐到 Tk 窗口位置（Tk 全局坐标，每帧调用）。"""
            if self._win is None:
                return
            if x_tk == self._x and y_tk == self._y:
                return
            self._x, self._y = int(x_tk), int(y_tk)
            cx, cy = self._cocoa_point(self._x, self._y)
            self._win.setFrameOrigin_((cx, cy))

        def _redraw(self):
            try:
                self._view.setNeedsDisplay_(True)
                self._win.display()
            except Exception:
                pass

        # ---- 显隐 ----
        def show(self):
            if self._win is not None and not self._shown:
                self._win.orderFrontRegardless()
                self._shown = True
                self._last_pil = None
                self.sync_position(self._x, self._y)

        def hide(self):
            if self._win is not None and self._shown:
                self._win.orderOut_(None)
                self._shown = False

        def close(self):
            if self._win is not None:
                try:
                    self._win.orderOut_(None)
                    self._win.close()
                except Exception:
                    pass
                self._win = None
                self._view = None

        # ---- 事件转发 ----
        def forward_event(self, kind, e):
            if self._on_event is None or self._win is None:
                return
            p = self._view.convertPoint_toView_(e.locationInWindow(), None)
            tx, ty = p.x, self._h - p.y          # 左下原点 → 左上原点
            x_root = self._x + tx
            y_root = self._y + ty
            try:
                self._on_event(kind, int(tx), int(ty),
                               int(x_root), int(y_root))
            except Exception:
                logger.exception("覆盖层事件转发失败 kind=%s", kind)

    # ------------------------------------------------------------------
    # 通用透明浮层面板（V1.0.9：Apple 风格菜单 / 气泡的显示载体）
    # ------------------------------------------------------------------
    _TRACKING_ENTERED_EXITED = 0x01
    _TRACKING_MOUSE_MOVED = 0x02
    _TRACKING_ACTIVE_ALWAYS = 0x80

    class _PanelView(ak.NSImageView):
        """接收点击 / 移动 → 换算图内坐标 → 回调宿主。

        注意：不要覆写 updateTrackingAreas——PyObjC 回调里用普通
        Python super() 会在 CATransaction 刷新期抛异常并直接 SIGILL
        （实测崩溃帧 +[NSApplication _crashOnException:]）。
        跟踪区由 MacFloatPanel._build 创建视图后一次性添加。
        """

        def acceptsFirstMouse_(self, w):
            return True

        def mouseDown_(self, e):
            self._owner_forward("click", e)

        def mouseMoved_(self, e):
            self._owner_forward("move", e)

        @objc.python_method
        def _owner_forward(self, kind, e):
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            p = self.convertPoint_toView_(e.locationInWindow(), None)
            owner.forward_panel_event(kind, float(p.x), float(p.y))

    class _KeyNSWindow(ak.NSWindow):
        """允许成为 key window 的无边框窗口（接收失焦通知用）。"""

        def canBecomeKeyWindow(self):
            return True

    class _PanelDelegate(ak.NSObject):
        """NSWindowDelegate：windowDidResignKey → 宿主 on_focus_out。

        必须继承 NSObject——普通 Python 对象注册为 delegate 后，窗口
        信号派发时 ObjC 找不到选择器会抛 NSInvalidArgumentException。
        注意：不要覆写 init（PyObjC 下 super().init() 不可靠），
        owner 用属性赋值（见 MacFloatPanel._build）。
        """

        def windowDidResignKey_(self, notification):
            owner = getattr(self, "_owner", None)
            if owner is not None and owner.on_focus_out is not None:
                try:
                    owner.on_focus_out()
                except Exception:
                    logger.exception("面板失焦回调失败")

    class MacFloatPanel:
        """无边框透明 NSWindow，显示一张 PIL RGBA 图（菜单/气泡）。

        on_click/on_move(x, y)：图内坐标（左上原点，与 Tk 画布一致）。
        on_focus_out()：key 模式下失去 key 状态时回调（用于点外关闭菜单）。
        """

        def __init__(self, width, height, on_click=None, on_move=None,
                     on_focus_out=None, key=False):
            self._w, self._h = int(width), int(height)
            self.on_click = on_click
            self.on_move = on_move
            self.on_focus_out = on_focus_out
            self._key = bool(key)
            self._win = None
            self._view = None
            self._delegate = None
            self._x = self._y = 0
            self._shown = False
            self._build()

        def _build(self):
            ak.NSApplication.sharedApplication()
            rect = NSMakeRect(0, 0, self._w, self._h)
            if self._key:
                win = _KeyNSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    rect, 0, 2, False)
            else:
                win = ak.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    rect, 0, 2, False)
            win.setOpaque_(False)
            win.setBackgroundColor_(ak.NSColor.clearColor())
            win.setHasShadow_(False)          # 阴影已烘焙进图像
            win.setReleasedWhenClosed_(False)
            win.setAcceptsMouseMovedEvents_(True)
            try:
                win.setLevel_(ak.NSFloatingWindowLevel + 1)  # 高于宠物覆盖层
            except AttributeError:
                win.setLevel_(4)
            view = _PanelView.alloc().initWithFrame_(rect)
            view._owner = self
            win.setContentView_(view)
            # 悬停跟踪区：视图创建后一次性添加（勿覆写 updateTrackingAreas，
            # 原因见 _PanelView docstring）
            ta = ak.NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                rect,
                _TRACKING_ENTERED_EXITED | _TRACKING_MOUSE_MOVED
                | _TRACKING_ACTIVE_ALWAYS,
                view, None)
            view.addTrackingArea_(ta)
            self._ta = ta
            if self._key:
                self._delegate = _PanelDelegate.alloc().init()
                self._delegate._owner = self
                win.setDelegate_(self._delegate)
            self._win, self._view = win, view
            logger.info("面板浮层已创建 (%dx%d, key=%s)", self._w, self._h,
                        self._key)

        def set_image(self, pil_image):
            if self._view is None or pil_image is None:
                return
            buf = io.BytesIO()
            pil_image.save(buf, "PNG")
            data = ak.NSData.dataWithBytes_length_(buf.getvalue(),
                                                   len(buf.getvalue()))
            self._view.setImage_(ak.NSImage.alloc().initWithData_(data))
            self._redraw()

        def set_alpha(self, alpha):
            if self._win is not None:
                self._win.setAlphaValue_(max(0.0, min(1.0, alpha / 255.0)))

        def set_position(self, x_tk, y_tk):
            """Tk 全局坐标（图左上）→ Cocoa 坐标。"""
            if self._win is None:
                return
            self._x, self._y = int(x_tk), int(y_tk)
            cx, cy = tk_to_cocoa(self._x, self._y, self._h)
            self._win.setFrameOrigin_((cx, cy))

        def show(self, key=False):
            if self._win is None or self._shown:
                return
            if key:
                self._win.makeKeyAndOrderFront_(None)
            else:
                self._win.orderFrontRegardless()
            self._shown = True

        def alive(self):
            return self._win is not None

        def close(self):
            if self._win is not None:
                try:
                    self._win.orderOut_(None)
                    self._win.setDelegate_(None)
                    self._win.close()
                except Exception:
                    pass
                self._win = None
                self._view = None

        def forward_panel_event(self, kind, x, y):
            ty = self._h - y  # 左下原点 → 左上原点
            if kind == "click" and self.on_click is not None:
                self.on_click(int(x), int(ty))
            elif kind == "move" and self.on_move is not None:
                self.on_move(int(x), int(ty))

        def _redraw(self):
            try:
                self._view.setNeedsDisplay_(True)
                self._win.display()
            except Exception:
                pass
