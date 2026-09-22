import json
import math
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PET_DIR = PROJECT_ROOT / "assets"
WORK = PROJECT_ROOT / "scripts" / "raw_assets"

SRC_NEUTRAL = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-44.png"
SRC_DAISY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-47.png"
SRC_ANGRY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-47-18.png"
SRC_WINK = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-42.png"

CELL_W, CELL_H = 192, 208
COLS, ROWS = 16, 14
N_FRAMES = 16

SIGH_MOUTH = (48, 68)

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
    sprite = base.transpose(Image.FLIP_LEFT_RIGHT) if flip else base
    if abs(scale_y - 1.0) > 1e-3:
        w, h = sprite.size
        sy = scale_y
        sx = 1.0 + (1.0 - sy) * 0.6
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

_SKIN_REFS = [(248, 229, 217), (247, 222, 206), (240, 202, 187),
              (232, 168, 152), (219, 169, 154), (194, 134, 117)]

def _is_skin(p):
    r, g, b, a = p
    if a < 100:
        return False
    return any((r - s[0]) ** 2 + (g - s[1]) ** 2 + (b - s[2]) ** 2 < 2000
               for s in _SKIN_REFS)

def split_arm(cell: Image.Image):
    px = cell.load()

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

    mask2 = Image.new("L", cell.size, 0)
    mp2 = mask2.load()
    for (x, y) in best:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                xx, yy = x + dx, y + dy
                if 0 <= xx < CELL_W and 0 <= yy < CELL_H:
                    mp2[xx, yy] = 255
    mask2 = mask2.filter(ImageFilter.GaussianBlur(0.6))

    body = cell.copy()
    body.putalpha(Image.composite(Image.new("L", cell.size, 0),
                                  body.getchannel("A"), mask2))

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

    xs = [p[0] for p in best]
    ys = [p[1] for p in best]
    top = [p for p in best if p[1] <= min(ys) + 1]
    pvx = sum(p[0] for p in top) // len(top)
    pvy = min(ys) + 2
    arm = Image.new("RGBA", cell.size, (0, 0, 0, 0))
    arm.paste(cell, (0, 0), mask2)
    abb = mask2.getbbox()
    arm_c = arm.crop(abb)

    shade = ap[pvx, max(0, pvy - 4)][:3] if ap[pvx, max(0, pvy - 4)][3] > 10 else (247, 224, 209)
    return body, arm_c, abb, (pvx, pvy), shade

def _ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def _ease_in_cubic(t):
    return t ** 3

def frames_for_waving(cell_base: Image.Image):
    body, arm_c, abb, (pvx, pvy), shade = split_arm(cell_base)
    RAISE, AMP = 132.0, 15.0

    apx = arm_c.load()
    ax = ay = n = 0
    for yy in range(arm_c.height):
        for xx in range(arm_c.width):
            if apx[xx, yy][3] > 128:
                gx, gy = xx + abb[0], yy + abb[1]
                if math.hypot(gx - pvx, gy - pvy) > 30:
                    ax += gx - pvx
                    ay += gy - pvy
                    n += 1
    if n:
        L = math.hypot(ax, ay) or 1.0
        ux, uy = ax / L, ay / L
    else:
        ux, uy = 0.4, 0.92

    _soft_cache = {}

    def soft_e(rx, ry, color, blur, ss=4):
        key = (rx, ry, color, blur)
        if key in _soft_cache:
            return _soft_cache[key]
        w = int(rx * 2 + blur * 4 + 2)
        h = int(ry * 2 + blur * 4 + 2)
        t = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        dd = ImageDraw.Draw(t)
        dd.ellipse([w * ss / 2 - rx * ss, h * ss / 2 - ry * ss,
                    w * ss / 2 + rx * ss, h * ss / 2 + ry * ss],
                   fill=color + (255,))
        t = t.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(blur))
        _soft_cache[key] = (t, w // 2, h // 2)
        return _soft_cache[key]

    def compose(angle):
        frm = body.copy()
        layer = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
        layer.paste(arm_c, (abb[0], abb[1]))
        if angle > 0.5:

            bc, hw, hh = soft_e(8.0, 7.0, shade, 1.2)
            frm.alpha_composite(bc, (pvx - 2 - hw, pvy + 1 - hh))

            ac, hw, hh = soft_e(6.5, 5.0, shade, 0.8)
            layer.alpha_composite(ac, (int(pvx + ux * 2) - hw, int(pvy + uy * 2) - hh))
        rot = layer.rotate(angle, center=(pvx, pvy), resample=Image.BICUBIC)
        frm.alpha_composite(rot)
        return frm

    angles = [0.0] * N_FRAMES
    for i in range(1, 5):
        angles[i] = RAISE * _ease_out_cubic(i / 4)
    for i in range(5, 12):
        angles[i] = RAISE + AMP * math.sin(2 * math.pi * (i - 5) / 3.5)
    for i in range(12, 16):
        angles[i] = RAISE * (1 - _ease_in_cubic((i - 11) / 4))

    return [compose(a) for a in angles]

def frames_for_sigh(base: Image.Image):
    frames = []

    poses = []
    for i in range(N_FRAMES):
        if i < 4:
            k = i / 4
            poses.append((-3.0 * k, 1.0 + 0.02 * k, -1.2 * k))
        elif i < 6:
            poses.append((-3.0, 1.02, -1.2))
        elif i < 10:
            k = (i - 6) / 4
            poses.append((-3.0 + 7.0 * k, 1.02 - 0.045 * k, -1.2 + 3.2 * k))
        else:
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
        ell(w * 0.5, h * 0.55, w * 0.16)
        ell(w * 0.28, h * 0.62, w * 0.11)
        ell(w * 0.72, h * 0.60, w * 0.125)
        tile = tile.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.7))
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha / 255)))
        _cloud_cache[key] = tile
        return tile

    for i in range(N_FRAMES):
        dy, sy, ang = poses[i]
        cell = make_frame(base, dy=round(dy), angle=ang, scale_y=sy)

        sprite_h = round(base.height * sy)
        sprite_w = round(base.width * (1.0 + (1.0 - sy) * 0.6))
        k = sprite_h / base.height
        px0 = (CELL_W - sprite_w) // 2
        py0 = CELL_H - 6 - sprite_h + round(dy)

        start = 6
        if i >= start:
            p = (i - start) / 8.0
            if p <= 1.0:
                life = min(1.0, p)
                grow = min(1.0, life * 3.0)
                fade = (1.0 - life) ** 1.1
                alpha = int(235 * fade)
                if alpha > 4:
                    ax = px0 + 86 * k + 16
                    ay = py0 + 51 * k - 6 - 16 * life
                    sc = grow * (1.0 + 0.25 * life)
                    cloud = _sigh_cloud(sc, alpha)
                    cell.alpha_composite(cloud, (int(ax - cloud.width / 2),
                                                 int(ay - cloud.height / 2)))
        frames.append(cell)
    return frames

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

