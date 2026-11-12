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

import functools
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

# Официальный путь ассетов версии 26.3 (см. AGENTS.md, .local layout).
STONE_TEXTURE_PATH = Path(
    ".local/horizon-client/26.3/assets/minecraft/textures/block/stone.png"
)
# Корень ресурсов клиента (blockstates/models/textures) — как у Rust Assets.
BLOCK_PACK_ROOT = Path(".local/horizon-client/26.3/assets/minecraft")
# Реестр блоков: state id -> имя блока (block_sprites.rs читает его же).
BLOCK_REGISTRY_PATH = Path(".local/horizon-client-motion/block-registry.nbt")
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


# ===========================================================================
# Блочный атлас (порт ``horizon-client-render/src/block_sprites.rs``)
# ===========================================================================
#
# Rust строит для каждого состояния block model (blockstates + models) и
# берёт с каждой грани её спрайт; мешер печёт UV этой грани. Здесь то же
# самое, но проще: модели резолвятся один раз по имени блока, шесть текстур
# (south/north/east/west/up/down) упаковываются в один RGBA-атлас, а
# ``face_rects`` отдаёт мешеру UV-прямоугольник нужной грани.
#
# Порядок граней ровно как в ``mesher.FACE_DEFS``:
#     0 +Z south, 1 -Z north, 2 +X east, 3 -X west, 4 +Y up, 5 -Y down.
FACE_KEYS: tuple[str, ...] = ("south", "north", "east", "west", "up", "down")

#: Жидкости рисуются одним спрайтом на все шесть граней (block_sprites.rs:158).
FLUID_TEXTURES: dict[str, str] = {
    "minecraft:water": "minecraft:block/water_still",
    "minecraft:bubble_column": "minecraft:block/water_still",
    "minecraft:lava": "minecraft:block/lava_still",
}

#: FALLBACK-тинт серых текстур (grass/leaves/water) — Rust умножает их на
#: ``TintSource``; здесь фиксированные ванильные цвета биомов.
TINTS: dict[str, tuple[int, int, int]] = {
    "minecraft:block/grass_block_top": (0x91, 0xBD, 0x59),
    "minecraft:block/water_still": (0x3F, 0x76, 0xE4),
    "minecraft:block/water_flow": (0x3F, 0x76, 0xE4),
    "minecraft:block/oak_leaves": (0x48, 0xB5, 0x18),
    "minecraft:block/jungle_leaves": (0x48, 0xB5, 0x18),
    "minecraft:block/dark_oak_leaves": (0x48, 0xB5, 0x18),
    "minecraft:block/mangrove_leaves": (0x48, 0xB5, 0x18),
    "minecraft:block/birch_leaves": (0x80, 0xA7, 0x55),
    "minecraft:block/spruce_leaves": (0x61, 0x99, 0x61),
    "minecraft:block/acacia_leaves": (0x6A, 0x70, 0x39),
    "minecraft:block/vine": (0x48, 0xB5, 0x18),
    "minecraft:block/lily_pad": (0x71, 0xC7, 0x4E),
}

#: Сколько тайлов в ряд при упаковке атласа.
_ATLAS_COLUMNS = 32


def _read_json(path: Path) -> dict:
    """Прочитать JSON модели/blockstate; пустой dict при любой ошибке."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _strip_ns(name: str) -> str:
    """``minecraft:block/stone`` -> ``block/stone`` (путь внутри models/)."""
    return name.split(":", 1)[1] if ":" in name else name


def _resolve_var(textures: dict, value: object, depth: int = 0) -> Optional[str]:
    """Развернуть ``#side`` в имя текстуры (block_sprites.rs: affine/uv)."""
    while isinstance(value, str) and value.startswith("#") and depth < 32:
        value = textures.get(value[1:])
        depth += 1
    if not isinstance(value, str) or not value or value.startswith("#"):
        return None
    return value if ":" in value else "minecraft:" + value


