import json
from typing import Optional

from .config import (
    ANIMATION_STATES,
    CELL_WIDTH,
    CELL_HEIGHT,
    COLS,
    ROWS,
    ATLAS_WIDTH,
    ATLAS_HEIGHT,
    SPRITE_VERSION_NUMBER,
    DEFAULT_FPS,
    DEFAULT_FRAME_COUNT,
    GAZE_DIRECTIONS,
)

def build_animation_entry(
    name: str,
    row: int,
    label: str,
    repeat: bool = True,
    fps: int = DEFAULT_FPS,
    frame_count: int = DEFAULT_FRAME_COUNT,
) -> dict:
    return {
        "name": name,
        "label": label,
        "row": row,
        "frameCount": frame_count,
        "fps": fps,
        "repeat": repeat,
        "loop": repeat,
    }

def build_gaze_entry(
    name: str,
    row: int,
    col: int,
    angle: float,
    label: str,
) -> dict:
    return {
        "name": name,
        "label": label,
        "angle": angle,
        "row": row,
        "col": col,
        "type": "gaze",
    }

def build_pet_config(
    name: str = "DesktopBuddy",
    description: str = "Q版卡通桌面宠物",
    author: str = "",
    version: str = "1.0.2",
) -> dict:
    animations = []
    for state in ANIMATION_STATES:
        animations.append(build_animation_entry(**state))

    gazes = []
    for gaze in GAZE_DIRECTIONS:
        gazes.append(build_gaze_entry(**gaze))

    return {
        "name": name,
        "description": description,
        "author": author,
        "version": version,
        "spriteVersionNumber": SPRITE_VERSION_NUMBER,
        "sprite": {
            "image": "spritesheet.webp",
            "cell": {
                "width": CELL_WIDTH,
                "height": CELL_HEIGHT,
            },
            "cols": COLS,
            "rows": ROWS,
            "atlasWidth": ATLAS_WIDTH,
            "atlasHeight": ATLAS_HEIGHT,
        },
        "animations": animations,
        "gazes": gazes,
    }

def save_pet_config(
    path: str = "pet.json",
    name: str = "DesktopBuddy",
    description: str = "Q版卡通桌面宠物",
    author: str = "",
    version: str = "1.0.2",
) -> dict:
    config = build_pet_config(name=name, description=description, author=author, version=version)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    return config

def validate_pet_config(config: dict) -> list[str]:
    errors = []

    if config.get("spriteVersionNumber") != 2:
        errors.append("spriteVersionNumber 必须为 2")

    sprite = config.get("sprite", {})
    if sprite.get("image") != "spritesheet.webp":
        errors.append("sprite.image 必须为 'spritesheet.webp'")

    cell = sprite.get("cell", {})
    if cell.get("width") != CELL_WIDTH:
        errors.append(f"sprite.cell.width 必须为 {CELL_WIDTH}")
    if cell.get("height") != CELL_HEIGHT:
        errors.append(f"sprite.cell.height 必须为 {CELL_HEIGHT}")

    if sprite.get("cols") != COLS:
        errors.append(f"sprite.cols 必须为 {COLS}")
    if sprite.get("rows") != ROWS:
        errors.append(f"sprite.rows 必须为 {ROWS}")

    if sprite.get("atlasWidth") != ATLAS_WIDTH:
        errors.append(f"sprite.atlasWidth 必须为 {ATLAS_WIDTH}")
    if sprite.get("atlasHeight") != ATLAS_HEIGHT:
        errors.append(f"sprite.atlasHeight 必须为 {ATLAS_HEIGHT}")

    animations = config.get("animations", [])
    if len(animations) != 9:
        errors.append(f"animations 必须包含 9 个动画状态，当前 {len(animations)} 个")

    gazes = config.get("gazes", [])
    if len(gazes) != 16:
        errors.append(f"gazes 必须包含 16 个方向注视，当前 {len(gazes)} 个")

    return errors
