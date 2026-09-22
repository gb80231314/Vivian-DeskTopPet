import struct
import zlib
from io import BytesIO

def create_rgba_png(width: int, height: int, color: tuple[int, int, int, int] = (200, 200, 220, 255)) -> bytes:
    r, g, b, a = color

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + chunk + crc

    signature = b"\x89PNG\r\n\x1a\n"

    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)

    raw_data = b""
    for y in range(height):
        raw_data += b"\x00"
        for x in range(width):
            raw_data += struct.pack("BBBB", r, g, b, a)

    compressed = zlib.compress(raw_data)
    idat = make_chunk(b"IDAT", compressed)

    iend = make_chunk(b"IEND", b"")

    return signature + ihdr + idat + iend

def create_frame_image(
    cell_width: int = 192,
    cell_height: int = 208,
    base_color: tuple = None,
    body_color: tuple = (120, 160, 220, 255),
    accent_color: tuple = (255, 180, 100, 255),
    frame_col: int = 0,
    anim_type: str = "idle",
) -> bytes:
    if base_color is None:
        base_color = (245, 245, 250, 0)

    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (cell_width, cell_height), base_color)
    draw = ImageDraw.Draw(img)

    head_cx = cell_width // 2
    head_cy = cell_height // 3
    head_r = min(cell_width, cell_height) // 5
    draw.ellipse(
        [head_cx - head_r, head_cy - head_r, head_cx + head_r, head_cy + head_r],
        fill=body_color,
        outline=(80, 120, 180, 255),
        width=2,
    )

    body_top = head_cy + head_r
    body_bottom = cell_height - 20
    draw.rounded_rectangle(
        [head_cx - head_r + 10, body_top, head_cx + head_r - 10, body_bottom],
        radius=15,
        fill=body_color,
        outline=(80, 120, 180, 255),
        width=2,
    )

    eye_offset = 0
    if anim_type == "running-right":
        eye_offset = 3
    elif anim_type == "running-left":
        eye_offset = -3
    elif anim_type == "jumping":
        eye_offset = -2

    draw.ellipse(
        [head_cx - 18 - eye_offset, head_cy - 10, head_cx - 6 - eye_offset, head_cy + 5],
        fill=(255, 255, 255, 255),
    )
    draw.ellipse(
        [head_cx + 6 - eye_offset, head_cy - 10, head_cx + 18 - eye_offset, head_cy + 5],
        fill=(255, 255, 255, 255),
    )

    draw.ellipse(
        [head_cx - 12 - eye_offset, head_cy - 5, head_cx - 8 - eye_offset, head_cy],
        fill=(40, 40, 40, 255),
    )
    draw.ellipse(
        [head_cx + 8 - eye_offset, head_cy - 5, head_cx + 12 - eye_offset, head_cy],
        fill=(40, 40, 40, 255),
    )

    mouth_y = head_cy + 10
    if anim_type == "failed":
        draw.arc([head_cx - 10, mouth_y - 5, head_cx + 10, mouth_y + 10], 0, 180, fill=(200, 80, 80, 255), width=2)
    else:
        draw.arc([head_cx - 8, mouth_y - 5, head_cx + 8, mouth_y + 8], 0, 180, fill=(200, 100, 100, 255), width=1)

    draw.ellipse([head_cx - 25, head_cy + 2, head_cx - 15, head_cy + 10], fill=(255, 150, 150, 100))
    draw.ellipse([head_cx + 15, head_cy + 2, head_cx + 25, head_cy + 10], fill=(255, 150, 150, 100))

    hat_color = accent_color
    draw.ellipse(
        [head_cx - head_r - 5, head_cy - head_r - 15, head_cx + head_r + 5, head_cy - head_r + 5],
        fill=hat_color,
    )

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
