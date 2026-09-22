# -*- coding: utf-8 -*-
"""Vivian 艺术字 → 透明底 ico 图标。"""
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

WORK = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\pet-work")
SRC = WORK / "优雅的英文艺术字__Vivian__流畅的手写花体书法字体__2026-09-18T11-46-47.png"
OUT_ICO = Path(r"F:\AiWorkProject\2026-09-17-22-43-10\qpet-app\vivian.ico")
OUT_PNG = WORK / "vivian_icon_preview.png"


def remove_white(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_bg(x, y):
        r, g, b, a = px[x, y]
        if a < 40:
            return True
        mx, mn = max(r, g, b), min(r, g, b)
        return (mx - mn) < 10 and (r + g + b) / 3 > 215

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

    # 轻微软化边缘，去白边
    alpha = img.getchannel("A").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.6))
    img.putalpha(alpha)

    # 保留最大连通域（去水印残迹）
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


def main():
    img = remove_white(Image.open(SRC))
    bbox = img.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    img = img.crop(bbox)
    print("内容尺寸:", img.size)

    # 方形画布 + 6% 边距
    side = int(max(img.size) * 1.12)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2), img)

    canvas.save(OUT_ICO, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                (64, 64), (128, 128), (256, 256)])
    canvas.resize((256, 256), Image.LANCZOS).save(OUT_PNG)
    print("ico →", OUT_ICO)


if __name__ == "__main__":
    main()
