# -*- coding: utf-8 -*-
"""Vivian 桌面宠物精灵图构建脚本 v6 — 举臂挥手 + 失败叹气。

变更（v5→v6）：
- waving 重做：肤色分割切下右臂（补洞修复裙子边缘），绕肩关节旋转合成
  "举手挥胳膊"动画：0→132° 举起 → ±15° 挥动两拍 → 收回
- failed 重做：叹气动画（吸气上挺 → 停顿 → 呼气下沉消沉 → 呼气云雾从嘴角飘出）
- 其余动画与 v5 完全一致（16 帧 × 14 行）

Designed by Louis_Qi for Vivian.
"""
import json
import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PET_DIR = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\my-qpet")
WORK = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\pet-work")

SRC_NEUTRAL = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-44.png"
SRC_DAISY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-47.png"
SRC_ANGRY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-47-18.png"
SRC_WINK = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-42.png"

CELL_W, CELL_H = 192, 208
COLS, ROWS = 16, 14
N_FRAMES = 16

# 叹气动画参数
SIGH_MOUTH = (48, 68)  # 嘴角在未缩放 sprite 中的坐标（cell (97,92) - paste 偏移 (49,24)）


# ─────────────────────────────────────────────
#  抠图（边缘泛洪 + 保留最大连通域）— 与 v5 一致
# ─────────────────────────────────────────────

