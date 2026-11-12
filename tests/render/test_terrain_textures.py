#!/usr/bin/env python3
"""[QuadRix] Тесты текстур terrain (блочный атлас) и hotbar без фантомов.

Покрывают два бага Gameplay PART 5:

    * «всё чёрное» — terrain не имел per-face UV и текстура не привязывалась
      (uniform ``light_dir`` не задавался → ``normalize(0)`` = NaN);
    * «фантомные предметы» — hotbar рисовал FALLBACK-иконки в пустых слотах,
      потому что мультиплеерный GameScreen предзаполнял инвентарь демо-блоком.

Атлас — из ``.local/horizon-client/26.3/assets/minecraft/{blockstates,models,
textures}`` (порт ``horizon-client-render/src/block_sprites.rs``), мешер
берёт UV грани оттуда.
"""

from __future__ import annotations

import numpy as np

from quadrix.items.items import ItemStack
from quadrix.render.app import GameScreen
from quadrix.render.hotbar import Hotbar, item_color
from quadrix.render.mesher import mesh_chunk
from quadrix.render.texture_atlas import load_block_atlas
from quadrix.world.block_placement import default_registry
from quadrix.world.player_inventory import HOTBAR_SIZE, PlayerInventory

# ---------------------------------------------------------------------------
# блочный атлас
# ---------------------------------------------------------------------------

def test_block_atlas_loaded() -> None:
    """Атлас собран из ``.local/textures/block/*.png``; базовые блоки на месте."""
    atlas = load_block_atlas()
    assert atlas is not None, "block atlas не загружен"
    assert atlas.size[0] > 0 and atlas.size[1] > 0
    # базовые текстуры мира (правило 10 AGENTS.md)
    assert atlas.has_texture("minecraft:block/stone")
    assert atlas.has_texture("minecraft:block/dirt")
    assert atlas.has_texture("minecraft:block/grass_block_top")
    assert atlas.has_texture("minecraft:block/oak_log")
    # в атласе реально есть непрозрачные пиксели (не пустая картинка)
    assert int(atlas.image[:, :, 3].max()) == 255
    assert int(atlas.image[:, :, :3].sum()) > 0


def test_mesher_uv_from_atlas() -> None:
    """UV вершин — sub-прямоугольник атласа, в [0, 1] и не (0, 0)."""
    atlas = load_block_atlas()
    assert atlas is not None
    registry = default_registry()

    def _mesh(block_name: str) -> np.ndarray:
        blocks = np.zeros((16, 16, 16), dtype=np.uint16)
        blocks[8, 8, 8] = registry.default_state(block_name).id
        vertices, _ = mesh_chunk(blocks, atlas)
        return vertices[:, 6:8]

    stone_uv = _mesh("minecraft:stone")
    assert stone_uv.min() >= 0.0
    assert stone_uv.max() <= 1.0
    # тайл занимает часть атласа, а не весь UV-квадрат
    assert (stone_uv[:, 0].max() - stone_uv[:, 0].min()) < 0.5
    assert (stone_uv[:, 1].max() - stone_uv[:, 1].min()) < 0.5
    # не вырожденный (не 0, 0) — текстура реально где-то в атласе
    assert not (np.allclose(stone_uv, 0.0))

    # разные блоки → разные тайлы атласа
    dirt_uv = _mesh("minecraft:dirt")
    assert not np.allclose(stone_uv[0], dirt_uv[0])


def test_grass_uses_three_different_face_tiles() -> None:
    """У травы top/side/bottom — разные текстуры (per-face UV мешера)."""
    atlas = load_block_atlas()
    assert atlas is not None
    registry = default_registry()
    state = registry.default_state("minecraft:grass_block").id
    rects = atlas.face_rects(np.asarray([state]))[0]
    unique = {tuple(np.round(row, 5)) for row in rects}
    assert len(unique) == 3


# ---------------------------------------------------------------------------
# привязка текстуры terrain
# ---------------------------------------------------------------------------

class _FakeUniform:
    def __init__(self) -> None:
        self.data: bytes | None = None

    def write(self, data: bytes) -> None:
        self.data = data


