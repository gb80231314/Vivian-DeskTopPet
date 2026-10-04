# -*- coding: utf-8 -*-
"""pixel_ui — 赛博朋克 × 可爱风的像素 UI 素材（黑绿黄蓝四色体系）

配色规划：
- 黑  #0A0E14  窗口底色（夜） / #121A24 卡片 / #233043 描边
- 绿  #39FF6E  主强调：霓虹绿（边框/标题/logo/输入文字）
- 黄  #FFD60A  可爱点缀：保存按钮 / ❕提示 / 爱心·星星·月亮
- 蓝  #00D9FF  辅助霓虹：音符 / 链接 / 天际线灯窗
- 文字  #D9E8F5  主文字 / #7C93AB 次要文字 / #7CFFB2 终端风输入

提供两类素材（全部程序化生成，无外部资源）：
- icon_photo()   手绘像素矩阵 logo（NEAREST 放大，硬边像素风）
- pixel_backdrop() 赛博像素壁纸：暗色渐变 + 网格点 + 星星/闪光
  + 底部霓虹天际线 + 像素月亮与爱心（固定种子，缩放后重绘一致）
"""
import random

from PIL import Image, ImageDraw

# ---------- 四色体系 ----------
BLACK_BG = "#0A0E14"
BLACK_CARD = "#121A24"
BLACK_INPUT = "#0B1016"
BLACK_LINE = "#233043"
GREEN = "#39FF6E"
YELLOW = "#FFD60A"
BLUE = "#00D9FF"
TEXT = "#D9E8F5"
SUB = "#7C93AB"
MINT = "#7CFFB2"

# ---------- 像素 logo（手绘矩阵，'.' 为透明） ----------
_ICONS = {
    # 主标题：Vivian 像素脸（发光绿眼 = 赛博 + 可爱）
    "face": {
        "H": "#2A1F3D", "F": "#FFE0CE", "E": GREEN, "W": "#EFFFF4",
        "M": "#FF8FA3", "B": "#FFB3C6",
        "rows": [
            "..HHHHHHHH..",
            ".HHHHHHHHHH.",
            "HHHHHHHHHHHH",
            "HHHHHHHHHHHH",
            "HHFFFFFFFFFF",
            "HFFEWFFEWFFH",
            "HFFEEFFEEFFH",
            "HFBFFFFFFBFF",
            "HFFFFFFFFFFH",
            ".FFFFMMFFFF.",
            ".FFFFFFFFFF.",
            "..FFFFFFFF..",
        ],
    },
    # 外观与行为：调节滑杆
    "sliders": {
        "G": GREEN, "K": YELLOW,
        "rows": [
            "..........",
            "GGGGGGGGGG",
            "GGKKKGGGGG",
            "..........",
            "GGGGGGGGGG",
            "GGGGGGGKKK",
            "..........",
            "GGGGGGGGGG",
            "GKKKGGGGGG",
            "..........",
        ],
    },
    # 互动与提醒：爱心
    "heart": {
        "Y": YELLOW, "W": "#FFF7CC",
        "rows": [
            ".YY...YY.",
            "YYYY.YYYY",
            "YYYYYYYYY",
            "YWYYYYYYY",
            ".YYYYYYY.",
            "..YYYYY..",
            "...YYY...",
            "....Y....",
        ],
    },
    # 语音包：音符
    "note": {
        "B": BLUE,
        "rows": [
            "....BB.",
            "....BB.",
            "....BB.",
            "....BB.",
            "....BB.",
            ".BBBBB.",
            ".BBBBB.",
            ".BBBBB.",
            "..BBB..",
        ],
    },
    # 语音交互：麦克风
    "mic": {
        "G": GREEN, "Y": YELLOW,
        "rows": [
            "..GGGG..",
            ".GGGGGG.",
            ".GGGGGG.",
            ".GGGGGG.",
            ".GGGGGG.",
            "..GGGG..",
            "...GG...",
            ".YYYYYY.",
            "...YY...",
            "...YY...",
        ],
    },
    # 其他：星星
    "star": {
        "Y": YELLOW, "W": "#FFFFFF",
        "rows": [
            "....Y....",
            "...YYY...",
            "...YYY...",
            "YYYYYYYYY",
            ".YYWYYYY.",
            "..YYYYY..",
            ".YYY.YYY.",
            ".Y.....Y.",
        ],
    },
    # 可爱点缀：像素爱心（壁纸用）
    "mini-heart": {
        "G": GREEN,
        "rows": [
            ".GG...GG.",
            "GGGG.GGGG",
            "GGGGGGGGG",
            "GGGGGGGGG",
            ".GGGGGGG.",
            "..GGGGG..",
            "...GGG...",
            "....G....",
        ],
    },
}


