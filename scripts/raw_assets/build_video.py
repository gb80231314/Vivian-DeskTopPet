# -*- coding: utf-8 -*-
"""Vivian 桌面宠物 竖版介绍视频渲染（1080x1920 @30fps, 15s）
分镜:
  S0 0.0-2.6  开场:鼠标双击图标→蛋壳式裂开→人物蹦出
  S1 2.6-4.65 Hi,我是Vivian(挥手+标题)
  S2 4.65-7.15 桌面小宠物(假桌面+捧花待机)
  S3 7.15-9.9  形态蒙太奇(奔跑/跳跃/等待/审阅)
  S4 9.9-13.0  眼神跟随 + CPU情绪联动
  S5 13.0-15   开源预告(自定义功能)
"""
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = "F:/AiWorkProject/2026-09-17-22-43-10"
OUT = ROOT + "/pet-work/video/video_silent.mp4"

W, H, FPS, DUR = 1080, 1920, 30, 15.0
N_FRAMES = int(DUR * FPS)
CW, CH = 192, 208          # 精灵图单元格
SPR = 4                    # 精灵放大倍数
EYE_L, EYE_R = (77, 81), (114, 80)
EYE_RX, EYE_RY = 7, 6

# ── 时间轴 ─────────────────────────────
S0 = (0.0, 2.6); S1 = (2.6, 4.65); S2 = (4.65, 7.15)
S3 = (7.15, 9.9); S4 = (9.9, 13.0); S5 = (13.0, 15.0)

# ── 精灵图 ─────────────────────────────
sheet = Image.open(ROOT + "/my-qpet/spritesheet.png").convert("RGBA")

_cache = {}
def cell(row, col):
    key = (row, col)
    if key not in _cache:
        _cache[key] = sheet.crop((col*CW, row*CH, col*CW+CW, row*CH+CH))
    return _cache[key]

_sc = {}
def cell_scaled(row, col):
    key = (row, col)
    if key not in _sc:
        _sc[key] = cell(row, col).resize((CW*SPR, CH*SPR), Image.LANCZOS)
    return _sc[key]

def frame_of(row, t, fps):
    return cell_scaled(row, int(t * fps) % 16)