class _ModelResolver:
    """Резолвер block model: сливает цепочку parents, кэширует результат."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = Path(models_dir)
        self._cache: dict[str, tuple[dict, Optional[list]]] = {}

    def resolve(self, ref: str) -> tuple[dict, Optional[list]]:
        """Вернуть ``(textures, elements)`` модели ``ref`` с учётом parents."""
        key = _strip_ns(ref)
        if key in self._cache:
            return self._cache[key]
        # защита от циклов: до полного разбора считаем модель пустой
        self._cache[key] = ({}, None)
        data = _read_json(self.models_dir / (key + ".json"))
        textures: dict = {}
        elements: Optional[list] = None
        parent = data.get("parent")
        if parent:
            ptex, pel = self.resolve(parent)
            textures.update(ptex)
            elements = pel
        own_tex = data.get("textures")
        if isinstance(own_tex, dict):
            textures.update(own_tex)
        if "elements" in data:
            own_el = data.get("elements")
            elements = own_el if isinstance(own_el, list) else elements
        self._cache[key] = (textures, elements)
        return textures, elements

    def face_textures(self, model_ref: Optional[str], block_name: str) -> dict[str, str]:
        """Имя текстуры для каждой из шести граней блока."""
        if block_name in FLUID_TEXTURES:
            return {key: FLUID_TEXTURES[block_name] for key in FACE_KEYS}
        textures: dict = {}
        elements: Optional[list] = None
        if model_ref:
            textures, elements = self.resolve(model_ref)
        faces: dict[str, str] = {}
        if elements:
            for element in elements:
                if not isinstance(element, dict):
                    continue
                element_faces = element.get("faces")
                if not isinstance(element_faces, dict):
                    continue
                for fkey, fdata in element_faces.items():
                    if fkey in faces or not isinstance(fdata, dict):
                        continue
                    tex = _resolve_var(textures, fdata.get("texture"))
                    if tex:
                        faces[fkey] = tex
        generic = self._generic_texture(textures)
        for fkey in FACE_KEYS:
            faces.setdefault(fkey, generic)
        return faces

    @staticmethod
    def _generic_texture(textures: dict) -> Optional[str]:
        """Запасная текстура модели: all/side/particle/... затем любая."""
        for key in ("all", "side", "particle", "texture", "top", "front", "end"):
            if key in textures:
                tex = _resolve_var(textures, textures[key])
                if tex:
                    return tex
        for value in textures.values():
            tex = _resolve_var(textures, value)
            if tex:
                return tex
        return None


def _variant_matches(key: str, props: dict) -> bool:
    """Подходит ли ключ варианта blockstate к свойствам состояния по умолчанию."""
    if key == "":
        return True
    for pair in key.split(","):
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        if props.get(name.strip()) != value.strip():
            return False
    return True


def _model_of_apply(value: object) -> Optional[str]:
    """Достать имя модели из variant/apply (dict, list или голая строка)."""
    if isinstance(value, dict):
        return value.get("model")
    if isinstance(value, list):
        for item in value:
            model = _model_of_apply(item)
            if model:
                return model
    if isinstance(value, str):
        return value
    return None


def _pick_model(blockstate: dict, props: dict) -> Optional[str]:
    """Модель состояния по умолчанию (blockstates: variants или multipart)."""
    variants = blockstate.get("variants")
    if isinstance(variants, dict) and variants:
        for key, value in variants.items():
            if _variant_matches(key, props):
                model = _model_of_apply(value)
                if model:
                    return model
        for value in variants.values():
            model = _model_of_apply(value)
            if model:
                return model
        return None
    multipart = blockstate.get("multipart")
    if isinstance(multipart, list):
        for part in multipart:
            if isinstance(part, dict):
                model = _model_of_apply(part.get("apply"))
                if model:
                    return model
    return None


def _tile_image(image: np.ndarray, tint: Optional[tuple[int, int, int]]) -> np.ndarray:
    """Обрезать текстуру до первого кадра 16x16 и (опционально) затонировать."""
    tile = np.zeros((TILE_PIXELS, TILE_PIXELS, 4), dtype=np.uint8)
    h = min(TILE_PIXELS, image.shape[0])
    w = min(TILE_PIXELS, image.shape[1])
    tile[:h, :w] = image[:h, :w]
    if tint is not None:
        rgb = tile[:, :, :3].astype(np.uint16)
        rgb = (rgb * np.asarray(tint, dtype=np.uint16)[None, None, :]) // 255
        tile[:, :, :3] = rgb.astype(np.uint8)
    return tile


def _fallback_tile() -> np.ndarray:
    """FALLBACK-тайл для блоков без модели: чёрно-пурпурная шахматка."""
    tile = np.zeros((TILE_PIXELS, TILE_PIXELS, 4), dtype=np.uint8)
    for y in range(TILE_PIXELS):
        for x in range(TILE_PIXELS):
            if ((x // 4) + (y // 4)) % 2 == 0:
                tile[y, x] = (255, 0, 255, 255)
            else:
                tile[y, x] = (20, 20, 20, 255)
    return tile


class BlockAtlas:
    """Атлас текстур блоков из моделей ``.local`` (порт ``block_sprites``).

    Хранит один RGBA-атлас (``image``), таблицу UV на грань для каждого
    состояния блока (``_state_faces``) и умеет отдавать мешеру прямоугольник
    конкретной грани через :meth:`face_rects`.
    """

    def __init__(
        self,
        image: np.ndarray,
        *,
        sprite_rects: dict[str, tuple[int, int, int, int]],
        state_faces: np.ndarray,
        tile_pixels: int = TILE_PIXELS,
        registry: Optional[object] = None,
    ) -> None:
        self.image = np.ascontiguousarray(image, dtype=np.uint8)
        self.tile_pixels = int(tile_pixels)
        self.height, self.width = self.image.shape[:2]
        self._sprite_rects = sprite_rects
        self._state_faces = state_faces
        self.registry = registry

    # -- загрузка --------------------------------------------------------

    @classmethod
    def load_default(
        cls,
        root: Path | str = BLOCK_PACK_ROOT,
        *,
        registry_path: Path | str = BLOCK_REGISTRY_PATH,
        registry: Optional[object] = None,
    ) -> "BlockAtlas":
        """Собрать атлас из ``blockstates``/``models``/``textures`` в ``.local``."""
        root = Path(root)
        models_dir = root / "models"
        textures_dir = root / "textures"

        if registry is None:
            # Общий с блок-плейсментом кэш реестра: не читать NBT дважды.
            if Path(registry_path) == BLOCK_REGISTRY_PATH:
                from quadrix.world.block_placement import default_registry

                registry = default_registry()
            else:
                from quadrix.world.registry import BlockRegistry

                registry = BlockRegistry.load(registry_path)

        resolver = _ModelResolver(models_dir)
        name_faces: dict[str, dict[str, str]] = {}
        for bs_path in sorted((root / "blockstates").glob("*.json")):
            name = "minecraft:" + bs_path.stem
            props: dict = {}
            default = registry.default_state(name)
            if default is not None:
                state = registry.state(default)
                if state is not None:
                    props = dict(state.properties.items())
            model = _pick_model(_read_json(bs_path), props)
            if not model:
                model = "minecraft:block/" + bs_path.stem
            name_faces[name] = resolver.face_textures(model, name)

        # какие текстуры реально нужны
        needed: set[str] = set()
        for faces in name_faces.values():
            needed.update(tex for tex in faces.values() if tex)

        from quadrix.render.ui import load_png_rgba

        # Параллельное чтение PNG: декодирование освобождает GIL, 905 файлов
        # читаются за ~0.4 с вместо ~2.5 с.
        jobs: list[tuple[str, Path]] = []
        for tex in sorted(needed):
            path = textures_dir / (_strip_ns(tex) + ".png")
            if path.exists():
                jobs.append((tex, path))

        from concurrent.futures import ThreadPoolExecutor

        def _load(job: tuple[str, Path]) -> Optional[tuple[str, np.ndarray]]:
            tex, path = job
            try:
                return tex, load_png_rgba(path)
            except Exception as exc:  # noqa: BLE001 - битый PNG не критичен
                print(f"[QuadRix] block atlas: не прочитан {path.name}: {exc}")
                return None

        tiles: list[tuple[str, np.ndarray]] = []
        if jobs:
            workers = min(8, len(jobs))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for result in pool.map(_load, jobs):
                    if result is None:
                        continue
                    tex, image = result
                    tiles.append((tex, _tile_image(image, TINTS.get(tex))))

        image, sprite_px = cls._pack(tiles)
        fallback_px = sprite_px["__fallback__"]

        atlas_w, atlas_h = image.shape[1], image.shape[0]

        def norm(px: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
            x, y, w, h = px
            return (
                (x + 0.5) / atlas_w,
                (y + 0.5) / atlas_h,
                (w - 1.0) / atlas_w,
                (h - 1.0) / atlas_h,
            )

        sprite_norm: dict[str, tuple[float, float, float, float]] = {
            tex: norm(px) for tex, px in sprite_px.items()
        }
        fallback_norm = norm(fallback_px)

        # состояние -> (6, 4) UV по граням
        states = list(getattr(registry, "states", []) or [])
        table = np.empty((len(states), len(FACE_KEYS), 4), dtype=np.float32)
        table[:] = np.asarray(fallback_norm, dtype=np.float32)
        for i, state in enumerate(states):
            faces = name_faces.get(getattr(state, "name", ""))
            if not faces:
                continue
            for fi, fkey in enumerate(FACE_KEYS):
                tex = faces.get(fkey)
                table[i, fi] = sprite_norm.get(tex, fallback_norm)

        print(
            f"[QuadRix] block atlas: {atlas_w}x{atlas_h} "
            f"тайлов={len(sprite_px)} блоков={len(states)}"
        )
        return cls(
            image,
            sprite_rects=sprite_px,
            state_faces=table,
            registry=registry,
        )

    @staticmethod
    def _pack(
        tiles: list[tuple[str, np.ndarray]],
    ) -> tuple[np.ndarray, dict[str, tuple[int, int, int, int]]]:
        """Разложить тайлы сеткой; вернуть атлас и ``tex -> (x, y, w, h)``.

        Служебный FALLBACK-тайл идёт первым (координаты (0, 0)), поэтому
        неизвестные/пропущенные текстуры всегда имеют валидный UV.
        """
        entries = [("__fallback__", _fallback_tile())] + list(tiles)
        cols = _ATLAS_COLUMNS
        rows = max(1, math.ceil(len(entries) / cols))
        image = np.zeros((rows * TILE_PIXELS, cols * TILE_PIXELS, 4), dtype=np.uint8)
        rects: dict[str, tuple[int, int, int, int]] = {}
        for i, (tex, tile) in enumerate(entries):
            x = (i % cols) * TILE_PIXELS
            y = (i // cols) * TILE_PIXELS
            image[y : y + TILE_PIXELS, x : x + TILE_PIXELS] = tile
            rects[tex] = (x, y, TILE_PIXELS, TILE_PIXELS)
        return image, rects

    # -- интерфейс мешера ------------------------------------------------

    def has_texture(self, name: str) -> bool:
        """Зарегистрирована ли текстура с этим именем (``minecraft:block/...``)."""
        return name in self._sprite_rects or (
            ":" not in name and ("minecraft:" + name) in self._sprite_rects
        )

    @property
    def texture_names(self) -> tuple[str, ...]:
        """Имена всех загруженных текстур (для тестов/логов)."""
        return tuple(self._sprite_rects)

    def face_rects(self, block_state_ids: np.ndarray) -> np.ndarray:
        """UV всех граней: ``(m, 6, 4)`` — ``(u0, v0, du, dv)`` на грань.

        Грани в порядке ``mesher.FACE_DEFS`` (south, north, east, west, up,
        down). Неизвестный id даёт FALLBACK-тайл.
        """
        ids = np.asarray(block_state_ids).reshape(-1).astype(np.int64)
        m = ids.size
        out = np.empty((m, len(FACE_KEYS), 4), dtype=np.float32)
        count = self._state_faces.shape[0]
        out[:] = self._state_faces[0] if count else 0.0
        valid = (ids >= 0) & (ids < count)
        if valid.any():
            out[valid] = self._state_faces[ids[valid]]
        return out

    def load_many(self, block_state_ids: np.ndarray) -> np.ndarray:
        """Совместимость со старым интерфейсом: UV верхней грани, ``(m, 4)``."""
        return self.face_rects(block_state_ids)[:, 4, :]

    def load(self, block_state_id: int) -> tuple[float, float, float, float]:
        """UV верхней грани одного состояния (``(u0, v0, du, dv)``)."""
        rect = self.face_rects(np.asarray([block_state_id]))[0, 4]
        return (float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3]))

    # -- GPU -------------------------------------------------------------

    @property
    def rgba_bytes(self) -> bytes:
        """Пиксели атласа для ``ctx.texture(...).write``."""
        return self.image.tobytes()

    @property
    def size(self) -> tuple[int, int]:
        """(ширина, высота) атласа в пикселях."""
        return self.width, self.height


@functools.lru_cache(maxsize=4)
def _load_block_atlas_cached(root: str, registry_path: str) -> Optional[BlockAtlas]:
    """Кэшированная сборка блочного атласа; ``None`` при любой ошибке."""
    try:
        return BlockAtlas.load_default(root, registry_path=registry_path)
    except Exception as exc:  # noqa: BLE001 - терраин рисуем цветом при сбое
        print(f"[QuadRix] block atlas не загружен: {exc}")
        return None


def load_block_atlas(
    root: Path | str = BLOCK_PACK_ROOT,
    registry_path: Path | str = BLOCK_REGISTRY_PATH,
) -> Optional[BlockAtlas]:
    """Загрузить блочный атлас из ``.local`` (кэш), ``None`` при ошибке."""
    return _load_block_atlas_cached(str(root), str(registry_path))
