import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from .config import (
    CELL_WIDTH,
    CELL_HEIGHT,
    COLS,
    ROWS,
    ATLAS_WIDTH,
    ATLAS_HEIGHT,
)

logger = logging.getLogger(__name__)

class SpriteSheetBuilder:

    def __init__(self):
        self._cells: dict[tuple[int, int], bytes] = {}
        self._pil = None

    def _get_pil(self):
        if self._pil is None:
            try:
                from PIL import Image
                self._pil = Image
            except ImportError:
                raise ImportError(
                    "Pillow 未安装。请执行: pip install Pillow"
                )
        return self._pil

    def set_cell(self, row: int, col: int, image_data: bytes) -> None:
        if not (0 <= row < ROWS):
            raise ValueError(f"行索引 out of range: {row} (有效范围: 0-{ROWS-1})")
        if not (0 <= col < COLS):
            raise ValueError(f"列索引 out of range: {col} (有效范围: 0-{COLS-1})")
        self._cells[(row, col)] = image_data

    def set_cells_from_dir(
        self, frames_dir: str, row: int, pattern: str = "frame-*.png"
    ) -> int:
        dir_path = Path(frames_dir)
        if not dir_path.exists():
            raise FileNotFoundError(f"目录不存在: {frames_dir}")

        frames = sorted(dir_path.glob(pattern))
        if not frames:
            raise FileNotFoundError(f"在 {frames_dir} 中未找到匹配 {pattern} 的文件")

        count = 0
        max_frames = min(len(frames), COLS)
        for col, frame_path in enumerate(frames[:max_frames]):
            with open(frame_path, "rb") as f:
                self.set_cell(row, col, f.read())
            count += 1
            logger.info(f"  加载帧: {frame_path} → 行 {row}, 列 {col}")

        return count

    def build(self, output_path: str = "spritesheet.webp", quality: int = 85) -> str:
        Image = self._get_pil()

        atlas = Image.new("RGBA", (ATLAS_WIDTH, ATLAS_HEIGHT), (0, 0, 0, 0))
        filled_cells = 0
        empty_cells = []

        for row in range(ROWS):
            for col in range(COLS):
                x = col * CELL_WIDTH
                y = row * CELL_HEIGHT
                key = (row, col)

                if key in self._cells:
                    try:
                        cell_img = Image.open(BytesIO(self._cells[key]))

                        if cell_img.mode != "RGBA":
                            cell_img = cell_img.convert("RGBA")

                        if cell_img.size != (CELL_WIDTH, CELL_HEIGHT):
                            cell_img = cell_img.resize(
                                (CELL_WIDTH, CELL_HEIGHT), Image.LANCZOS
                            )
                        atlas.paste(cell_img, (x, y), cell_img)
                        filled_cells += 1
                    except Exception as e:
                        logger.warning(f"无法处理单元格 ({row},{col}): {e}")
                        empty_cells.append((row, col))
                else:
                    empty_cells.append((row, col))

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        atlas.save(str(output), "webp", quality=quality, lossless=False)

        logger.info(f"精灵图已保存: {output_path} ({ATLAS_WIDTH}x{ATLAS_HEIGHT})")
        logger.info(f"已填充: {filled_cells}/{ROWS*COLS} 个单元格")
        if empty_cells:
            logger.warning(f"空单元格 ({len(empty_cells)}): {empty_cells[:10]}...")

        return str(output)

    def get_empty_cells(self) -> list[tuple[int, int]]:
        empty = []
        for row in range(ROWS):
            for col in range(COLS):
                if (row, col) not in self._cells:
                    empty.append((row, col))
        return empty

    def clear(self) -> None:
        self._cells.clear()
