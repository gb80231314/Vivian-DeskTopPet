# -*- coding: utf-8 -*-
"""apple_ui — Apple 设计语言的可浮层 UI 渲染（径向菜单 / 气泡 / 列表菜单）。

所有面板先画成一张 PIL RGBA 图（圆角 + 真 alpha 阴影 + 线性图标 + 文字），
再交由 float_panel.FloatPanel 按「原生分层窗口」（Windows=UpdateLayeredWindow、
macOS=透明 NSWindow）显示——两平台像素级一致，真正逐像素透明。

风格基调（参考 macOS Sonoma 菜单 / iOS 通知）：
- 按钮与面板：白色磨砂圆角（约 85% 不透明白），1px 中性描边，柔和大半径阴影
- 图标：SF Symbols 风格单色线性图标（圆头笔触，#1D1D1F），悬停反白
- 文字：macOS 用 PingFang SC，Windows 用 Microsoft YaHei，均 #1D1D1F
- 悬停高亮：Apple 系统蓝 #007AFF 圆形/行填充 + 白色图标

本模块只做「画图 + 命中区域几何」，不创建任何窗口。
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageFont

# ---------------------------------------------------------------------------
# 设计常量（Apple 色板）
# ---------------------------------------------------------------------------
LABEL_COLOR = (29, 29, 31)          # #1D1D1F  Apple label
ACCENT = (0, 122, 255)              # #007AFF  Apple systemBlue
PANEL_FILL = (255, 255, 255, 217)   # 磨砂白（≈85% 不透明）
PANEL_STROKE = (0, 0, 0, 34)        # 1px 中性描边
HOVER_FILL = (0, 122, 255, 235)     # 悬停蓝
ICON_COLOR = LABEL_COLOR
ICON_COLOR_HOVER = (255, 255, 255)

_SS = 3  # 超采样倍率（按 3x 绘制后 LANCZOS 缩回，抗锯齿）

MENU_LABELS = {
    "follow":   "跟随",
    "watch":    "观察",
    "activity": "活动",
    "settings": "设置",
    "hide":     "隐藏",
    "quit":     "退出",
}

# 动画名 → 图标 key（左键动画菜单行图标；未命中用 activity 火花）
_ANIM_ICON_MAP = {
    "idle": "watch",
    "idle-plain": "watch",
    "wink": "watch",
    "waiting": "watch",
    "running": "settings",
    "running-right": "follow",
    "running-left": "follow",
    "jumping": "activity",
    "waving": "activity",
    "failed": "hide",
    "review": "watch",
    "angry": "quit",
}


def anim_icon(anim_name):
    return _ANIM_ICON_MAP.get(anim_name, "activity")

# ---------------------------------------------------------------------------
# 字体
# ---------------------------------------------------------------------------
_font_cache = {}


def _font(size, bold=False):
    """跨平台中文字体：macOS PingFang SC / Windows 微软雅黑 / Linux Noto。"""
    key = ("font", size, bold)
    if key in _font_cache:
        return _font_cache[key]
    candidates = []
    if sys.platform == "darwin":
        pf = "/System/Library/Fonts/PingFang.ttc"
        if os.path.exists(pf):
            candidates.append((pf, "pingfang"))   # 逐索引探测含 "SC" 的字体
        candidates += [
            ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
            ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
            ("/System/Library/Fonts/Supplemental/Songti.ttc", 0),
        ]
    elif sys.platform == "win32":
        name = "msyhbd.ttc" if bold else "msyh.ttc"
        candidates += [
            (rf"C:\Windows\Fonts\{name}", 0),
            (r"C:\Windows\Fonts\msyh.ttc", 0),
            (r"C:\Windows\Fonts\simhei.ttf", 0),
        ]
    else:
        candidates += [
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
            ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),
        ]
    font, first_ok = None, None
    for path, idx in candidates:
        try:
            indices = range(20) if idx == "pingfang" else [idx]
            for i in indices:
                f = ImageFont.truetype(path, size, index=i)
                if first_ok is None:
                    first_ok = f
                if "pingfang" in str(path) and "SC" not in " ".join(f.getname()):
                    continue
                font = f
                break
            if font:
                break
        except Exception:
            continue
    if font is None:
        font = first_ok or ImageFont.load_default()
    _font_cache[key] = font
    return font


# ---------------------------------------------------------------------------
# 图标绘制辅助
# ---------------------------------------------------------------------------
def _bez(p0, ctrl, p1, n=6):
    """二次贝塞尔采样。"""
    pts = []
    for i in range(1, n + 1):
        t = i / n
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * ctrl[0] + t ** 2 * p1[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * ctrl[1] + t ** 2 * p1[1]
        pts.append((x, y))
    return pts


def _round_poly(pts, radius=2.0):
    """多边形顶点圆角化（每处尖角换成一小段贝塞尔）。"""
    if radius <= 0 or len(pts) < 3:
        return pts
    out = []
    n = len(pts)
    for i in range(n):
        p_prev, p1, p_next = pts[i - 1], pts[i], pts[(i + 1) % n]

        def towards(a, b, dist):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy) or 1.0
            k = min(dist, ln / 2) / ln
            return a[0] + dx * k, a[1] + dy * k

        a = towards(p1, p_prev, radius)
        b = towards(p1, p_next, radius)
        out.append(a)
        out.extend(_bez(a, p1, b))
    return out


def _star4(cx, cy, r_out, r_in):
    """四角星轮廓点（外点间经内点做二次贝塞尔内凹边）。"""
    pts = []
    for i in range(4):
        a0 = math.radians(-90 + i * 90)
        a_mid = math.radians(-45 + i * 90)
        a_next = math.radians(i * 90)
        p_out = (cx + r_out * math.cos(a0), cy + r_out * math.sin(a0))
        p_in = (cx + r_in * math.cos(a_mid), cy + r_in * math.sin(a_mid))
        p_next = (cx + r_out * math.cos(a_next), cy + r_out * math.sin(a_next))
        pts.append(p_out)
        pts.extend(_bez(p_out, p_in, p_next))
    return pts


def _stroke_poly(d, pts, color, lw):
    """圆头描边多边形（PIL 无 round cap，端点补圆）。"""
    d.line(pts + [pts[0]], fill=color, width=lw, joint="curve")
    r = lw / 2 - 0.3
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


# ---------------------------------------------------------------------------
# SF Symbols 风格图标（画在 s×s 区域中央，图形约占 72%）
# ---------------------------------------------------------------------------
def _icon_follow(d, cx, cy, s, color, lw):
    """定位/导航箭头（SF location）。"""
    r = s * 0.40
    # 指向上方，再整体旋转 45° 指向右上
    raw = [(0, -1.0), (0.78, 0.82), (0, 0.38), (-0.78, 0.82)]
    cos45, sin45 = math.cos(math.pi / 4), math.sin(math.pi / 4)
    rot = []
    for px, py in raw:
        px, py = px * r, py * r
        rot.append((cx + px * cos45 - py * sin45,
                    cy + px * sin45 + py * cos45))
    _stroke_poly(d, _round_poly(rot, r * 0.10), color, lw)


def _icon_watch(d, cx, cy, s, color, lw):
    """眼睛（SF eye）。"""
    w, h = s * 0.66, s * 0.44
    d.arc([cx - w / 2, cy - h * 0.62, cx + w / 2, cy + h * 0.66],
          205, 335, fill=color, width=lw)
    d.arc([cx - w / 2, cy - h * 0.66, cx + w / 2, cy + h * 0.62],
          25, 155, fill=color, width=lw)
    r = s * 0.135
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=lw)
    r2 = s * 0.05
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=color)


def _icon_activity(d, cx, cy, s, color, lw):
    """火花（SF sparkles）：一大一小两颗四角星。"""
    big = _star4(cx - s * 0.10, cy + s * 0.08, s * 0.30, s * 0.075)
    _stroke_poly(d, big, color, lw)
    small = _star4(cx + s * 0.24, cy - s * 0.24, s * 0.14, s * 0.04)
    d.polygon(small, fill=color)


def _icon_settings(d, cx, cy, s, color, lw):
    """齿轮（SF gearshape）。"""
    r = s * 0.26
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=lw)
    r_in = s * 0.115
    d.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in],
              outline=color, width=max(1, lw - 1))
    r0, r1 = s * 0.255, s * 0.365
    for i in range(8):
        a = math.radians(i * 45 + 22.5)
        d.line([cx + r0 * math.cos(a), cy + r0 * math.sin(a),
                cx + r1 * math.cos(a), cy + r1 * math.sin(a)],
               fill=color, width=lw + 1)
        x1, y1 = cx + r1 * math.cos(a), cy + r1 * math.sin(a)
        rr = (lw + 1) / 2 - 0.3
        d.ellipse([x1 - rr, y1 - rr, x1 + rr, y1 + rr], fill=color)


def _icon_hide(d, cx, cy, s, color, lw):
    """月亮（SF moon）：掩膜法月牙。"""
    r = s * 0.30
    size = int(r * 2.4)
    m = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(m)
    c = size / 2
    md.ellipse([c - r, c - r, c + r, c + r], fill=255)
    # 用偏移大圆削出细月牙（缺口朝右上）
    er = r * 1.15
    md.ellipse([c - er * 0.35, c - er * 1.05,
                c + er * 1.65, c + er * 0.45], fill=0)
    solid = Image.new("RGBA", (size, size), color + (255,))
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer.paste(solid, (0, 0), m)
    im = getattr(d, "_image", None)
    if im is not None:
        im.alpha_composite(layer, (int(cx - c), int(cy - c)))


def _icon_quit(d, cx, cy, s, color, lw):
    """电源符号（SF power）。"""
    r = s * 0.29
    d.arc([cx - r, cy - r, cx + r, cy + r], 130, 410, fill=color, width=lw)
    d.line([cx, cy - s * 0.42, cx, cy - r * 0.72], fill=color, width=lw + 1)
    rr = (lw + 1) / 2 - 0.3
    d.ellipse([cx - rr, cy - s * 0.42 - rr, cx + rr, cy - s * 0.42 + rr],
              fill=color)


_ICON_PAINTERS = {
    "follow": _icon_follow,
    "watch": _icon_watch,
    "activity": _icon_activity,
    "settings": _icon_settings,
    "hide": _icon_hide,
    "quit": _icon_quit,
}


def draw_icon(key, size, color=ICON_COLOR, stroke=2.0):
    """绘制单个图标（RGBA，size×size）。"""
    ss = _SS
    big = size * ss
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d._image = im  # 掩膜型图标（月亮）经此合成
    lw = max(2, round(stroke * ss))
    painter = _ICON_PAINTERS.get(key)
    if painter:
        painter(d, big / 2, big / 2, big, color, lw)
    return im.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# 柔和阴影 / 描边工具
# ---------------------------------------------------------------------------
def _shadow_from_mask(mask, blur, alpha, dx=0, dy=0):
    """由 L 掩膜生成黑色柔影图层（RGBA，尺寸同 mask）。"""
    a = mask.filter(ImageFilter.GaussianBlur(blur))
    a = a.point(lambda v: v * alpha // 255)
    layer = Image.new("RGBA", mask.size, (0, 0, 0, 255))
    layer.putalpha(a)
    if dx == 0 and dy == 0:
        return layer
    out = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    out.alpha_composite(layer, (dx, dy))
    return out


def _stroke_from_mask(mask):
    """1px 描边掩膜 = mask - erode(mask)。"""
    return ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))


# ---------------------------------------------------------------------------
# 径向菜单（右键扇形）
# ---------------------------------------------------------------------------
class RadialMenuArt:
    """扇形菜单画面与命中几何。

    image        正常态整图（RGBA）
    hover_images 每项悬停态整图（RGBA），键为项索引
    buttons      [(cx, cy, r), ...] 命中圆（图内 1x 坐标）
    size         (w, h)
    """

    def __init__(self, keys, radius=86, btn_r=27, icon_s=21, label_size=10,
                 pad=20):
        ss = _SS
        self.keys = list(keys)
        n = len(self.keys)
        self.radius, self.btn_r = radius, btn_r

        w = (radius + btn_r + pad) * 2
        h = pad + btn_r + radius + btn_r + pad
        self.size = (w, h)
        cx = w // 2
        cy = h - pad - btn_r  # 扇形圆心

        self.buttons = []
        for i in range(n):
            a = math.radians(180 + 180 * (i / (n - 1) if n > 1 else 0.5))
            self.buttons.append((cx + radius * math.cos(a),
                                 cy + radius * math.sin(a), btn_r))

        # ---------- 圆形组掩膜 + 阴影 + 白底 + 描边 ----------
        mask = Image.new("L", (w * ss, h * ss), 0)
        md = ImageDraw.Draw(mask)
        for bx, by, br in self.buttons:
            md.ellipse([(bx - br) * ss, (by - br) * ss,
                        (bx + br) * ss, (by + br) * ss], fill=255)
        mask1x = mask.resize((w, h), Image.LANCZOS)

        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        base.alpha_composite(_shadow_from_mask(mask1x, blur=9, alpha=95,
                                               dx=0, dy=5))
        base.paste(Image.new("RGBA", (w, h), PANEL_FILL), (0, 0), mask1x)
        base.paste(Image.new("RGBA", (w, h), PANEL_STROKE), (0, 0),
                   _stroke_from_mask(mask1x))

        font = _font(label_size)

        def draw_content(target, icon_color, label_color, only_i=None):
            td = ImageDraw.Draw(target)
            for i, key in enumerate(self.keys):
                if only_i is not None and i != only_i:
                    continue
                bx, by, _ = self.buttons[i]
                icon = draw_icon(key, icon_s, icon_color, stroke=2.0)
                target.alpha_composite(icon, (int(bx - icon_s / 2),
                                              int(by - icon_s / 2 - 4)))
                label = MENU_LABELS.get(key, key)
                tw = td.textlength(label, font=font)
                td.text((bx - tw / 2, by + 5), label, font=font,
                        fill=label_color)

        # 正常态
        self.image = base.copy()
        draw_content(self.image, ICON_COLOR, LABEL_COLOR)

        # ---------- 悬停帧：蓝圆(i) + 白图标 + 白标签 ----------
        blue = Image.new("RGBA", (w, h), HOVER_FILL)
        self.hover_images = {}
        for i in range(n):
            bx, by, br = self.buttons[i]
            bm = Image.new("L", (w * ss, h * ss), 0)
            bmd = ImageDraw.Draw(bm)
            bmd.ellipse([(bx - br) * ss, (by - br) * ss,
                         (bx + br) * ss, (by + br) * ss], fill=255)
            hover = self.image.copy()
            hover.paste(blue, (0, 0), bm.resize((w, h), Image.LANCZOS))
            draw_content(hover, ICON_COLOR_HOVER, (255, 255, 255), only_i=i)
            self.hover_images[i] = hover

    def hit(self, x, y):
        for i, (bx, by, br) in enumerate(self.buttons):
            if (x - bx) ** 2 + (y - by) ** 2 <= (br + 3) ** 2:
                return i
        return None


# ---------------------------------------------------------------------------
# 气泡（Apple 轻通知卡片风格）
# ---------------------------------------------------------------------------
_BUBBLE_ACCENT = {  # state → (强调色, 文字色)
    "error":      ((255, 59, 48), (183, 35, 28)),
    "done":       ((52, 199, 89), (24, 116, 52)),
    "happy":      ((52, 199, 89), (24, 116, 52)),
    "greet":      ((0, 122, 255), (0, 86, 179)),
    "working":    ((255, 149, 0), (153, 86, 0)),
    "thinking":   ((0, 122, 255), (0, 86, 179)),
    "needsinput": ((255, 149, 0), (153, 86, 0)),
    "waiting":    ((255, 149, 0), (153, 86, 0)),
    "juggling":   ((175, 82, 222), (121, 51, 189)),
    "loafing":    ((255, 59, 48), (183, 35, 28)),
    "sleeping":   ((142, 142, 147), (72, 72, 74)),
}


class BubbleArt:
    """气泡画面（render 后得到 image / arrow_cx / arrow_side）。"""

    def __init__(self, msg, state="", max_w=260, text_size=13, arrow_w=18,
                 arrow_h=9, radius=14):
        accent, text_color = _BUBBLE_ACCENT.get(state, ((255, 255, 255),
                                                        LABEL_COLOR))
        font = _font(text_size)
        pad_x, pad_y = 14, 8
        lh = text_size + 7

        lines, remain = [], msg
        while remain:
            for i in range(len(remain), 0, -1):
                if font.getlength(remain[:i]) <= max_w - pad_x * 2:
                    lines.append(remain[:i])
                    remain = remain[i:]
                    break
            else:
                lines.append(remain)
                remain = ""
        text_w = max((font.getlength(l) for l in lines), default=0)
        bw = max(int(text_w) + pad_x * 2, 56)
        bh = len(lines) * lh + pad_y * 2 - 2

        shadow_pad = 12
        self.size = (bw + shadow_pad * 2, bh + arrow_h + shadow_pad)
        self._g = dict(bw=bw, bh=bh, radius=radius, arrow_w=arrow_w,
                       arrow_h=arrow_h, shadow_pad=shadow_pad,
                       font=font, lines=lines, lh=lh, pad_y=pad_y,
                       accent=accent, text_color=text_color)
        self.arrow_cx = 0
        self.arrow_side = "bottom"

    def render(self, arrow_cx, side="bottom"):
        """按箭头位置/方向合成最终图（arrow_cx 为图内 x 坐标）。"""
        g = self._g
        ss = _SS
        w, h = self.size
        bx1, by1 = g["shadow_pad"] * ss, 2 * ss
        bx2, by2 = (g["shadow_pad"] + g["bw"]) * ss, (2 + g["bh"]) * ss
        mask = Image.new("L", (w * ss, h * ss), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([bx1, by1, bx2, by2],
                             radius=g["radius"] * ss, fill=255)
        ax = max(g["shadow_pad"] + g["arrow_w"] + 4,
                 min(int(arrow_cx), w - g["shadow_pad"] - g["arrow_w"] - 4))
        ah, aw = g["arrow_h"] * ss, g["arrow_w"] * ss
        if side == "bottom":
            ay = by2
            tri = [(ax * ss - aw / 2, ay - 1), (ax * ss + aw / 2, ay - 1),
                   (ax * ss, ay + ah)]
        else:
            ay = by1
            tri = [(ax * ss - aw / 2, ay + 1), (ax * ss + aw / 2, ay + 1),
                   (ax * ss, ay - ah)]
        md.polygon(tri, fill=255)
        self.arrow_cx, self.arrow_side = ax, side

        mask1x = mask.resize((w, h), Image.LANCZOS)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(_shadow_from_mask(mask1x, blur=10, alpha=70,
                                              dx=0, dy=4))
        ac = g["accent"]
        body = Image.new("RGBA", (w, h),
                         (round(255 * 0.90 + ac[0] * 0.10),
                          round(255 * 0.90 + ac[1] * 0.10),
                          round(255 * 0.90 + ac[2] * 0.10), 247))
        img.paste(body, (0, 0), mask1x)
        img.paste(Image.new("RGBA", (w, h), (0, 0, 0, 30)), (0, 0),
                  _stroke_from_mask(mask1x))
        d = ImageDraw.Draw(img)
        ty0 = 2 + g["pad_y"] - 1
        for i, line in enumerate(g["lines"]):
            d.text((g["shadow_pad"] + g["bw"] / 2, ty0 + i * g["lh"]
                    + g["lh"] / 2), line, font=g["font"],
                   fill=g["text_color"], anchor="mm")
        return img


# ---------------------------------------------------------------------------
# 列表菜单（垂直菜单，Windows 左键动画菜单用；macOS 用系统原生菜单）
# ---------------------------------------------------------------------------
class ListMenuArt:
    """圆角面板 + 图标行 + 悬停蓝条（macOS 菜单样式）。"""

    ROW_H = 30
    ICON_S = 17
    PAD = 8

    def __init__(self, rows, label_size=12, min_w=150):
        """rows: [("icon_key"|"sep", label), ...]"""
        ss = _SS
        self.rows = rows
        font = _font(label_size)
        text_w = max((font.getlength(lbl) for _, lbl in rows if lbl),
                     default=0)
        w = max(min_w, int(text_w) + self.PAD * 2 + self.ICON_S + 30)
        h = len(rows) * self.ROW_H + self.PAD * 2 - 4
        self.size = (w, h)

        mask = Image.new("L", (w * ss, h * ss), 0)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle([2 * ss, 2 * ss, (w - 2) * ss, (h - 2) * ss],
                             radius=11 * ss, fill=255)
        mask1x = mask.resize((w, h), Image.LANCZOS)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        img.alpha_composite(_shadow_from_mask(mask1x, blur=9, alpha=85,
                                              dx=0, dy=4))
        img.paste(Image.new("RGBA", (w, h), PANEL_FILL), (0, 0), mask1x)
        img.paste(Image.new("RGBA", (w, h), PANEL_STROKE), (0, 0),
                  _stroke_from_mask(mask1x))

        d = ImageDraw.Draw(img)
        self.row_rects = []
        for ri, (key, lbl) in enumerate(rows):
            ry = self.PAD - 2 + ri * self.ROW_H
            self.row_rects.append((0, ry, w, ry + self.ROW_H))
            if key == "sep":
                ly = ry + self.ROW_H // 2
                d.line([self.PAD, ly, w - self.PAD, ly],
                       fill=(0, 0, 0, 26), width=1)
                continue
            icon = draw_icon(key, self.ICON_S, ICON_COLOR, stroke=1.8)
            img.alpha_composite(icon, (self.PAD + 4,
                                       ry + (self.ROW_H - self.ICON_S) // 2))
            d.text((self.PAD + self.ICON_S + 14, ry + self.ROW_H // 2), lbl,
                   font=font, fill=LABEL_COLOR, anchor="lm")
        self.image = img

        self.hover_images = {}
        for ri, (key, lbl) in enumerate(rows):
            if key == "sep":
                continue
            hover = img.copy()
            hd = ImageDraw.Draw(hover)
            x0, y0, x1, y1 = self.row_rects[ri]
            hd.rounded_rectangle([x0 + 5, y0 + 1, x1 - 5, y1 - 1],
                                 radius=7, fill=HOVER_FILL)
            hd.text((self.PAD + self.ICON_S + 14, y0 + self.ROW_H // 2), lbl,
                    font=font, fill=(255, 255, 255), anchor="lm")
            icon = draw_icon(key, self.ICON_S, ICON_COLOR_HOVER, stroke=1.8)
            hover.alpha_composite(icon, (self.PAD + 4,
                                         y0 + (self.ROW_H - self.ICON_S) // 2))
            self.hover_images[ri] = hover

    def hit(self, x, y):
        for ri, (x0, y0, x1, y1) in enumerate(self.row_rects):
            if y0 <= y < y1 and x0 <= x < x1:
                return None if self.rows[ri][0] == "sep" else ri
        return None


def preview_all(out_dir):
    """开发期预览：三件套渲染到 PNG（浅/深两种桌面底色各一张）。"""
    os.makedirs(out_dir, exist_ok=True)
    art = RadialMenuArt(["follow", "watch", "activity", "settings", "hide",
                         "quit"])
    _on_wall(art.image, os.path.join(out_dir, "radial.png"))
    bub = BubbleArt("你好，Vivian 已上线，开始盯任务啦！", "greet")
    _on_wall(bub.render(60, "bottom"), os.path.join(out_dir, "bubble.png"))
    lm = ListMenuArt([("follow", "待机 idle"), ("activity", "跑动 run"),
                      ("sep", ""), ("quit", "退出")])
    _on_wall(lm.image, os.path.join(out_dir, "listmenu.png"))
    return out_dir


def _on_wall(img, path):
    w, h = img.size
    for name, base in (("light", (208, 224, 227)), ("dark", (40, 60, 80))):
        bg = Image.new("RGBA", (w + 60, h + 60), base + (255,))
        bg.alpha_composite(img, (30, 30))
        bg.convert("RGB").save(path.replace(".png", f"_{name}.png"))
