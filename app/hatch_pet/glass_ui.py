# -*- coding: utf-8 -*-
"""glass_ui — tkinter 设置面板的毛玻璃背景

实现方式：在窗口显示前，抓取窗口目标区域背后的屏幕内容，
高斯模糊后叠一层半透明白色蒙版，得到「磨砂玻璃」质感的静态背景图，
再作为 Canvas 背景铺在设置面板最底层。卡片等控件以不透明方式悬浮其上。

选择截图合成而非 DWM 亚克力（SetWindowCompositionAttribute）的原因：
- tkinter 的亚克力方案必须配合 -transparentcolor 抠洞，透明区域会
  点击穿透到下层窗口，设置面板的卡片间隙点不到，体验差；
- 截图合成无系统版本/主题限制，视觉效果可控且可降级。

任何一步失败（无屏幕抓取权限、多屏坐标异常等）返回 None，
调用方回退为纯色背景，不影响功能。
"""
from PIL import Image, ImageFilter

# 估算的窗口标题栏高度（逻辑像素）。抓取区域只需对齐到模糊后不可分辨的
# 精度，几像素误差在 blur=16 下不可见。
TITLE_H = 34


def frosted_image(x: int, y: int, w: int, h: int,
                  blur: int = 16,
                  tint=(250, 250, 253),
                  tint_alpha: float = 0.60,
                  decor: bool = True):
    """抓取 (x, y, w, h) 区域并生成毛玻璃图。失败返回 None。

    decor=True 时叠加紫/粉/蓝三个大号柔光光斑（玻璃拟态渐变），
    避免背景过于单调；光斑位置按窗口尺寸比例布局。"""
    if w <= 0 or h <= 0:
        return None
    try:
        from PIL import ImageGrab
        box = (int(x), int(y), int(x + w), int(y + h))
        shot = ImageGrab.grab(bbox=box, all_screens=True)
        img = shot.convert("RGB").filter(ImageFilter.GaussianBlur(blur))
        if img.size != (int(w), int(h)):
            img = img.resize((int(w), int(h)), Image.LANCZOS)
        overlay = Image.new("RGB", img.size, tint)
        img = Image.blend(img, overlay, max(0.0, min(0.9, tint_alpha)))
        if decor:
            from PIL import ImageDraw
            W, H = img.size
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            d.ellipse([W * 0.55, -H * 0.30, W * 1.30, H * 0.40],
                      fill=(139, 92, 246, 115))    # 紫（右上）
            d.ellipse([-W * 0.30, H * 0.40, W * 0.30, H * 1.20],
                      fill=(240, 171, 252, 95))    # 粉（左下）
            d.ellipse([W * 0.40, H * 0.62, W * 1.20, H * 1.40],
                      fill=(125, 180, 250, 80))    # 蓝（右下）
            layer = layer.filter(
                ImageFilter.GaussianBlur(max(30, min(W, H) // 8)))
            base = img.convert("RGBA")
            base.alpha_composite(layer)
            img = base.convert("RGB")
        return img
    except Exception:
        return None


def animate_open(win, dur_ms: int = 200, dy: int = 24, steps: int = 10):
    """窗口淡入 + 上滑入场（约 0.2s，ease-out）。"""
    import re
    try:
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", win.geometry())
        if not m:
            return
        w, h, x, y = (int(m.group(i)) for i in range(1, 5))
    except Exception:
        return

    def _step(i):
        k = min(1.0, i / float(steps))
        e = 1 - (1 - k) * (1 - k)
        try:
            win.attributes("-alpha", e)
            win.geometry("%dx%d+%d+%d" % (w, h, x, y + int(dy * (1 - e))))
        except Exception:
            return
        if i < steps:
            win.after(max(10, dur_ms // steps), lambda: _step(i + 1))
        else:
            try:
                win.attributes("-alpha", 1.0)
            except Exception:
                pass

    try:
        win.attributes("-alpha", 0.0)
    except Exception:
        return
    _step(1)


def animate_close(win, done, dur_ms: int = 150, steps: int = 7):
    """窗口淡出，动画结束后执行 done（通常为 destroy）。"""
    def _step(i):
        a = 1.0 - i / float(steps)
        try:
            if a <= 0.05:
                done()
                return
            win.attributes("-alpha", a)
        except Exception:
            done()
            return
        win.after(max(10, dur_ms // steps), lambda: _step(i + 1))

    _step(1)


def client_origin(win_y: int) -> int:
    """窗口顶部 y -> 客户区（标题栏以下）顶部 y"""
    return win_y + TITLE_H
