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
from quadrix.render.mesher import FACE_DEFS, mesh_chunk
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


# ---------------------------------------------------------------------------
# ориентация UV и текстура на грань (порт ``mesher::standard_uv``)
# ---------------------------------------------------------------------------
#
# Rust ``mesher::standard_uv(facing, p)`` задаёт UV точки блока ``p`` для
# каждой грани: спрайт растёт сверху вниз (бок = ``1 - y``, верх = ``z``,
# низ = ``1 - z``). Мешер обязан повторить это побитово, иначе трава сбоку
# окажется у земли, а верх — перевёрнутым.

def _std_uv(face_index: int, x: float, y: float, z: float) -> tuple[float, float]:
    """UV точки блока для грани — эталон Rust ``standard_uv``.

    Порядок граней = ``mesher.FACE_DEFS``: south, north, east, west, up, down.
    """
    if face_index == 0:  # south (+Z)
        return (x, 1.0 - y)
    if face_index == 1:  # north (-Z)
        return (1.0 - x, 1.0 - y)
    if face_index == 2:  # east (+X)
        return (1.0 - z, 1.0 - y)
    if face_index == 3:  # west (-X)
        return (z, 1.0 - y)
    if face_index == 4:  # up (+Y)
        return (x, z)
    return (x, 1.0 - z)  # down (-Y)


def _mesh_single_block(atlas: object, block_name: str) -> tuple[int, np.ndarray]:
    """Один блок в воздухе без центрирования: локальные координаты = поз. - 8."""
    registry = default_registry()
    state = registry.default_state(block_name)
    assert state is not None, f"нет состояния {block_name}"
    blocks = np.zeros((16, 16, 16), dtype=np.uint16)
    blocks[8, 8, 8] = state.id
    vertices, _ = mesh_chunk(blocks, atlas, center=False)
    return state.id, vertices


def _face_vertices(vertices: np.ndarray, face_index: int) -> np.ndarray:
    """6 вершин грани ``face_index`` (по нормали из FACE_DEFS)."""
    normal = np.asarray(FACE_DEFS[face_index][0], dtype=np.float32)
    return vertices[np.all(vertices[:, 3:6] == normal, axis=1)]


def _face_center(rect: np.ndarray) -> np.ndarray:
    return np.array([rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0])


def _sprite_center(atlas: object, texture: str) -> np.ndarray:
    """Центр тайла текстуры в нормированных UV атласа (как ``norm``)."""
    x, y, w, h = atlas._sprite_rects[texture]
    return np.array([(x + w / 2.0) / atlas.width, (y + h / 2.0) / atlas.height])


def test_grass_up_uses_top_texture() -> None:
    """Грань UP травы — ``grass_block_top`` (не боковая)."""
    atlas = load_block_atlas()
    assert atlas is not None
    state = default_registry().default_state("minecraft:grass_block")
    rects = atlas.face_rects(np.asarray([state.id]))[0]
    assert np.allclose(
        _face_center(rects[4]), _sprite_center(atlas, "minecraft:block/grass_block_top")
    )


def test_grass_side_uses_side_texture() -> None:
    """Грани N/S/E/W травы — ``grass_block_side``."""
    atlas = load_block_atlas()
    assert atlas is not None
    state = default_registry().default_state("minecraft:grass_block")
    rects = atlas.face_rects(np.asarray([state.id]))[0]
    side = _sprite_center(atlas, "minecraft:block/grass_block_side")
    for fi in (0, 1, 2, 3):
        assert np.allclose(_face_center(rects[fi]), side)


def test_grass_down_uses_dirt_texture() -> None:
    """Грань DOWN травы — ``dirt``."""
    atlas = load_block_atlas()
    assert atlas is not None
    state = default_registry().default_state("minecraft:grass_block")
    rects = atlas.face_rects(np.asarray([state.id]))[0]
    assert np.allclose(
        _face_center(rects[5]), _sprite_center(atlas, "minecraft:block/dirt")
    )


def test_texel_orientation_matches_rust() -> None:
    """UV каждой вершины = Rust ``standard_uv`` (после нормировки в тайл)."""
    atlas = load_block_atlas()
    assert atlas is not None
    state, vertices = _mesh_single_block(atlas, "minecraft:grass_block")
    rects = atlas.face_rects(np.asarray([state]))[0]
    for fi in range(len(FACE_DEFS)):
        u0, v0, du, dv = rects[fi]
        for vertex in _face_vertices(vertices, fi):
            x, y, z = vertex[0] - 8.0, vertex[1] - 8.0, vertex[2] - 8.0
            exp_u, exp_v = _std_uv(fi, round(x), round(y), round(z))
            assert np.isclose((vertex[6] - u0) / du, exp_u, atol=1e-5)
            assert np.isclose((vertex[7] - v0) / dv, exp_v, atol=1e-5)


def test_side_uv_not_vertically_flipped() -> None:
    """Верх блока берёт верх спрайта: трава сверху, земля снизу."""
    atlas = load_block_atlas()
    assert atlas is not None
    state, vertices = _mesh_single_block(atlas, "minecraft:grass_block")
    u0, v0, du, dv = atlas.face_rects(np.asarray([state]))[0][0]  # south
    face = _face_vertices(vertices, 0)
    top = face[np.isclose(face[:, 1] - 8.0, 1.0)]  # y = 1, верх блока
    bottom = face[np.isclose(face[:, 1] - 8.0, 0.0)]  # y = 0, низ блока
    assert (top[:, 7] - v0).max() / dv < 0.5  # верх → верх спрайта
    assert (bottom[:, 7] - v0).min() / dv > 0.5  # низ → низ спрайта


def test_face_uv_order() -> None:
    """6 вершин грани идут как TRIANGLE_ORDER, углы не перепутаны."""
    from quadrix.render.mesher import TRIANGLE_ORDER

    atlas = load_block_atlas()
    assert atlas is not None
    _state, vertices = _mesh_single_block(atlas, "minecraft:grass_block")
    # один блок: на грань ровно 6 вершин, в порядке FACE_DEFS
    for fi, (_normal, corners) in enumerate(FACE_DEFS):
        group = vertices[fi * 6 : (fi + 1) * 6]
        for slot, corner_index in enumerate(TRIANGLE_ORDER):
            corner = np.asarray(corners[corner_index], dtype=np.float32) + 8.0
            assert np.allclose(group[slot, 0:3], corner)
        # общая вершина обоих треугольников (slot 0 и 3) — один угол (0)
        assert np.allclose(group[0, 6:8], group[3, 6:8])


def test_slab_faces_use_model_textures() -> None:
    """Полублок: UP/DOWN — текстуры top/bottom модели, бока — side."""
    atlas = load_block_atlas()
    assert atlas is not None
    reg = default_registry()
    slab = atlas.face_rects(np.asarray([reg.default_state("minecraft:sandstone_slab").id]))[0]
    full = atlas.face_rects(np.asarray([reg.default_state("minecraft:sandstone").id]))[0]
    for fi in range(len(FACE_DEFS)):
        assert np.allclose(_face_center(slab[fi]), _face_center(full[fi]))