# ── 眼部合成（与 qpet_app 同源） ──────────
def skin_color(img):
    px = img.load(); cs = []
    for ddy in range(-10, -4):
        for ddx in range(-3, 4):
            x, y = EYE_L[0]+ddx, EYE_L[1]+ddy
            if 0 <= x < img.width and 0 <= y < img.height:
                p = px[x, y]
                if p[3] > 200 and p[0] > 100:
                    cs.append(p[:3])
    return (255, 235, 225) if not cs else tuple(sum(c[i] for c in cs)//len(cs) for i in range(3))

def synth_eyes(img, angle_deg=None, blink_amt=0.0):
    """在 192x208 基础帧上合成眼白+瞳孔+眼睑，返回新图。"""
    img = img.copy()
    d = ImageDraw.Draw(img)
    sc = skin_color(img)
    if angle_deg is not None:
        rad = math.radians(angle_deg)
        dx, dy = math.sin(rad)*3.0, -math.cos(rad)*3.0
    else:
        dx = dy = 0
    for ex, ey in (EYE_L, EYE_R):
        d.ellipse([ex-EYE_RX-2, ey-EYE_RY-2, ex+EYE_RX+2, ey+EYE_RY+2], fill=sc+(255,))
        d.ellipse([ex-EYE_RX, ey-EYE_RY, ex+EYE_RX, ey+EYE_RY], fill=(255, 250, 248, 255))
        nx, ny = round(ex+dx), round(ey+dy)
        d.ellipse([nx-4, ny-4, nx+4, ny+4], fill=(40, 30, 35, 255))
        d.ellipse([nx-2, ny-2, nx+1, ny+1], fill=(255, 255, 255, 255))
    if blink_amt > 0.02:
        hw, eh = EYE_RX+3, EYE_RY+2
        for ex, ey in (EYE_L, EYE_R):
            top = ey - eh
            bottom = top + round(2*eh*blink_amt)
            if bottom > top + 1:
                d.ellipse([ex-hw, top, ex+hw, bottom], fill=sc+(255,))
                if blink_amt > 0.55:
                    ly = bottom - 1
                    d.line([(ex-hw+2, ly-1), (ex, ly+1), (ex+hw-2, ly-1)], fill=(70, 45, 50, 255), width=1)
    return img

# ── 开场：图标 + 蛋壳碎片（预计算） ──────────
ICON_C = (540, 880)
TILE = 380

def make_tile():
    """桌面快捷方式图标：圆角白底瓷贴 + Vivian 艺术字"""
    tile = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    td.rounded_rectangle([6, 6, TILE-6, TILE-6], radius=88,
                         fill=(252, 250, 252, 252), outline=(226, 220, 238, 255), width=4)
    art = Image.open(ROOT + "/my-qpet/vivian.png").convert("RGBA")
    art.thumbnail((300, 300), Image.LANCZOS)
    tile.alpha_composite(art, ((TILE-art.width)//2, (TILE-art.height)//2 - 8))
    return tile
TILE_IMG = make_tile()

def make_halves():
    """沿纵向锯齿裂缝把图标切成左右两半（蛋壳式）"""
    import random as _rnd
    _rnd.seed(7)
    # 纵向锯齿裂缝路径（x 围绕中心抖动）
    zig = [(190 + (190-190)*0 + _rnd.uniform(-24, 24), y) for y in range(6, TILE, 26)]
    zig[0] = (190 + _rnd.uniform(-8, 8), 6); zig[-1] = (190 + _rnd.uniform(-8, 8), TILE-6)
    halves = []
    for side in ("L", "R"):
        mask = Image.new("L", (TILE, TILE), 0)
        md = ImageDraw.Draw(mask)
        if side == "L":
            poly = [(6, 6)] + [(max(6, x-4), y) for x, y in zig] + [(6, TILE-6)]
        else:
            poly = [(TILE-6, 6)] + [(min(TILE-6, x+4), y) for x, y in zig] + [(TILE-6, TILE-6)]
        md.polygon(poly, fill=255)
        img = TILE_IMG.copy()
        img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (TILE, TILE), 0), mask))
        halves.append(dict(img=img, side=side, zig=zig))
    return halves
HALVES = make_halves()
ZIG = HALVES[0]["zig"]

