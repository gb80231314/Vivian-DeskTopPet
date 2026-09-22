import logging
import random
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

CHIBI_STYLES = {
    "chibi_classic": {
        "name": "经典Q版",
        "head_ratio": 0.5,
        "eye_ratio": 1.8,
        "body_height": 0.5,
        "color_boost": 1.3,
        "outline_width": 2,
        "line_color": (60, 60, 60, 255),
        "background": (0, 0, 0, 0),
    },
    "chibi_cute": {
        "name": "萌系Q版",
        "head_ratio": 0.6,
        "eye_ratio": 2.2,
        "body_height": 0.4,
        "color_boost": 1.5,
        "outline_width": 3,
        "line_color": (40, 30, 30, 255),
        "background": (0, 0, 0, 0),
    },
    "chibi_minimal": {
        "name": "简约Q版",
        "head_ratio": 0.55,
        "eye_ratio": 1.6,
        "body_height": 0.45,
        "color_boost": 1.1,
        "outline_width": 1,
        "line_color": (80, 80, 80, 255),
        "background": (0, 0, 0, 0),
    },
    "chibi_pixel": {
        "name": "像素Q版",
        "head_ratio": 0.5,
        "eye_ratio": 1.5,
        "body_height": 0.5,
        "color_boost": 1.2,
        "outline_width": 1,
        "line_color": (50, 50, 50, 255),
        "background": (0, 0, 0, 0),
        "pixelate": 4,
    },
    "chibi_watercolor": {
        "name": "水彩Q版",
        "head_ratio": 0.55,
        "eye_ratio": 1.7,
        "body_height": 0.45,
        "color_boost": 1.0,
        "outline_width": 2,
        "line_color": (100, 80, 70, 200),
        "background": (0, 0, 0, 0),
        "soften": 3,
    },
}

