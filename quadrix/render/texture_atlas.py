"""Атлас текстур QuadRix — минимальная версия.

# FALLBACK: полноценный атлас (hundreds of block textures) pending — Фаза 5.
Сейчас загружается одна текстура ``stone.png`` из ``.local`` и считается
атласом 1x1. UV-контракт (u, v, w, h) уже атласный, поэтому мешер и
шейдер менять не придётся: когда появится сетка тайлов, изменятся только
координаты, а не интерфейс.

Путь строго по AGENTS.md:
    .local/horizon-client/26.3/assets/minecraft/textures/block/stone.png
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

# Официальный путь ассетов версии 26.3 (см. AGENTS.md, .local layout).
STONE_TEXTURE_PATH = Path(
    ".local/horizon-client/26.3/assets/minecraft/textures/block/stone.png"
)
# Размер тайла в пикселях (ванильные текстуры блоков — 16x16).
TILE_PIXELS = 16


class TextureAtlas:
    """Атлас текстур блоков.

    Минимальная реализация: один тайл 16x16 (stone), атлас 1x1.
    ``load(block_state_id)`` возвращает прямоугольник (u, v, w, h) в
    нормализованных координатах [0, 1] — именно его ждёт ``mesh_chunk``.
    """

    def __init__(
        self,
        image: np.ndarray,
        *,
        tile_pixels: int = TILE_PIXELS,
        registry: Optional[object] = None,
        source: Optional[Path] = None,
    ) -> None:
        if image.ndim != 3 or image.shape[2] != 4:
            raise ValueError(
                f"[QuadRix] TextureAtlas: ожидается RGBA-изображение (H, W, 4), "
                f"получено {image.shape}"
            )
        self.image = np.ascontiguousarray(image, dtype=np.uint8)
        self.tile_pixels = int(tile_pixels)
        self.height, self.width = self.image.shape[:2]
        # атлас 1x1 (единственный тайл — stone)
        self.columns = max(1, self.width // self.tile_pixels)
        self.rows = max(1, self.height // self.tile_pixels)
        self.registry = registry
        self.source = source
        # кэш: block_state_id -> (u, v, w, h)
        self._cache: dict[int, tuple[float, float, float, float]] = {}

    # ------------------------------------------------------------------
    # загрузка
    # ------------------------------------------------------------------

    @classmethod
    def load_default(
        cls,
        path: Path | str = STONE_TEXTURE_PATH,
        *,
        registry: Optional[object] = None,
    ) -> "TextureAtlas":
        """Загрузить ``stone.png`` из ``.local`` как атлас 1x1.

        Регистр блоков опционален: он нужен только для логов о том, какой
        блок получил тайл. UV от него не зависят, пока тайл один.
        """
        from PIL import Image

        texture_path = Path(path)
        if not texture_path.exists():
            raise FileNotFoundError(
                f"[QuadRix] TextureAtlas: текстура не найдена: {texture_path}"
            )
        with Image.open(texture_path) as img:
            rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
        print(
            f"[QuadRix] texture atlas: {texture_path.name} "
            f"{rgba.shape[1]}x{rgba.shape[0]} tiles={1}x{1} (minimal)"
        )
        return cls(rgba, tile_pixels=TILE_PIXELS, registry=registry, source=texture_path)

    # ------------------------------------------------------------------
    # UV
    # ------------------------------------------------------------------

    def load(self, block_state_id: int) -> tuple[float, float, float, float]:
        """UV-прямоугольник блока в атласе: ``(u, v, w, h)``, всё в [0, 1].

        # FALLBACK: пока любой твёрдый блок получает единственный тайл
        # stone. Полноценная сетка тайлов — Фаза 5.
        """
        key = int(block_state_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        # атлас 1x1: весь прямоугольник
        tile_w = 1.0 / self.columns
        tile_h = 1.0 / self.rows
        rect = (0.0, 0.0, tile_w, tile_h)
        self._cache[key] = rect
        return rect

    def load_many(self, block_state_ids: np.ndarray) -> np.ndarray:
        """UV-прямоугольники для массива id: ``(m, 4)`` float32.

        Векторизовано: при атласе 1x1 возвращается broadcast-представление,
        без питоновского цикла по блокам (важно для мешинга).
        """
        ids = np.asarray(block_state_ids)
        m = ids.size
        if self.columns == 1 and self.rows == 1:
            out = np.empty((m, 4), dtype=np.float32)
            out[:, 0] = 0.0
            out[:, 1] = 0.0
            out[:, 2] = 1.0
            out[:, 3] = 1.0
            return out

        # Общий случай (будущий атлас): цикл только по уникальным id.
        out = np.empty((m, 4), dtype=np.float32)
        unique, inverse = np.unique(ids, return_inverse=True)
        rects = np.asarray([self.load(int(sid)) for sid in unique], dtype=np.float32)
        out[:] = rects[inverse.reshape(-1)]
        return out

    # ------------------------------------------------------------------
    # GPU-данные
    # ------------------------------------------------------------------

    @property
    def rgba_bytes(self) -> bytes:
        """Пиксели для ``ctx.texture(...).write``."""
        return self.image.tobytes()

    @property
    def size(self) -> tuple[int, int]:
        """(ширина, высота) атласа в пикселях."""
        return self.width, self.height