def draw_crack_line(d, k):
    """裂缝锯齿线从上往下生长，k∈[0,1]"""
    n = max(2, int(2 + k*(len(ZIG)-1)))
    pts = [(ICON_C[0]-TILE//2 + x, ICON_C[1]-TILE//2 + y) for x, y in ZIG[:n]]
    d.line(pts, fill=(122, 92, 76, 235), width=7, joint="curve")

def draw_star(d, x, y, r, color, tw):
    """四角星光"""
    d.line([(x-r, y), (x+r, y)], fill=color, width=max(2, int(r*0.35)))
    d.line([(x, y-r), (x, y+r)], fill=color, width=max(2, int(r*0.35)))
import os
FONT_CANDIDATES = ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]
FONT_PATH = next(f for f in FONT_CANDIDATES if os.path.exists(f))
def font(sz):
    return ImageFont.truetype(FONT_PATH, sz, index=0)

F_TITLE  = font(108)
F_SUB    = font(56)
F_CAP    = font(52)
F_BADGE  = font(46)
F_SMALL  = font(38)
F_CREDIT = font(64)

# ── 背景（预计算渐变+光晕） ───────────────
def make_bg():
    y = np.linspace(0, 1, H)[:, None]
    top = np.array([255, 236, 244], dtype=float)
    bot = np.array([232, 236, 255], dtype=float)
    grad = top*(1-y) + bot*y                     # (H,3)
    img = np.repeat(grad[:, None, :], W, axis=1).astype(np.uint8)
    im = Image.fromarray(img, "RGB")
    # 中央柔光
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W//2-560, 700-560, W//2+560, 700+560], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    white = Image.new("RGB", (W, H), (255, 255, 255))
    im = Image.composite(white, im, glow.point(lambda v: v//2))
    return im
BG = make_bg()

# ── 粒子（花瓣/雏菊） ────────────────────
rng = np.random.default_rng(42)
PARTS = []
for i in range(26):
    PARTS.append(dict(
        x=float(rng.uniform(20, W-20)), y=float(rng.uniform(0, H)),
        r=float(rng.uniform(7, 18)),
        spd=float(rng.uniform(28, 66)),
        sway=float(rng.uniform(14, 40)),
        ph=float(rng.uniform(0, 6.28)),
        kind="daisy" if i % 3 == 0 else "petal",
        hue=(255, 182, 208) if i % 3 else (255, 255, 255),
    ))

def draw_particles(d, t):
    for p in PARTS:
        y = (p["y"] + p["spd"]*t) % (H + 60) - 30
        x = p["x"] + p["sway"]*math.sin(t*0.9 + p["ph"])
        r = p["r"]
        if p["kind"] == "daisy":
            d.ellipse([x-r, y-r, x+r, y+r], fill=p["hue"], outline=(250, 214, 120), width=2)
            d.ellipse([x-r*0.35, y-r*0.35, x+r*0.35, y+r*0.35], fill=(255, 214, 92))
        else:
            d.ellipse([x-r*0.6, y-r, x+r*0.6, y+r], fill=p["hue"]+(160,) if d.im.mode == "RGBA" else p["hue"])

def text_c(d, y, s, f, fill=(60, 44, 66), stroke=0, sfill=(255, 255, 255)):
    bb = d.textbbox((0, 0), s, font=f, stroke_width=stroke)
    d.text(((W-(bb[2]-bb[0]))//2, y), s, font=f, fill=fill, stroke_width=stroke, stroke_fill=sfill)

def rounded_card(d, box, fill=(255, 255, 255, 205), radius=36, outline=None):
    d.rounded_rectangle(box, radius=radius, fill=fill[:3] if d.im.mode == "RGB" else fill, outline=outline)

# ── 场景元素 ──────────────────────────
def draw_badge(d, t, text, color, y=1660):
    """CPU 状态胶囊"""
    f = F_BADGE
    bb = d.textbbox((0, 0), text, font=f)
    tw = bb[2]-bb[0]; th = bb[3]-bb[1]
    x0 = (W - tw)//2 - 44; x1 = (W + tw)//2 + 44
    pop = min(1.0, t*4)
    hh = int((th + 36) * (0.7 + 0.3*pop))
    d.rounded_rectangle([x0, y-hh//2, x1, y+hh//2], radius=hh//2, fill=color, outline=(255,255,255), width=3)
    d.text(((W-tw)//2, y-th//2-bb[1]), text, font=f, fill=(255, 255, 255))

def draw_desktop(d, t):
    """假桌面：窗口 + 任务栏"""
    # 窗口
    d.rounded_rectangle([80, 500, 1000, 1520], radius=28, fill=(255, 255, 255), outline=(210, 214, 232), width=2)
    d.rounded_rectangle([80, 500, 1000, 596], radius=28, fill=(238, 241, 250))
    d.rectangle([80, 560, 1000, 596], fill=(238, 241, 250))
    for i, c in enumerate([(255, 108, 96), (255, 194, 66), (92, 200, 96)]):
        d.ellipse([108+i*44, 532, 138+i*44, 562], fill=c)
    d.text((250, 528), "我的电脑", font=F_SMALL, fill=(120, 124, 148))
    # 文字行
    for i in range(6):
        w = 620 if i % 2 == 0 else 440
        d.rounded_rectangle([120, 660+i*74, 120+w, 688+i*74], radius=12, fill=(234, 236, 246))
    # 小图表
    d.rounded_rectangle([120, 1130, 960, 1460], radius=16, fill=(246, 247, 253))
    pts = [(180+ i*110, 1400 - int(180*math.sin(i*0.9 + t*1.2)**2)) for i in range(7)]
    d.line(pts, fill=(255, 128, 170), width=6)
    for p in pts:
        d.ellipse([p[0]-7, p[1]-7, p[0]+7, p[1]+7], fill=(255, 128, 170))
    # 任务栏
    d.rectangle([0, 1780, W, H], fill=(44, 46, 66))
    for i in range(6):
        c = (255, 182, 208) if i != 2 else (255, 255, 255)
        d.rounded_rectangle([60+i*100, 1808, 124+i*100, 1872], radius=14, fill=c)
    d.ellipse([W-96, 1812, W-40, 1868], fill=(120, 124, 148))

def draw_cursor(d, x, y, s=1.0):
    """鼠标指针（白底黑边箭头）"""
    pts = [(0, 0), (0, 30), (7, 24), (12, 34), (17, 31), (12, 22), (21, 21)]
    pts = [(x + px*s*1.4, y + py*s*1.4) for px, py in pts]
    d.polygon(pts, fill=(255, 255, 255), outline=(50, 50, 60))

def ease_out_back(k):
    k -= 1
    return 1 + 2.2*k**3 + 1.2*k**2

def sprite_at(img, top, scale=1.0):
    """居中贴精灵，top 为顶边 y。"""
    if scale != 1.0:
        w, h = int(img.width*scale), int(img.height*scale)
        img = img.resize((w, h), Image.LANCZOS)
    frame.paste(img, ((W - img.width)//2, top), img)

def caption(d, text):
    d.rounded_rectangle([90, 1642, W-90, 1762], radius=32, fill=(255, 255, 255))
    d.line([(130, 1652), (130, 1752)], fill=(255, 128, 170), width=8)
    text_c(d, 1672, text, F_CAP, fill=(76, 56, 84))

# ── 主渲染 ─────────────────────────────
import imageio.v2 as imageio
writer = imageio.get_writer(OUT, fps=FPS, codec="libx264", quality=8,
                            macro_block_size=None, pixelformat="yuv420p")

for fi in range(N_FRAMES):
    t = fi / FPS
    frame = BG.copy()
    d = ImageDraw.Draw(frame)
    draw_particles(d, t)

    if t < S0[1]:                                   # S0 开场：双击图标→蛋壳裂开→蹦出
        # 阶段: 0-0.7 鼠标移入 / 0.7-1.05 双击 / 1.05-2.0 裂缝生长+两半张开 / 2.0-2.6 进裂蹦出
        reveal = cell_scaled(9, 0)                  # 中性站姿（壳内人物）
        if t < 2.0:
            k = max(0.0, (t-1.05)/0.95)             # 裂开进度
            # 壳内人物逐渐显现（裂缝张开后清晰可见）
            if k > 0.3:
                kk = (k-0.3)/0.7
                sc = 0.35 + 0.42*kk
                w2, h2 = int(reveal.width*sc), int(reveal.height*sc)
                spr = reveal.resize((w2, h2), Image.LANCZOS)
                frame.paste(spr, (ICON_C[0]-w2//2, ICON_C[1]-h2//2), spr)
            # 左右两半蛋壳张开
            pulse = 1.0
            if 0.7 <= t < 1.05:                     # 双击脉冲
                ph = (t-0.7) % 0.18
                pulse = 1.0 - 0.05*math.sin(math.pi*ph/0.18)
            gap = 0 if k <= 0.28 else (k-0.28)/0.72 * 175   # 两半横向张开距离
            for h in HALVES:
                img = h["img"]
                if pulse != 1.0:
                    img = img.resize((int(TILE*pulse), int(TILE*pulse)), Image.LANCZOS)
                sgn = -1 if h["side"] == "L" else 1
                tilt = -10*sgn * (gap/175)
                if tilt:
                    img = img.rotate(tilt, resample=Image.BICUBIC, expand=False)
                frame.paste(img, (int(ICON_C[0]-img.width//2 + sgn*gap),
                                  int(ICON_C[1]-img.height//2)), img)
            if 0.98 <= t <= 1.05 + 0.3*0.95:        # 裂缝生长（张开前）
                draw_crack_line(d, min(1.0, k/0.3))
            if 0.86 <= t < 1.25:                    # 双击涟漪
                rr = 30 + (t-0.86)*420
                d.ellipse([ICON_C[0]-rr, ICON_C[1]-rr, ICON_C[0]+rr, ICON_C[1]+rr],
                          outline=(255, 150, 190), width=4)
            # 快捷方式标签
            if t < 1.3:
                text_c(d, ICON_C[1]+TILE//2+36, "Vivian 桌面宠物", F_SMALL, fill=(130, 100, 140))
        else:                                       # 2.0-2.6 蛋壳飞散 + 人物蹦出
            b = (t-2.0)/0.6
            # 人物弹出：放大过冲 + 落位
            pop = ease_out_back(min(1.0, b*1.25))
            sc = 0.8 + 0.35*pop - 0.15*max(0.0, b-0.8)/0.2 if b > 0.8 else 0.8 + 0.35*pop
            cy = ICON_C[1] + (1136-ICON_C[1])*min(1.0, b*1.15)   # 移到标准站位
            w2, h2 = int(reveal.width*sc), int(reveal.height*sc)
            spr = reveal.resize((w2, h2), Image.LANCZOS)
            frame.paste(spr, (ICON_C[0]-w2//2, int(cy-h2//2)), spr)
            # 两半壳加速向外飞旋淡出
            for h in HALVES:
                sgn = -1 if h["side"] == "L" else 1
                dist = 60 + 640*b*b
                img = h["img"].rotate(sgn*46*b, resample=Image.BICUBIC, expand=True)
                if b > 0.55:
                    fade = max(0, 1-(b-0.55)/0.45)
                    a_ = img.getchannel("A").point(lambda v: int(v*fade))
                    img.putalpha(a_)
                frame.paste(img, (int(ICON_C[0]-img.width//2 + sgn*dist),
                                  int(ICON_C[1]-img.height//2 - 130*b)), img)
            # 星光迸发
            for i in range(12):
                a2 = math.radians(i*30 + 15)
                dist = 90 + 330*b
                sx = ICON_C[0] + math.cos(a2)*dist
                sy = ICON_C[1] + math.sin(a2)*dist
                col = [(255, 214, 120), (255, 150, 190), (255, 255, 255)][i % 3]
                r2 = max(3, int(16*(1-b)))
                draw_star(d, sx, sy, r2, col, 1-b)
        # 鼠标指针（移入→双击→消失）
        if t < 2.2:
            k = min(1.0, t/0.7)
            e = 1-(1-k)**3
            cx = 1000 + (ICON_C[0]-1000+10)*e
            cy2 = 1700 + (ICON_C[1]-1700+10)*e
            if 0.7 <= t < 1.05:                     # 双击抖动
                cx += math.sin((t-0.7)*90)*3
            draw_cursor(d, cx, cy2, 1.3)
    elif t < S1[1]:                                 # S1 打招呼
        spr = frame_of(3, t, 6)                     # 挥手
        sprite_at(spr, 720)
        a = min(1.0, max(0.0, (t-S1[0]-0.1)/0.5))
        y_t = int(340 + (1-a)*80)
        text_c(d, y_t, "Hi，我是 Vivian", F_TITLE, fill=(84, 40, 82), stroke=10, sfill=(255, 255, 255))
        if t > S1[0] + 0.4:
            text_c(d, y_t+150, "你的桌面小精灵", F_SUB, fill=(150, 110, 150))
        for sx, sy, ph in ((180, 420, 0), (880, 500, 2), (920, 1180, 4)):
            tw = 0.5 + 0.5*math.sin(t*4 + ph)
            r = int(14 + 10*tw)
            d.line([(sx-r, sy), (sx+r, sy)], fill=(255, 214, 120), width=5)
            d.line([(sx, sy-r), (sx, sy+r)], fill=(255, 214, 120), width=5)
    elif t < S2[1]:                                 # S2 桌面宠物
        draw_desktop(d, t)
        sprite_at(frame_of(0, t, 4), 780)           # 捧花待机
        text_c(d, 300, "Vivian 桌面宠物", F_TITLE, fill=(84, 40, 82), stroke=10)
        caption(d, "住在你电脑桌面上的 Q 版小宠物")
    elif t < S3[1]:                                 # S3 形态展示（蒙太奇）
        FORMS = [(1, "奔跑"), (4, "跳跃"), (6, "等待"), (8, "审阅")]
        seg = (S3[1] - S3[0]) / len(FORMS)
        row, name = FORMS[min(3, int((t - S3[0]) / seg))]
        spr = frame_of(row, t, 8)
        # 左右往返跑的位移（奔跑时）
        if row == 1:
            ph = (t - S3[0]) / seg
            off = int(160 * math.sin(ph * math.pi * 2))
        else:
            off = 0
        if off:
            frame.paste(spr, ((W - spr.width)//2 + off, 720), spr)
        else:
            sprite_at(spr, 720)
        draw_badge(d, (t - S3[0]) % seg, name, (156, 100, 200), y=1590)
        text_c(d, 320, "多种小形态", F_TITLE, fill=(84, 40, 82), stroke=10)
        caption(d, "奔跑 · 跳跃 · 等待 · 审阅 · 工作中…")
    elif t < S4[1]:                                 # S4 眼神跟随 + CPU 情绪
        p = t - S4[0]
        if p < 1.5:                                 # 眼神跟随鼠标
            base = cell(9, 0)
            ang = 40 + 280*min(1.0, p/1.5)
            spr = synth_eyes(base, angle_deg=ang)
            sprite_at(spr.resize((CW*SPR, CH*SPR), Image.LANCZOS), 720)
            hx, hy = W//2, 720 + 78*SPR
            r = 300
            cx = hx + r*math.sin(math.radians(ang))
            cy = hy - r*math.cos(math.radians(ang))
            draw_cursor(d, cx, cy)
            text_c(d, 320, "眼神会说话", F_TITLE, fill=(84, 40, 82), stroke=10)
            caption(d, "眼睛会一直跟着鼠标转")
        else:                                       # CPU 情绪
            happy = p < 2.75
            spr = frame_of(0, t, 4) if happy else frame_of(11, t, 8)
            sprite_at(spr, 720)
            if happy:
                draw_badge(d, p-1.5, "CPU 15% · 心情开心", (92, 184, 92), y=1590)
            else:
                draw_badge(d, p-2.75, "CPU 88% · 心情生气", (232, 78, 96), y=1590)
            text_c(d, 320, "感知电脑负载", F_TITLE, fill=(84, 40, 82), stroke=10)
            caption(d, "闲时捧花微笑 · 忙时抱臂生气")
    else:                                           # S5 开源预告
        sprite_at(frame_of(3, t, 6), 430)           # 挥手
        a = min(1.0, max(0.0, (t-S5[0]-0.1)/0.4))
        text_c(d, int(330 + (1-a)*60), "即将开源", F_TITLE, fill=(84, 40, 82), stroke=10)
        if t > S5[0] + 0.5:
            # 三个自定义功能胶囊
            pills = ["外观自定义", "动画自定义", "行为自定义"]
            pw = 270; gap = 24
            x0 = (W - (pw*3 + gap*2))//2
            for i, txt in enumerate(pills):
                x = x0 + i*(pw+gap)
                d.rounded_rectangle([x, 1330, x+pw, 1430], radius=40,
                                    fill=(255, 128, 170), outline=(255, 255, 255), width=3)
                bb = d.textbbox((0, 0), txt, font=F_SMALL)
                d.text((x + (pw-(bb[2]-bb[0]))//2, 1330 + (100-(bb[3]-bb[1]))//2 - bb[1]),
                       txt, font=F_SMALL, fill=(255, 255, 255))
        if t > S5[0] + 0.7:
            text_c(d, 1490, "近期开放 · 敬请期待", F_SUB, fill=(150, 110, 150))
        if t > S5[0] + 0.9:
            text_c(d, 1600, "Windows / Mac 双平台", F_SMALL, fill=(170, 140, 170))
        # 淡出
        if t > 14.55:
            k = (t-14.55)/0.45
            frame = Image.blend(frame, Image.new("RGB", (W, H), (255, 255, 255)), min(1.0, k))

    # 左下角著作人水印（常驻，淡色不抢戏）
    d.text((28, H-64), "Designed by Louis_QI", font=F_SMALL,
           fill=(255, 255, 255), stroke_width=3, stroke_fill=(150, 120, 160))

    writer.append_data(np.asarray(frame))

writer.close()
print("VIDEO_OK", OUT)