class QPetConverter:

    def __init__(self, style: str = "chibi_classic", cell_size: Tuple[int, int] = (192, 208)):
        self.style = CHIBI_STYLES.get(style, CHIBI_STYLES["chibi_classic"])
        self.cell_width, self.cell_height = cell_size
        self._pil = None

    def _get_pil(self):
        if self._pil is None:
            try:
                from PIL import Image
                self._pil = Image
            except ImportError:
                raise ImportError("Pillow 未安装。请执行: pip install Pillow")
        return self._pil

    def load_image(self, path: str):
        Image = self._get_pil()
        img = Image.open(path).convert("RGBA")
        logger.info(f"加载参考图: {path} ({img.size[0]}x{img.size[1]})")
        return img

    def convert_to_chibi(self, image) -> bytes:
        Image = self._get_pil()
        s = self.style

        w, h = image.size

        person_img = self._crop_person(image)

        pw, ph = person_img.size
        new_h = int(self.cell_height * 0.85)
        head_size = int(new_h * s["head_ratio"])
        body_size = new_h - head_size

        head = person_img.crop((0, 0, pw, int(ph * 0.45))).resize(
            (int(self.cell_width * 0.75), head_size), Image.LANCZOS
        )

        body = person_img.crop(
            (0, int(ph * 0.45), pw, ph)
        ).resize((int(self.cell_width * 0.45), body_size), Image.LANCZOS)

        head = self._cartoon_enhance(head, s)
        body = self._cartoon_enhance(body, s)

        chibi = Image.new("RGBA", (self.cell_width, self.cell_height), s["background"])

        head_x = (self.cell_width - head.size[0]) // 2
        head_y = 5
        chibi.paste(head, (head_x, head_y), head)

        body_x = (self.cell_width - body.size[0]) // 2
        body_y = head_y + head.size[0] - 10
        chibi.paste(body, (body_x, body_y), body)

        chibi = self._add_chibi_accents(chibi)

        if "pixelate" in s:
            chibi = self._pixelate(chibi, s["pixelate"])
        if "soften" in s:
            chibi = self._soften(chibi, s["soften"])

        buf = BytesIO()
        chibi.save(buf, format="PNG")
        logger.info(f"Q版转换完成 ({s['name']})")
        return buf.getvalue()

    def _crop_person(self, image):
        Image = self._get_pil()
        w, h = image.size

        if image.mode != "RGBA":
            image = image.convert("RGBA")

        data = image.getdata()
        alpha_data = [p[3] for p in data]

        non_transparent = [(i % w, i // w) for i, a in enumerate(alpha_data) if a > 30]

        if not non_transparent:
            return image

        xs = [p[0] for p in non_transparent]
        ys = [p[1] for p in non_transparent]

        left = max(0, min(xs) - 5)
        top = max(0, min(ys) - 5)
        right = min(w, max(xs) + 5)
        bottom = min(h, max(ys) + 5)

        return image.crop((left, top, right, bottom))

    def _cartoon_enhance(self, image, style: dict):
        Image = self._get_pil()
        from PIL import ImageFilter, ImageEnhance

        img = image.copy()

        if style.get("color_boost", 1.0) != 1.0:
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(style["color_boost"])
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.1)

        img = img.filter(ImageFilter.SMOOTH_MORE)

        if style.get("outline_width", 0) > 0:
            edges = img.filter(ImageFilter.FIND_EDGES)
            edges = edges.convert("RGBA")

            img = Image.blend(img, edges, 0.08)

        return img

    def _add_chibi_accents(self, chibi_img):
        Image = self._get_pil()
        from PIL import ImageDraw

        img = chibi_img.copy()
        draw = ImageDraw.Draw(img)

        cx = self.cell_width // 2
        head_top = int(self.cell_height * self.style["head_ratio"] * 0.35)

        blush_color = (255, 150, 150, 120)
        blush_r = 12

        draw.ellipse(
            [cx - 40, head_top + 25, cx - 20, head_top + 45],
            fill=blush_color,
        )

        draw.ellipse(
            [cx + 20, head_top + 25, cx + 40, head_top + 45],
            fill=blush_color,
        )

        highlight_color = (255, 255, 255, 200)

        draw.ellipse(
            [cx - 25, head_top + 10, cx - 12, head_top + 20],
            fill=highlight_color,
        )

        draw.ellipse(
            [cx + 12, head_top + 10, cx + 25, head_top + 20],
            fill=highlight_color,
        )

        return img

    def _pixelate(self, image, pixel_size: int):
        Image = self._get_pil()
        w, h = image.size
        small = image.resize(
            (w // pixel_size, h // pixel_size), Image.NEAREST
        )
        return small.resize((w, h), Image.NEAREST)

    def _soften(self, image, radius: int):
        Image = self._get_pil()
        from PIL import ImageFilter
        return image.filter(ImageFilter.GaussianBlur(radius=radius))

    def generate_sprite_frames(
        self,
        ref_image,
        anim_states: list,
        num_frames: int = 8,
    ) -> dict:
        frames = {}

        base_chibi = self.convert_to_chibi(ref_image)
        Image = self._get_pil()
        base_img = Image.open(BytesIO(base_chibi))

        for state in anim_states:
            state_name = state.get("name", "idle")
            state_frames = []

            for i in range(num_frames):

                frame = base_img.copy()

                if "running" in state_name:

                    from PIL import ImageChops
                    offset = int(3 * (1 if i % 2 == 0 else -1))
                    frame = ImageChops.offset(frame, offset, 0)

                elif state_name == "jumping":

                    from PIL import ImageChops
                    offset_y = int(-8 if i < num_frames // 2 else 8)
                    frame = ImageChops.offset(frame, 0, offset_y)

                elif state_name == "waving":

                    from PIL import ImageChops
                    offset = int(2 * (i % 3 - 1))
                    frame = ImageChops.offset(frame, offset, 0)

                buf = BytesIO()
                frame.save(buf, format="PNG")
                state_frames.append(buf.getvalue())

            frames[state_name] = state_frames

        return frames

class AIImageGenerator:

    def __init__(self, provider: str = "local", api_key: Optional[str] = None):
        self.provider = provider
        self.api_key = api_key

    def is_available(self) -> bool:
        if self.provider == "local":
            return False
        if self.provider == "openai" and self.api_key:
            return True
        return False

    def generate_chibi(self, ref_image_path: str,
                       prompt_extra: str = "",
                       style: str = "chibi cartoon") -> Optional[str]:
        if not self.is_available():
            logger.warning(
                "AI 图像生成不可用。请设置 provider 和 api_key，"
                "或将参考图放到 frames/ 目录下手动管理。"
            )
            return None

        logger.info(f"[AI] 将调用 {self.provider} 生成 Q 版形象...")
        logger.info(f"[AI] 提示词: Q-version cute cartoon character, {style}, {prompt_extra}")

        return None

def generate_q_pet_from_image(
    image_path: str,
    style: str = "chibi_classic",
    output_dir: str = "output",
    pet_name: str = "MyPet",
    use_ai: bool = False,
    api_key: Optional[str] = None,
) -> Path:
    from .config import ANIMATION_STATES
    from .sprite_builder import SpriteSheetBuilder
    from .pet_config import save_pet_config

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    converter = QPetConverter(style=style)
    ref_img = converter.load_image(image_path)

    if use_ai:
        ai = AIImageGenerator(provider="openai" if api_key else "local", api_key=api_key)
        ai_result = ai.generate_chibi(image_path, f"Name: {pet_name}")
        if ai_result:
            ref_img = converter.load_image(ai_result)

    logger.info(f"生成 '{pet_name}' Q版动画帧 (风格: {style})...")
    frames = converter.generate_sprite_frames(ref_img, ANIMATION_STATES, num_frames=8)

    builder = SpriteSheetBuilder()

    for state in ANIMATION_STATES:
        state_name = state["name"]
        row = state["row"]
        if state_name in frames:
            for col, frame_data in enumerate(frames[state_name]):
                builder.set_cell(row, col, frame_data)

    from .frame_generator import create_frame_image
    for row in range(9, 11):
        for col in range(8):
            if (row, col) not in builder.get_empty_cells():
                continue
            frame = create_frame_image(
                anim_type="idle", frame_col=col,
            )
            builder.set_cell(row, col, frame)

    spritesheet_path = str(output_path / "spritesheet.webp")
    builder.build(spritesheet_path)

    config = save_pet_config(
        path=str(output_path / "pet.json"),
        name=pet_name,
        description=f"{pet_name} - Q版桌面宠物 ({CHIBI_STYLES[style]['name']}风格)",
    )

    logger.info(f"✅ {pet_name} Q版宠物生成完成 → {output_path}")
    return output_path