def remove_background(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_bg(x, y):
        r, g, b, a = px[x, y]
        if a < 40:
            return True
        mx, mn = max(r, g, b), min(r, g, b)
        return (mx - mn) < 14 and (r + g + b) / 3 > 180

    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if is_bg(x, y) and not visited[y * w + x]:
                visited[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if is_bg(x, y) and not visited[y * w + x]:
                visited[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny * w + nx] and is_bg(nx, ny):
                visited[ny * w + nx] = 1
                q.append((nx, ny))

    alpha = img.getchannel("A").filter(ImageFilter.MinFilter(3))
    img.putalpha(alpha)

    a_px = img.getchannel("A").load()
    seen = bytearray(w * h)
    best, best_size = None, 0
    for sy in range(h):
        for sx in range(w):
            if a_px[sx, sy] > 10 and not seen[sy * w + sx]:
                comp = []
                q = deque([(sx, sy)])
                seen[sy * w + sx] = 1
                while q:
                    x, y = q.popleft()
                    comp.append((x, y))
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] and a_px[nx, ny] > 10:
                            seen[ny * w + nx] = 1
                            q.append((nx, ny))
                if len(comp) > best_size:
                    best, best_size = comp, len(comp)
    if best:
        keep = set(best)
        for y in range(h):
            for x in range(w):
                if a_px[x, y] > 10 and (x, y) not in keep:
                    a_px[x, y] = 0
    return img


def trim(img):
    bbox = img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    return img.crop(bbox) if bbox else img


def fit_base(img, target_h=178):
    w, h = img.size
    return img.resize((max(1, round(w * target_h / h)), target_h), Image.LANCZOS)


def scale_head(base: Image.Image, f: float, head_ratio: float = 0.52) -> Image.Image:
    if abs(f - 1.0) < 1e-3:
        return base
    w, h = base.size
    head_h = int(h * head_ratio)
    head = base.crop((0, 0, w, head_h))
    nw, nh = round(w * f), round(head_h * f)
    head_big = head.resize((nw, nh), Image.LANCZOS)
    canvas_w = max(w, nw)
    pad_top = max(0, nh - head_h)
    canvas_h = h + pad_top
    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    neck_y = head_h + pad_top
    body = base.crop((0, head_h, w, h))
    out.paste(body, ((canvas_w - w) // 2, neck_y), body)
    out.paste(head_big, ((canvas_w - nw) // 2, neck_y - nh), head_big)
    return out


def paste_fit(sprite: Image.Image, margin: int = 2) -> Image.Image:
    bbox = sprite.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if not bbox:
        return Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    avail_w, avail_h = CELL_W - margin * 2, CELL_H - margin * 2
    k = min(avail_w / bw, avail_h / bh, 1.0)
    if k < 1.0:
        sprite = sprite.resize((max(1, round(sprite.width * k)),
                                max(1, round(sprite.height * k))), Image.LANCZOS)
        bbox = sprite.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    sw, sh = sprite.size
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cell.paste(sprite, ((CELL_W - sw) // 2, CELL_H - 3 - sh), sprite)
    return cell


def make_frame(base, dx=0, dy=0, angle=0.0, flip=False, scale_y=1.0):
    """生成单元格帧；scale_y 用于叹气的压缩/舒展（体积近似守恒）。"""
    sprite = base.transpose(Image.FLIP_LEFT_RIGHT) if flip else base
    if abs(scale_y - 1.0) > 1e-3:
        w, h = sprite.size
        sy = scale_y
        sx = 1.0 + (1.0 - sy) * 0.6  # 压扁时略微变宽，近似守体积
        sprite = sprite.resize((max(1, round(w * sx)), max(1, round(h * sy))), Image.LANCZOS)
    if angle:
        sprite = sprite.rotate(angle, resample=Image.BICUBIC, expand=True)
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    sw, sh = sprite.size
    cell.paste(sprite, ((CELL_W - sw) // 2 + dx, (CELL_H - 6 - sh) + dy), sprite)
    return cell


def make_wink_frame(base, f, dy=0):
    sprite = trim(scale_head(base, f))
    w, h = sprite.size
    k = min((CELL_W - 4) / w, (CELL_H - 4) / h, 1.0)
    if k < 1.0:
        sprite = sprite.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
        w, h = sprite.size
    y = max(0, min(CELL_H - h, CELL_H - 3 - h + dy))
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cell.paste(sprite, ((CELL_W - w) // 2, y), sprite)
    return cell


# ─────────────────────────────────────────────
#  v6 新增：手臂分割（举臂挥手）
# ─────────────────────────────────────────────

_SKIN_REFS = [(248, 229, 217), (247, 222, 206), (240, 202, 187),
              (232, 168, 152), (219, 169, 154), (194, 134, 117)]


def _is_skin(p):
    r, g, b, a = p
    if a < 100:
        return False
    return any((r - s[0]) ** 2 + (g - s[1]) ** 2 + (b - s[2]) ** 2 < 2000
               for s in _SKIN_REFS)


def split_arm(cell: Image.Image):
    """从待机单元帧中切下画面右侧手臂。

    返回 (body 去臂图, arm_c 手臂 sprite, abb 手臂 bbox, (pvx,pvy) 肩关节, 肩部肤色)。
    切除后对裙子边缘的空洞做就近颜色填充。
    """
    px = cell.load()
    # 1) 手臂掩码：右上区域肤色最大连通域（避开脸颊：y>=106）
    mask = Image.new("L", cell.size, 0)
    mp = mask.load()
    for y in range(106, CELL_H):
        for x in range(110, CELL_W):
            if _is_skin(px[x, y]):
                mp[x, y] = 255
    seen = [[False] * CELL_H for _ in range(CELL_H)]
    best = []
    for sy in range(106, CELL_H):
        for sx in range(110, CELL_W):
            if mp[sx, sy] and not seen[sy][sx]:
                q = deque([(sx, sy)])
                seen[sy][sx] = True
                comp = []
                while q:
                    x, y = q.popleft()
                    comp.append((x, y))
                    for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                        if (110 <= nx < CELL_W and 106 <= ny < CELL_H
                                and not seen[ny][nx] and mp[nx, ny]):
                            seen[ny][nx] = True
                            q.append((nx, ny))
                if len(comp) > len(best):
                    best = comp
    # 2) 膨胀 1px 捕获抗锯齿边缘，轻微羽化
    mask2 = Image.new("L", cell.size, 0)
    mp2 = mask2.load()
    for (x, y) in best:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < CELL_W and 0 <= yy < CELL_H:
                    mp2[xx, yy] = 255
    mask2 = mask2.filter(ImageFilter.GaussianBlur(0.6))
    # 3) 身体 = 去臂
    body = cell.copy()
    body.putalpha(Image.composite(Image.new("L", cell.size, 0),
                                  body.getchannel("A"), mask2))
    # 4) 补洞：内部透明像素就近填充（手臂与裙边重叠处）
    ap = body.load()
    outside = [[False] * CELL_H for _ in range(CELL_H)]
    q = deque()
    for x in range(CELL_W):
        for y in (0, CELL_H - 1):
            if ap[x, y][3] < 10 and not outside[y][x]:
                outside[y][x] = True
                q.append((x, y))
    for y in range(CELL_H):
        for x in (0, CELL_W - 1):
            if ap[x, y][3] < 10 and not outside[y][x]:
                outside[y][x] = True
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (0 <= nx < CELL_W and 0 <= ny < CELL_H
                    and not outside[ny][nx] and ap[nx, ny][3] < 10):
                outside[ny][nx] = True
                q.append((nx, ny))
    holes = {(x, y): None for y in range(CELL_H) for x in range(CELL_W)
             if ap[x, y][3] < 10 and not outside[y][x]}
    frontier = []
    for (x, y) in holes:
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in holes and ap[nx, ny][3] > 10:
                frontier.append((nx, ny))
    while frontier:
        nf = []
        for (fx, fy) in frontier:
            c = ap[fx, fy]
            for nx, ny in ((fx + 1, fy), (fx - 1, fy), (fx, fy + 1), (fx, fy - 1)):
                if (nx, ny) in holes and holes[(nx, ny)] is None:
                    holes[(nx, ny)] = c
                    ap[nx, ny] = (c[0], c[1], c[2], 255)
                    nf.append((nx, ny))
        frontier = nf
    # 5) 手臂 sprite 与肩关节
    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    top = [p for p in best if p[1] <= min(ys) + 1]
    pvx = sum(p[0] for p in top) // len(top)
    pvy = min(ys) + 2
    arm = Image.new("RGBA", cell.size, (0, 0, 0, 0))
    arm.paste(cell, (0, 0), mask2)
    abb = mask2.getbbox()
    arm_c = arm.crop(abb)
    # 肩部补丁颜色（肩关节附近的肤色）
    shade = ap[pvx, max(0, pvy - 4)][:3] if ap[pvx, max(0, pvy - 4)][3] > 10 else (247, 224, 209)
    return body, arm_c, abb, (pvx, pvy), shade


def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3


def _ease_in_cubic(t):
    return t ** 3


def frames_for_waving(cell_base: Image.Image):
    """举臂挥手：0→132° 举起（缓出）→ ±15° 挥动两拍 → 缓入收回。"""
    body, arm_c, abb, (pvx, pvy), shade = split_arm(cell_base)
    RAISE, AMP = 132.0, 15.0

    def compose(angle, dy=0.0):
        frm = body.copy()
        layer = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
        layer.paste(arm_c, (abb[0], abb[1]))
        rot = layer.rotate(angle, center=(pvx, pvy - dy), resample=Image.BICUBIC)
        frm.alpha_composite(rot)
        d = ImageDraw.Draw(frm)
        py = pvy - dy
        d.ellipse([pvx - 5, py - 4, pvx + 5, py + 5], fill=shade + (255,))
        if dy:
            frm = frm.transform(
                (CELL_W, CELL_H), Image.AFFINE, (1, 0, 0, 0, 1, dy),
                resample=Image.BICUBIC)
        return frm

    angles = [0.0] * N_FRAMES
    for i in range(1, 5):          # 举起（缓出）
        angles[i] = RAISE * _ease_out_cubic(i / 4)
    for i in range(5, 12):         # 挥动两拍
        angles[i] = RAISE + AMP * math.sin(2 * math.pi * (i - 5) / 3.5)
    for i in range(12, 16):        # 收回（缓入）
        angles[i] = RAISE * (1 - _ease_in_cubic((i - 11) / 4))

    return [compose(a) for a in angles]


# ─────────────────────────────────────────────
#  v6 新增：失败叹气
# ─────────────────────────────────────────────

def frames_for_sigh(base: Image.Image):
    """叹气：吸气上挺 → 停顿 → 呼气下沉消沉 → 云雾从嘴角飘出。

    16 帧 @4fps（4s 循环）：0-3 吸气 / 4-5 顶点 / 6-9 呼气下沉 / 10-15 消沉呼吸。
    云雾在帧 7/8/9 依次发出，向上飘散渐隐。
    """
    frames = []
    # 每帧身体姿态： (dy, scale_y, angle)
    poses = []
    for i in range(N_FRAMES):
        if i < 4:      # 吸气
            k = i / 4
            poses.append((-3.0 * k, 1.0 + 0.02 * k, -1.2 * k))
        elif i < 6:    # 顶点
            poses.append((-3.0, 1.02, -1.2))
        elif i < 10:   # 呼气下沉
            k = (i - 6) / 4
            poses.append((-3.0 + 7.0 * k, 1.02 - 0.045 * k, -1.2 + 3.2 * k))
        else:          # 消沉呼吸
            k = (i - 10) / 6
            poses.append((4.0 - 1.5 * math.sin(math.pi * k), 0.975, 2.0))

    puff_tiles = {}
    def puff_tile(r):
        if r in puff_tiles:
            return puff_tiles[r]
        ss = 4
        size = r * 2 + 6
        tile = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        d.ellipse([3 * ss, 3 * ss, (size - 3) * ss, (size - 3) * ss],
                  fill=(252, 250, 248, 255))
        tile = tile.resize((size, size), Image.LANCZOS).filter(
            ImageFilter.GaussianBlur(1.2))
        puff_tiles[r] = tile
        return tile

    _cloud_cache = {}
    def _sigh_cloud(sc, alpha):
        """卡通叹气云：一大两小的三团圆，白色柔边。"""
        key = (round(sc, 2), alpha // 8)
        if key in _cloud_cache:
            return _cloud_cache[key]
        base_w, base_h = 34, 20
        w, h = max(4, int(base_w * sc)), max(4, int(base_h * sc))
        ss = 4
        tile = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        def ell(cx, cy, r):
            d.ellipse([(cx - r) * ss, (cy - r) * ss, (cx + r) * ss, (cy + r) * ss],
                      fill=(250, 248, 246, 255))
        ell(w * 0.5, h * 0.55, w * 0.16)   # 大团
        ell(w * 0.28, h * 0.62, w * 0.11)  # 左小团
        ell(w * 0.72, h * 0.60, w * 0.125) # 右小团
        tile = tile.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.7))
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha / 255)))
        _cloud_cache[key] = tile
        return tile

    for i in range(N_FRAMES):
        dy, sy, ang = poses[i]
        cell = make_frame(base, dy=round(dy), angle=ang, scale_y=sy)
        # 帧内 sprite 实际位置（缩放/位移后），用于锚定叹气云
        sprite_h = round(base.height * sy)
        sprite_w = round(base.width * (1.0 + (1.0 - sy) * 0.6))
        k = sprite_h / base.height
        px0 = (CELL_W - sprite_w) // 2
        py0 = CELL_H - 6 - sprite_h + round(dy)
        # 叹气云：帧 6 发出，头侧上方一朵卡通小云向上飘散渐隐（深色背景衬托）
        start = 6
        if i >= start:
            p = (i - start) / 8.0
            if p <= 1.0:
                life = min(1.0, p)
                grow = min(1.0, life * 3.0)          # 前 1/3 长出
                fade = (1.0 - life) ** 1.1           # 之后渐隐
                alpha = int(235 * fade)
                if alpha > 4:
                    ax = px0 + 86 * k + 16            # 头右侧外
                    ay = py0 + 51 * k - 6 - 16 * life  # 向上飘
                    sc = grow * (1.0 + 0.25 * life)
                    cloud = _sigh_cloud(sc, alpha)
                    cell.alpha_composite(cloud, (int(ax - cloud.width / 2),
                                                 int(ay - cloud.height / 2)))
        frames.append(cell)
    return frames


# ─────────────────────────────────────────────
#  其余动画 — 与 v5 一致
# ─────────────────────────────────────────────

def frames_for(base, state):
    out, n = [], N_FRAMES
    if state == "idle":
        for i in range(n):
            t = i / n
            out.append(make_frame(base, dx=round(1.5 * math.sin(2 * math.pi * t)),
                                  dy=round(3.0 * math.sin(2 * math.pi * t))))
    elif state == "wink":
        scales = [1.00, 1.05, 1.11, 1.18, 1.23, 1.27,
                  1.27, 1.27, 1.27, 1.27,
                  1.24, 1.20, 1.15, 1.10, 1.05, 1.00]
        for i in range(n):
            dy = round(1.5 * math.sin(2 * math.pi * i / n))
            out.append(make_wink_frame(base, scales[i], dy=dy))
    elif state in ("running-right", "running"):
        for i in range(n):
            phase = i / n
            dy = round(3 * abs(math.sin(2 * math.pi * phase))) * -1 + 2
            sway = round(2 * math.sin(2 * math.pi * phase))
            out.append(make_frame(base, dx=sway, dy=dy,
                                  angle=4 * math.sin(2 * math.pi * phase)))
    elif state == "running-left":
        for i in range(n):
            phase = i / n
            dy = round(3 * abs(math.sin(2 * math.pi * phase))) * -1 + 2
            sway = round(2 * math.sin(2 * math.pi * phase))
            out.append(make_frame(base, dx=sway, dy=dy,
                                  angle=4 * math.sin(2 * math.pi * phase),
                                  flip=True))
    elif state == "jumping":
        dys = [4, 0, -6, -12, -16, -18, -16, -12,
               -8, -4, 0, 3, 5, 4, 3, 4]
        out = [make_frame(base, dy=d) for d in dys]
    elif state == "waiting":
        for i in range(n):
            t = i / n
            out.append(make_frame(base,
                                  angle=2.5 * math.sin(2 * math.pi * t / 2),
                                  dy=round(1.5 * math.sin(2 * math.pi * t))))
    elif state == "review":
        for i in range(n):
            t = i / n
            out.append(make_frame(base,
                                  dx=round(3 * math.sin(2 * math.pi * t)),
                                  angle=2 * math.sin(2 * math.pi * t)))
    elif state == "angry":
        for i in range(n):
            phase = i / n
            dx = round(3 * math.sin(2 * math.pi * phase * 2))
            dy = 1 if i % 4 < 2 else 3
            out.append(make_frame(base, dx=dx, dy=dy,
                                  angle=2.5 * math.sin(2 * math.pi * phase * 2)))
    elif state == "idle-plain":
        for i in range(n):
            t = i / n
            out.append(make_frame(base, dy=round(2 * math.sin(2 * math.pi * t))))
    else:
        out = [make_frame(base)] * n
    return out


def main():
    print("抠图：中性 / 雏菊 / 生气 / wink（全部无描边素材）")
    neutral = fit_base(trim(remove_background(Image.open(SRC_NEUTRAL))))
    daisy = fit_base(trim(remove_background(Image.open(SRC_DAISY))))
    angry = fit_base(trim(remove_background(Image.open(SRC_ANGRY))))
    wink = fit_base(trim(remove_background(Image.open(SRC_WINK))))
    print("  尺寸:", neutral.size, daisy.size, angry.size, wink.size)

    neutral_cell = make_frame(neutral)

    def gen(state, base):
        if state == "waving":
            return frames_for_waving(neutral_cell)
        if state == "failed":
            return frames_for_sigh(base)
        return frames_for(base, state)

    rows = {
        0: ("idle", daisy),
        1: ("running-right", neutral),
        2: ("running-left", neutral),
        3: ("waving", neutral),
        4: ("jumping", neutral),
        5: ("failed", neutral),
        6: ("waiting", neutral),
        7: ("running", neutral),
        8: ("review", neutral),
        11: ("angry", angry),
        12: ("idle-plain", neutral),
        13: ("wink", wink),
    }

    atlas = Image.new("RGBA", (COLS * CELL_W, ROWS * CELL_H), (0, 0, 0, 0))
    anims = []
    labels = {"idle": "待机(捧花)", "running-right": "向右跑", "running-left": "向左跑",
              "waving": "挥手(举臂)", "jumping": "跳跃", "failed": "失败(叹气)",
              "waiting": "等待", "running": "工作中", "review": "审阅",
              "angry": "生气", "idle-plain": "安静待机", "wink": "眨眼"}
    for row, (name, base) in rows.items():
        frames = gen(name, base)
        for col in range(min(len(frames), COLS)):
            atlas.paste(frames[col], (col * CELL_W, row * CELL_H), frames[col])
        anims.append({"name": name, "label": labels[name], "row": row,
                      "frameCount": N_FRAMES,
                      "fps": 8 if name == "angry" else (
                          4 if name.startswith("idle") or name in ("wink", "failed") else 6),
                      "repeat": True, "loop": True})
        print(f"  行 {row}: {name}  ({len(frames)} 帧)")

    # 注视帧占位（行 9-10）
    idle0 = make_frame(neutral)
    for row in (9, 10):
        for col in range(COLS):
            atlas.paste(idle0, (col * CELL_W, row * CELL_H), idle0)

    PET_DIR.mkdir(exist_ok=True)
    atlas.save(PET_DIR / "spritesheet.png")
    atlas.save(PET_DIR / "spritesheet.webp", "webp", quality=85, lossless=False)
    print("精灵图:", atlas.size, "→ spritesheet.png / .webp")

    gazes = []
    angles = [0.0, 22.5, 45.0, 67.5, 90.0, 112.5, 135.0, 157.5,
              180.0, 202.5, 225.0, 247.5, 270.0, 292.5, 315.0, 337.5]
    dirs = ["up", "up-right", "up-right", "up-right", "right", "down-right", "down-right", "down-right",
            "down", "down-left", "down-left", "down-left", "left", "up-left", "up-left", "up-left"]
    for i, (a, d) in enumerate(zip(angles, dirs)):
        gazes.append({"name": f"gaze-{a:05.1f}", "label": d, "angle": a,
                      "row": 9 + i // 8, "col": i % 8, "type": "gaze"})

    cfg = {
        "name": "Q版小裙裙",
        "description": "Vivian 桌面宠物（举臂挥手 / 失败叹气 / CPU 情绪联动 / 自然眨眼 / wink 提醒 / 语音包）",
        "author": "Louis_Qi",
        "credit": "Designed by Louis_Qi for Vivian",
        "version": "4.3.0",
        "spriteVersionNumber": 6,
        "sprite": {"image": "spritesheet.webp", "cell": {"width": CELL_W, "height": CELL_H},
                   "cols": COLS, "rows": ROWS, "atlasWidth": COLS * CELL_W, "atlasHeight": ROWS * CELL_H},
        "animations": anims, "gazes": gazes,
    }
    with open(PET_DIR / "pet.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("pet.json 写入完成（12 动画 ×16 帧 + 16 注视）v4.3.0")

    # ── 验证输出：挥手/失败行关键帧 ──
    check = Image.new("RGBA", (CELL_W * 4, CELL_H * 2), (40, 40, 40, 255))
    for i, col in enumerate((0, 2, 5, 8)):
        check.paste(atlas.crop((col * CELL_W, 3 * CELL_H, col * CELL_W + CELL_W,
                                3 * CELL_H + CELL_H)), (i * CELL_W, 0))
    for i, col in enumerate((0, 4, 7, 12)):
        check.paste(atlas.crop((col * CELL_W, 5 * CELL_H, col * CELL_W + CELL_W,
                                5 * CELL_H + CELL_H)), (i * CELL_W, CELL_H))
    check.save(WORK / "_v6_check_waving_failed.png")
    print("关键帧预览 → pet-work/_v6_check_waving_failed.png")


if __name__ == "__main__":
    main()