def icon_image(name: str, scale: int = 3) -> Image:
    spec = _ICONS.get(name)
    if spec is None:
        raise KeyError(name)
    rows = spec["rows"]
    w = len(rows[0])
    h = len(rows)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            color = spec.get(ch)
            if color:
                px[x, y] = tuple(int(color[i:i + 2], 16)
                                 for i in (1, 3, 5)) + (255,)
    return img.resize((w * scale, h * scale), Image.NEAREST)


def icon_photo(widget, name: str, scale: int = 3):
    """生成 PhotoImage。注意：请在宿主窗口映射（deiconify）之后再调用，
    withdraw 状态下带 master 创建会得到空白图像。"""
    from PIL.ImageTk import PhotoImage
    return PhotoImage(icon_image(name, scale))


def checkbox_photo(widget, checked: bool, scale: int = 2):
    """自绘像素勾选框（12×12 逻辑格）：
    未选中 = 暗盒浅边框；选中 = 亮盒 + 霓虹绿像素对勾。"""
    from PIL.ImageTk import PhotoImage
    img = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 11, 11], outline="#7C93AB")
    if checked:
        d.rectangle([1, 1, 10, 10], fill="#E8F6EF")
        # 像素对勾：左降右升两段 2px 点
        for x, y in ((3, 6), (4, 7), (5, 8), (6, 7), (7, 6), (8, 5), (9, 4)):
            d.rectangle([x, y, x + 1, y + 1], fill=GREEN)
    else:
        d.rectangle([1, 1, 10, 10], fill="#0B1016")
    return PhotoImage(img.resize((12 * scale, 12 * scale), Image.NEAREST),
                      master=widget)


# ---------- 赛博像素壁纸 ----------
def pixel_backdrop(w: int, h: int, seed: int = 20260930) -> Image:
    """黑底霓虹像素壁纸：渐变 + 网格点 + 星星/闪光 + 天际线 + 月亮爱心。"""
    rnd = random.Random(seed)
    w = max(200, int(w))
    h = max(200, int(h))
    img = Image.new("RGB", (w, h), BLACK_BG)
    d = ImageDraw.Draw(img)

    # 1) 纵向渐变（4px 一条，保持块状）
    top = (10, 14, 20)
    bot = (14, 22, 32)
    for yy in range(0, h, 4):
        k = yy / max(1, h - 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3))
        d.rectangle([0, yy, w, min(h, yy + 3)], fill=c)

    # 2) 网格点
    for yy in range(4, h, 16):
        for xx in range(4, w, 16):
            d.point((xx, yy), fill=(24, 36, 50))

    # 3) 星星（上半部散布）
    for _ in range(max(24, w // 22)):
        xx = rnd.randrange(2, max(3, w - 3))
        yy = rnd.randrange(2, max(3, int(h * 0.55)))
        c = rnd.choice([YELLOW, BLUE, "#E8F6EF", GREEN])
        s = rnd.choice([1, 1, 2])
        d.rectangle([xx, yy, xx + s, yy + s], fill=c)

    # 4) 十字闪光
    for _ in range(max(3, w // 220)):
        xx = rnd.randrange(8, max(9, w - 8))
        yy = rnd.randrange(8, max(9, int(h * 0.5)))
        c = rnd.choice([GREEN, YELLOW])
        d.rectangle([xx - 2, yy, xx + 2, yy], fill=c)
        d.rectangle([xx, yy - 2, xx, yy + 2], fill=c)

    # 5) 赛博天际线（底部）
    base = h
    xx = 0
    while xx < w:
        bw = rnd.randrange(14, 44)
        bh = rnd.randrange(int(h * 0.05), int(h * 0.20))
        d.rectangle([xx, base - bh, min(w, xx + bw) - 1, base],
                    fill=rnd.choice(["#0C1119", "#0D1320", "#0B141D"]))
        d.rectangle([xx, base - bh, min(w, xx + bw) - 1, base - bh + 1],
                    fill=rnd.choice(["#123B2A", "#0E3550", "#3B3413"]))
        for wy in range(base - bh + 4, base - 4, 6):
            for wx in range(xx + 3, min(w, xx + bw) - 4, 7):
                if rnd.random() < 0.16:
                    d.rectangle([wx, wy, wx + 1, wy + 1], fill=rnd.choice(
                        [GREEN, YELLOW, BLUE]))
        xx += bw + rnd.randrange(0, 4)

    # 6) 像素月亮（右上，可爱）
    moon = ["..YYYY..", ".YYYYYY.", "YYYYYYYY", "YYYYYYYY",
            "YYYYYYYY", "YYYYYYYY", ".YYYYYY.", "..YYYY.."]
    _stamp(d, moon, {"Y": "#F5D76E"}, w - 40, 14)

    # 7) 像素爱心（左上，可爱）
    heart = _ICONS["mini-heart"]["rows"]
    _stamp(d, heart, {"G": GREEN}, 14, 12)

    return img


def _stamp(d, rows, palette, ox: int, oy: int):
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            c = palette.get(ch)
            if c:
                d.rectangle([ox + x, oy + y, ox + x, oy + y], fill=c)
