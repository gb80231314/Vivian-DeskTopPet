# -*- coding: utf-8 -*-
"""Vivian 桌面宠物精灵图构建脚本 v5 — 修复 wink 头部放大裁切。

变更（v4→v5）：
- scale_head 重写：放大后的头部合成到"扩展画布"上，不再被原图边界裁掉
  （v4 中 f=1.27 时头顶上溢 ~25px、左右各溢 ~12px 被 PIL 静默切平）
- wink 帧增加 fit-to-cell 安全缩放：内容超出 192x208 单元格时整体等比缩小，
  保证头部放大的同时绝无缺失
- 其余动画与 v4 完全一致（16 帧 × 14 行）

Designed by Louis_Qi for Vivian.
"""
import json
import math
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

PET_DIR = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\my-qpet")
WORK = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\pet-work")

SRC_NEUTRAL = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-44.png"
SRC_DAISY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-47.png"
SRC_ANGRY = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-47-18.png"
SRC_WINK = WORK / "保持这个_Q_版_chibi_卡通女孩形象完全一致_黑色盘发_2026-09-18T11-46-42.png"

CELL_W, CELL_H = 192, 208
COLS, ROWS = 16, 14
N_FRAMES = 16


# ─────────────────────────────────────────────
#  抠图（边缘泛洪 + 保留最大连通域）
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
    """把头部区域（顶部 head_ratio 部分）以脖子为锚点放大 f 倍。

    v5 修复：合成到"扩展画布"（取 max(原宽, 放大头宽) × 原高+上溢），
    头部不会被原图边界裁掉；身体保持原尺寸并居中，脖子接缝对齐。
    """
    if abs(f - 1.0) < 1e-3:
        return base
    w, h = base.size
    head_h = int(h * head_ratio)
    head = base.crop((0, 0, w, head_h))
    nw, nh = round(w * f), round(head_h * f)
    head_big = head.resize((nw, nh), Image.LANCZOS)

    # 扩展画布：宽度容纳放大头，顶部预留上溢空间
    canvas_w = max(w, nw)
    pad_top = max(0, nh - head_h)
    canvas_h = h + pad_top
    out = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # 脖子线在画布上的新 y 坐标
    neck_y = head_h + pad_top
    # 身体：水平居中，顶边贴脖子线
    body = base.crop((0, head_h, w, h))
    out.paste(body, ((canvas_w - w) // 2, neck_y), body)
    # 放大头：底边贴脖子线（锚点），水平居中
    out.paste(head_big, ((canvas_w - nw) // 2, neck_y - nh), head_big)
    return out


def paste_fit(sprite: Image.Image, margin: int = 2) -> Image.Image:
    """把 sprite 放入 192x208 单元格；内容超出时整体等比缩小（不裁切）。"""
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
    # 底部对齐（留 3px），水平居中
    cell.paste(sprite, ((CELL_W - sw) // 2, CELL_H - 3 - sh), sprite)
    return cell


def make_frame(base, dx=0, dy=0, angle=0.0, flip=False):
    sprite = base.transpose(Image.FLIP_LEFT_RIGHT) if flip else base
    if angle:
        sprite = sprite.rotate(angle, resample=Image.BICUBIC, expand=True)
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    sw, sh = sprite.size
    cell.paste(sprite, ((CELL_W - sw) // 2 + dx, (CELL_H - 6 - sh) + dy), sprite)
    return cell


def make_wink_frame(base, f, dy=0):
    """wink 帧：头部放大 f 倍（无裁切）+ 上下浮动。

    先 trim 到内容紧致 bbox，若超出单元格安全区（左右各 2px / 上下各 2px）
    则整体等比缩小，最后底部对齐（留 3px）+ 浮动偏移（clamp 防越界）。
    """
    sprite = trim(scale_head(base, f))
    w, h = sprite.size
    k = min((CELL_W - 4) / w, (CELL_H - 4) / h, 1.0)
    if k < 1.0:
        sprite = sprite.resize((max(1, round(w * k)), max(1, round(h * k))),
                               Image.LANCZOS)
        w, h = sprite.size
    y = max(0, min(CELL_H - h, CELL_H - 3 - h + dy))
    cell = Image.new("RGBA", (CELL_W, CELL_H), (0, 0, 0, 0))
    cell.paste(sprite, ((CELL_W - w) // 2, y), sprite)
    return cell


def frames_for(base, state):
    """生成 16 帧动画。"""
    out, n = [], N_FRAMES
    if state == "idle":  # 捧花开心的待机（呼吸+轻微摆动）
        for i in range(n):
            t = i / n
            out.append(make_frame(base, dx=round(1.5 * math.sin(2 * math.pi * t)),
                                  dy=round(3.0 * math.sin(2 * math.pi * t))))
    elif state == "wink":  # 16 关键帧头部放大曲线（v5: 头部完整不裁切）
        # sin 形 ease-in-out：0→1.27→保持 5 帧→1.0
        scales = [1.00, 1.05, 1.11, 1.18, 1.23, 1.27,
                  1.27, 1.27, 1.27, 1.27,
                  1.24, 1.20, 1.15, 1.10, 1.05, 1.00]
        for i in range(n):
            dy = round(1.5 * math.sin(2 * math.pi * i / n))
            out.append(make_wink_frame(base, scales[i], dy=dy))
    elif state in ("running-right", "running"):  # 跑动（步幅更密）
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
    elif state == "waving":  # 挥手
        for i in range(n):
            t = i / n
            out.append(make_frame(base,
                                  angle=3 * math.sin(2 * math.pi * t),
                                  dy=round(1.5 * math.sin(2 * math.pi * t))))
    elif state == "jumping":  # 跳跃（更密的抛物线关键帧）
        dys = [4, 0, -6, -12, -16, -18, -16, -12,
               -8, -4, 0, 3, 5, 4, 3, 4]
        out = [make_frame(base, dy=d) for d in dys]
    elif state == "failed":  # 失败（左右摇）
        out = [make_frame(base, dy=4 + (i % 2), angle=-7 + (i % 2) * 2) for i in range(n)]
    elif state == "waiting":
        for i in range(n):
            t = i / n
            out.append(make_frame(base,
                                  angle=2.5 * math.sin(2 * math.pi * t / 2),
                                  dy=round(1.5 * math.sin(2 * math.pi * t))))
    elif state == "review":  # 审阅（小幅摆动）
        for i in range(n):
            t = i / n
            out.append(make_frame(base,
                                  dx=round(3 * math.sin(2 * math.pi * t)),
                                  angle=2 * math.sin(2 * math.pi * t)))
    elif state == "angry":  # 生气：快速左右发抖 + 跺脚
        for i in range(n):
            phase = i / n
            dx = round(3 * math.sin(2 * math.pi * phase * 2))
            dy = 1 if i % 4 < 2 else 3
            out.append(make_frame(base, dx=dx, dy=dy,
                                  angle=2.5 * math.sin(2 * math.pi * phase * 2)))
    elif state == "idle-plain":  # 中性待机
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
              "waving": "挥手", "jumping": "跳跃", "failed": "失败", "waiting": "等待",
              "running": "工作中", "review": "审阅", "angry": "生气", "idle-plain": "安静待机",
              "wink": "眨眼"}
    for row, (name, base) in rows.items():
        frames = frames_for(base, name)
        for col in range(min(len(frames), COLS)):
            atlas.paste(frames[col], (col * CELL_W, row * CELL_H), frames[col])
        anims.append({"name": name, "label": labels[name], "row": row,
                      "frameCount": N_FRAMES,
                      "fps": 8 if name == "angry" else (4 if name.startswith("idle") or name == "wink" else 6),
                      "repeat": True, "loop": True})
        print(f"  行 {row}: {name}  ({len(frames)} 帧)")

    # 注视帧占位（行 9-10）：每格用同一中性帧，运行时按 gaze 角度叠加移动的瞳孔
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
        "description": "Vivian 桌面宠物（无描边软边 / 雏菊待机 / CPU 情绪联动 / 自然眨眼 / 长时间无点击 wink）",
        "author": "Louis_Qi",
        "credit": "Designed by Louis_Qi for Vivian",
        "version": "4.1.0",
        "spriteVersionNumber": 5,
        "sprite": {"image": "spritesheet.webp", "cell": {"width": CELL_W, "height": CELL_H},
                   "cols": COLS, "rows": ROWS, "atlasWidth": COLS * CELL_W, "atlasHeight": ROWS * CELL_H},
        "animations": anims, "gazes": gazes,
    }
    with open(PET_DIR / "pet.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("pet.json 写入完成（12 动画 ×16 帧 + 16 注视）")
    print("署名:", cfg["credit"])
    print(f"精灵图尺寸: {COLS*CELL_W}x{ROWS*CELL_H} (列{COLS}×行{ROWS})")

    # ── 验证：wink 行头部完整性（与未缩放基准帧对比头顶/两侧内容量） ──
    print("\n验证 wink 行（行 13）:")
    plain = trim(wink)
    plain_bb = plain.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    for col in (0, 5, 8):
        cell = atlas.crop((col * CELL_W, 13 * CELL_H, col * CELL_W + CELL_W, 13 * CELL_H + CELL_H))
        bb = cell.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
        w_, h_ = bb[2] - bb[0], bb[3] - bb[1]
        # 缩放比 = 内容宽高相对基准，头部完整时宽高比应接近 1:1 联动放大
        print(f"  col{col:2d}: bbox={bb} 内容 {w_}x{h_}（基准 {plain_bb[2]-plain_bb[0]}x{plain_bb[3]-plain_bb[1]}）"
              f" 触边={'是' if (bb[0] <= 0 or bb[2] >= CELL_W or bb[1] <= 0 or bb[3] >= CELL_H) else '否'}")


if __name__ == "__main__":
    main()