_REF_CELL = (9, 0)
_REF_EYES = ((77, 81), (114, 80))

_BLINK_ROWS = {"idle": 0, "waving": 3, "waiting": 6, "review": 8, "idle-plain": 12}

def _ncc_eye_search(frame, tmpl, tmask, ex, ey, rad=9):
    ph, pw = tmask.shape
    H, W = frame.shape[:2]
    best, bs = (ex, ey), -2.0
    for dy in range(-rad, rad + 1):
        for dx in range(-rad, rad + 1):
            x0, y0 = ex - pw // 2 + dx, ey - ph // 2 + dy
            if x0 < 0 or y0 < 0 or x0 + pw > W or y0 + ph > H:
                continue
            crop = frame[y0:y0 + ph, x0:x0 + pw]
            m = tmask & (crop[:, :, 3] > 128)
            if m.sum() < 50:
                continue
            a = crop[:, :, :3][m].ravel()
            b = tmpl[:, :, :3][m].ravel()
            a = a - a.mean()
            b = b - b.mean()
            den = math.sqrt(float((a * a).sum()) * float((b * b).sum())) + 1e-6
            s = float((a * b).sum() / den)
            if s > bs:
                bs, best = s, (x0 + pw // 2, y0 + ph // 2)
    return best[0], best[1], bs

def build_eye_tracks(atlas: Image.Image) -> dict:
    arr = np.asarray(atlas, dtype=np.float32)
    rx0, ry0 = _REF_CELL[1] * CELL_W, _REF_CELL[0] * CELL_H
    ref = arr[ry0:ry0 + CELL_H, rx0:rx0 + CELL_W]
    PHW, PHH = 13, 10
    tracks = {}
    for name, row in sorted(_BLINK_ROWS.items()):
        per_frame = []
        min_score = 2.0
        for col in range(N_FRAMES):
            fx0, fy0 = col * CELL_W, row * CELL_H
            frame = arr[fy0:fy0 + CELL_H, fx0:fx0 + CELL_W]
            frame_pts = []
            for (ex, ey) in _REF_EYES:
                tmpl = ref[ey - PHH:ey + PHH, ex - PHW:ex + PHW]
                tmask = tmpl[:, :, 3] > 128
                bx, by, sc = _ncc_eye_search(frame, tmpl, tmask, ex, ey)
                min_score = min(min_score, sc)
                frame_pts.extend([int(bx), int(by)])
            per_frame.append(frame_pts)
        tracks[name] = per_frame
        print(f"  眼睛跟踪 {name}: f0={per_frame[0]} f8={per_frame[8]} "
              f"(最低匹配分 {min_score:.3f})")
    return tracks

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

    idle0 = make_frame(neutral)
    for row in (9, 10):
        for col in range(COLS):
            atlas.paste(idle0, (col * CELL_W, row * CELL_H), idle0)

    eye_tracks = build_eye_tracks(atlas)

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
        "version": "1.0.2",
        "spriteVersionNumber": 7,
        "eyeTracks": eye_tracks,
        "sprite": {"image": "spritesheet.webp", "cell": {"width": CELL_W, "height": CELL_H},
                   "cols": COLS, "rows": ROWS, "atlasWidth": COLS * CELL_W, "atlasHeight": ROWS * CELL_H},
        "animations": anims, "gazes": gazes,
    }
    with open(PET_DIR / "pet.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("pet.json 写入完成（12 动画 ×16 帧 + 16 注视 + 眼睛跟踪）")

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