class _FakeProgram:
    """Программа с uniform-ами ``moderngl``-стиля."""

    def __init__(self) -> None:
        self.assigned: dict[str, object] = {}

    def __contains__(self, name: str) -> bool:
        return name in ("texture0", "mvp", "light_dir", "ambient")

    def __setitem__(self, name: str, value: object) -> None:
        self.assigned[name] = value

    def __getitem__(self, name: str) -> _FakeUniform:
        return _FakeUniform()


class _FakeTexture:
    def __init__(self) -> None:
        self.used: list[int] = []

    def use(self, location: int = 0) -> None:
        self.used.append(int(location))


class _FakeBuffer:
    def __init__(self, data: bytes) -> None:
        self.size = len(data)

    def release(self) -> None:
        pass


class _FakeVAO:
    def __init__(self) -> None:
        self.render_calls: list[tuple] = []

    def render(self, mode: object, vertices: int | None = None) -> None:
        self.render_calls.append((mode, vertices))

    def release(self) -> None:
        pass


class _FakeContext:
    def __init__(self) -> None:
        self.vaos: list[_FakeVAO] = []

    def enable(self, *_a) -> None:
        pass

    def disable(self, *_a) -> None:
        pass

    def buffer(self, data: bytes) -> _FakeBuffer:
        return _FakeBuffer(data)

    def vertex_array(self, program: object, attributes: object) -> _FakeVAO:
        vao = _FakeVAO()
        self.vaos.append(vao)
        return vao


def test_terrain_texture_bound() -> None:
    """``draw`` привязывает текстуру в unit 0 и ставит ``program["texture0"]=0``."""
    from quadrix.render.backend_moderngl import ModernglBackend

    backend = ModernglBackend()
    backend.ctx = _FakeContext()
    program = _FakeProgram()
    texture = _FakeTexture()

    vertices = np.zeros((36, 8), dtype=np.float32)
    backend.draw(
        vertices,
        program,
        texture,
        count=36,
        mvp=np.identity(4, dtype=np.float32),
    )

    assert texture.used and texture.used[0] == 0
    assert program.assigned.get("texture0") == 0
    # реально был draw call
    assert backend.ctx.vaos and backend.ctx.vaos[0].render_calls


# ---------------------------------------------------------------------------
# hotbar: пустые слоты без иконок
# ---------------------------------------------------------------------------

class _FakeBatch:
    def __init__(self) -> None:
        self.quads: list = []
        self.atlas = None
        self.width = 320.0
        self.height = 240.0

    def add_quad(self, quad: object) -> None:
        self.quads.append(quad)

    def add_quads(self, quads: list) -> None:
        self.quads.extend(quads)


def test_hotbar_empty_slots_no_icon() -> None:
    """Пустой инвентарь → только фон и подсветка, иконок нет."""
    inventory = PlayerInventory()
    assert inventory.is_empty()
    hotbar = Hotbar(inventory)
    batch = _FakeBatch()

    hotbar.render(batch, font=None, width=320.0, height=240.0)

    # фон (1) + подсветка выбранного слота (1); ни одной иконки предмета.
    assert len(batch.quads) == 2


def test_hotbar_item_icon() -> None:
    """Слот с предметом → иконка (FALLBACK-квадрат), пустые — без иконки."""
    inventory = PlayerInventory()
    inventory.items[0] = ItemStack("minecraft:stone", 64)
    hotbar = Hotbar(inventory)
    batch = _FakeBatch()

    hotbar.render(batch, font=None, width=320.0, height=240.0)

    # фон (1) + подсветка (1) + иконка (1) + рамка иконки (1).
    assert len(batch.quads) == 4
    colors = {q.color for q in batch.quads}
    assert item_color("minecraft:stone") in colors


def test_multiplayer_hotbar_has_no_phantom_items() -> None:
    """Мультиплеерный GameScreen не предзаполняет инвентарь демо-блоками."""
    from tests.render.test_multiplayer import FakeClient

    game = GameScreen(client=FakeClient(), width=64.0, height=48.0)

    assert game.inventory.is_empty()
    assert all(game.hotbar.slot_stack(i) is None for i in range(HOTBAR_SIZE))
