"""Настройки графики Horizon (порт ``horizon-client-render/src/graphics.rs``).

Здесь живут значения ``graphics::Graphics`` (файл ``horizon-graphics.txt``),
их перечисления, а также данные экрана ``graphics_ui.rs`` — страницы, группы
и строки настроек — с точными подписями, слайдерами, циклами и описаниями.

Rust — спецификация: значения, диапазоны, шаги и тексты перенесены дословно.
Отрисовка и ввод — в ``quadrix/render/graphics_ui.py``.

FALLBACK: возможности, которые сообщает рендер (``graphics::hdr_offered``,
``smooth_gradients_offered``, ``translucent_batching_offered``,
``gpu_culling_offer``), в headless-порте не определяются. Флаги ниже по
умолчанию ``False``; там, где Horizon на неподдерживаемой машине серый,
QuadRix тоже серый. Экстра-настройки (``horizon-extras.txt``: Fullbright,
Dynamic Lights, Hide Block Particles) перенесены минимально.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Optional

from quadrix.core import lang

__all__ = [
    "Cost",
    "Extras",
    "GraphicsSetting",
    "HorizonGraphics",
    "GRAPHICS_PAGES",
    "GRAPHICS_PAGE_NAMES",
    "GRAPHICS_PAGE_ABOUT",
    "cost_label",
    "cost_color",
    "extra_caption_text",
    "h_switch",
    "h_slider",
    "h_slider_steps",
    "h_label",
    "h_set_slider",
    "h_cycle",
    "horizon_apply_preset",
    "vanilla_apply_preset",
    "opt_switch",
    "opt_slider",
    "opt_slider_steps",
    "opt_label",
    "opt_set_slider",
    "opt_cycle",
    "item_blocked",
    "item_cycle",
    "item_label",
    "item_set_slider",
    "item_slider",
    "item_slider_steps",
    "item_steps",
    "item_switch",
    "name_and_value",
    "labelled",
    "labelled_percent",
    "on_off",
    "hexcolor",
    "max_workers",
]

# ---------------------------------------------------------------------------
# палитра BLOCKS_DARK (horizon-theme/src/lib.rs L463-485) и цвета стиля
# ---------------------------------------------------------------------------

_PAGE = 0x0F0D17
_INK = 0xECEDF3
_INK_SOFT = 0xC5C7D1
_MUTED = 0xA29CB8
_ACCENT = 0x9A86FF
_FACE = 0x5B3FD6
_OUTLINE = 0x05040A
_DANGER = 0xF07A68
_SUCCESS = 0x45C27A
_WARN = 0xF0B84F


def hexcolor(c: int, a: int) -> int:
    """Порт ``graphics_style::hex``: ``0xRRGGBB`` + альфа → упаковка Horizon."""
    return (
        (int(a) & 0xFF) << 24
        | (int(c) & 0xFF) << 16
        | ((int(c) >> 8) & 0xFF) << 8
        | ((int(c) >> 16) & 0xFF)
    )


# ---------------------------------------------------------------------------
# стоимость настройки (graphics_style::Cost)
# ---------------------------------------------------------------------------

class Cost:
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    SAVES = "saves"

    _LABEL = {
        "none": "No cost",
        "low": "Low cost",
        "medium": "Medium cost",
        "high": "High cost",
        "saves": "Saves time",
    }
    _RGB = {
        "none": _INK_SOFT,
        "low": _SUCCESS,
        "saves": _SUCCESS,
        "medium": _WARN,
        "high": _DANGER,
    }


def cost_label(cost: str) -> str:
    """Строка стоимости (переводится через ``lang`` как в ``lang::get``)."""
    return lang.get_or(Cost._LABEL[cost], Cost._LABEL[cost])


def cost_color(cost: str) -> int:
    """Цвет квадрата стоимости (``Cost::rgb`` через ``hex(...,255)``)."""
    return hexcolor(Cost._RGB[cost], 255)


# ---------------------------------------------------------------------------
# перечисления graphics.rs
# ---------------------------------------------------------------------------

PRESET_ALL = ["performance", "balanced", "quality", "ultra", "custom"]
PRESET_LABELS = {
    "performance": "Performance",
    "balanced": "Balanced",
    "quality": "Quality",
    "ultra": "Ultra",
    "custom": "Custom",
}

ENTITY_CULLING_ALL = ["off", "sync", "async"]
CULLING_LABELS = {"off": "Off", "sync": "Synchronous", "async": "Asynchronous"}

LEAF_CULLING_ALL = ["off", "hidden", "solid", "solid_aggressive", "hollow"]
LEAF_LABELS = {
    "off": "Off",
    "hidden": "Hidden Faces",
    "solid": "Solid",
    "solid_aggressive": "Solid Aggressive",
    "hollow": "Hollow",
}

PRESENT_MODE_ALL = ["auto", "fifo", "mailbox", "immediate"]
PRESENT_MODE_LABELS = {
    "auto": "Auto (VSync)",
    "fifo": "FIFO",
    "mailbox": "Mailbox",
    "immediate": "Immediate",
}

PACING_LABELS = {"efficient": "Efficient", "precise": "Precise"}

OVERLAY_ALL = ["off", "fps", "graph"]
OVERLAY_LABELS = {"off": "Off", "fps": "FPS", "graph": "FPS and Graph"}

FAR_DETAIL_ALL = ["full", "reduced"]
FAR_DETAIL_LABELS = {"full": "Full", "reduced": "Reduced"}

FRAME_GEN_ALL = ["off", "fsr3.1"]
FRAME_GEN_LABELS = {"off": "Off", "fsr3.1": "FSR 3.1"}

UPSCALING_ALL = ["native", "quality", "balanced", "performance", "ultraPerformance"]
UPSCALING_LABELS = {
    "native": "Native",
    "quality": "Quality",
    "balanced": "Balanced",
    "performance": "Performance",
    "ultraPerformance": "Ultra Performance",
}

# graphics_ui.rs отфильтровывает эти три на macOS; на Windows/Linux они есть.
_MACOS = False
GRAPHICS_API_CHOICES = (
    ["auto", "vulkan", "opengl"]
    if _MACOS
    else ["auto", "vulkan", "dx12", "opengl"]
)
GRAPHICS_API_LABELS = {
    "auto": "Auto",
    "vulkan": "Vulkan",
    "dx12": "DirectX 12",
    "opengl": "OpenGL",
}

SCREENSHOT_QUALITIES = [1, 2, 4, 8]
BLUE_MAP_RADII = [16, 32, 64, 128, 256]
UPLOAD_STEPS = [0, 256, 512, 1024, 2048, 4096, 8192, 16384]
LOD_STEPS = [
    0, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536,
    131072, 262144, 524288, 1048576, 2097152, 0,
]
# lod::MAX_CHUNKS подставляется ниже; 0 здесь — placeholder.
LOD_STEPS[-1] = 4194304

# FALLBACK: возможности рендера не определяются в headless-порте.
HDR_OFFERED = False
SMOOTH_GRADIENTS_OFFERED = False
TRANSLUCENT_BATCHING_OFFERED = False
GPU_CULLING_OFFERED = False
REDUCED_FAR_DETAIL_SUGGESTED = False


def max_workers() -> int:
    """``std::thread::available_parallelism()`` иначе 8."""
    try:
        return os.cpu_count() or 8
    except Exception:  # noqa: BLE001
        return 8


# ---------------------------------------------------------------------------
# Horizon Graphics (graphics::Graphics, defaults L779-833)
# ---------------------------------------------------------------------------

@dataclass
class HorizonGraphics:
    preset: str = "custom"
    lod_distance: int = 0
    far_detail: str = "full"
    blue_map_auto_detect: bool = False
    blue_map_radius: int = 64  # bluemap::DEFAULT_RADIUS
    cave_culling: bool = True
    gpu_culling: bool = False
    entity_culling: str = "off"
    entity_culling_precheck: int = 64
    particle_culling: str = "off"
    leaf_culling: str = "off"
    cache_shulker_boxes: bool = False
    cache_signs: bool = True
    cache_decorated_pots: bool = False
    cache_bells: bool = False
    cache_chests: bool = False
    cache_banners: bool = False
    cache_copper_golem_statues: bool = False
    chunk_updates: int = 0
    upload_budget_kib: int = 0
    texture_budget_mib: int = 0
    sky: bool = True
    fog: bool = True
    weather: bool = True
    animated_textures: bool = True
    dither_cutout_mips: bool = False
    present_mode: str = "auto"
    pacing: str = "efficient"
    workers: int = 0
    overlay: str = "off"
    resolution_scale: int = 100
    fxaa: bool = False
    taa: bool = False
    upscaling: str = "native"
    screenshot_quality: int = 1
    frame_generation: str = "off"
    hdr: bool = False
    hdr_paper_white: int = 0
    hdr_peak: int = 0
    hdr_black_level: int = 0
    hdr_ui_brightness: int = 100
    hdr_lighting: bool = True
    hdr_key: str = "key.keyboard.unknown"
    battery: bool = False
    shadow_cache: bool = False
    api: str = "auto"
    translucent_batching: bool = True
    hdr_smooth_gradients: bool = True
    shader_pack: str = ""

    # -- производные значения (graphics.rs L1060-1093) --------------------

    def paper_white_nits(self) -> int:
        return self.hdr_paper_white or 203

    def peak_nits(self) -> int:
        return self.hdr_peak or 1000

    def black_level_nits(self) -> float:
        return (self.hdr_black_level or 0) / 100.0

    def worker_threads(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(1, max_workers() - 1)

    def radius_chunks(self) -> int:
        return self.blue_map_radius or 64

    def clone(self) -> "HorizonGraphics":
        return HorizonGraphics(**vars(self))


# ---------------------------------------------------------------------------
# extras (horizon-extras.txt) — минимальный порт
# ---------------------------------------------------------------------------

@dataclass
class Extras:
    """FALLBACK: ``extras::Item`` для 3 строк Quality-страницы.

    Rust хранит их в ``horizon-extras.txt``; здесь — только поля, которые
    читает графика (Fullbright, Dynamic Lights, Hide Block Particles) плюс
    колесо мыши (``wheel_cycles_settings``).
    """

    fullbright: bool = False
    dynamic_lights: bool = False
    hide_block_particles: bool = False
    wheel_cycles_settings: bool = False
    three_d_skin_layers: bool = False

    def switch(self, item: str) -> Optional[bool]:
        mapping = {
            "fullbright": self.fullbright,
            "dynamic_lights": self.dynamic_lights,
            "hide_block_particles": self.hide_block_particles,
        }
        return mapping.get(item)

    def toggle(self, item: str) -> None:
        if item == "fullbright":
            self.fullbright = not self.fullbright
        elif item == "dynamic_lights":
            self.dynamic_lights = not self.dynamic_lights
        elif item == "hide_block_particles":
            self.hide_block_particles = not self.hide_block_particles

    def value(self, item: str) -> str:
        on = self.switch(item)
        return on_off(bool(on))


# ---------------------------------------------------------------------------
# языковые помощники (дословно graphics_ui.rs L732-756)
# ---------------------------------------------------------------------------

def _tr(key: str, *args: Any, default: Optional[str] = None) -> str:
    fmt = lang.get_or(key, default if default is not None else key)
    if args:
        try:
            return fmt % args
        except (TypeError, ValueError):
            return fmt
    return fmt


def on_off(on: bool) -> str:
    return lang.get_or("On" if on else "Off", "On" if on else "Off")


def labelled(caption: str, value: Any) -> str:
    """``generic(caption, value)`` через ``options.generic_value``."""
    cap = lang.get_or(caption, caption)
    val = lang.get_or(str(value), str(value))
    fmt = lang.get_or("options.generic_value", "%s: %s")
    return fmt.replace("%s", cap, 1).replace("%s", val, 1)


def labelled_percent(caption: str, percent: int) -> str:
    """``options.percent_value`` (French/German ставят пробел перед %)."""
    cap = lang.get_or(caption, caption)
    fmt = lang.get_or("options.percent_value", "%s: %s%%")
    out = fmt.replace("%s", cap, 1).replace("%s", str(percent), 1)
    # Формат lang-файла экранирует знак процента как «%%»; подстановка идёт
    # вручную, поэтому снимаем экранирование здесь (Rust: Text::translate).
    return out.replace("%%", "%")


def name_and_value(label: str) -> tuple[str, Optional[str]]:
    """Порт ``settings_shell::name_and_value``: имя и значение из подписи."""
    fmt = lang.get_or("options.generic_value", "%s: %s")
    chunks = fmt.split("%s")
    sep = chunks[1] if len(chunks) > 1 else ": "
    if not sep or sep not in label:
        sep = ": "
    if sep in label:
        name, value = label.split(sep, 1)
        return name, value
    return label, None


# ---------------------------------------------------------------------------
# данные строк (graphics_ui.rs::rows L159-637)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GraphicsSetting:
    """Одна строка: элемент (``H``/``Opt``/``Extra``), стоимость и описание."""

    kind: str  # "H" | "Opt" | "Extra"
    name: str
    cost: str
    text: str  # ключ описания (для Extra) либо английский текст

    @property
    def item(self) -> tuple[str, str]:
        return (self.kind, self.name)


GRAPHICS_PAGE_NAMES = ["General", "Quality", "Performance", "Shaders", "Advanced", "HDR"]
GRAPHICS_PAGE_ABOUT = {
    "General": "How far you see, the window and the HUD.",
    "Quality": "The sky and weather, lighting, textures and the image.",
    "Performance": "Chunk loading, culling and power use.",
    "Shaders": "Shader packs, QuadRix's and shaders/ folder ones, and their options.",
    "Advanced": "How frames reach the screen, and the performance overlay.",
    "HDR": "Brighter-than-white output on an HDR display.",
}

_N = Cost.NONE
_L = Cost.LOW
_M = Cost.MEDIUM
_H = Cost.HIGH
_S = Cost.SAVES


def _h(name: str, cost: str, text: str) -> GraphicsSetting:
    return GraphicsSetting("H", name, cost, text)


def _v(name: str, cost: str, text: str) -> GraphicsSetting:
    return GraphicsSetting("Opt", name, cost, text)


def _e(name: str, cost: str) -> GraphicsSetting:
    return GraphicsSetting("Extra", name, cost, name)


def _rows() -> list[tuple[str, list[tuple[str, list[GraphicsSetting]]]]]:
    far = (
        "Reduced draws far terrain coarser: faster on this integrated GPU."
        if REDUCED_FAR_DETAIL_SUGGESTED
        else "Reduced draws far terrain coarser, for GPUs it slows down."
    )
    pages: list[tuple[str, list[tuple[str, list[GraphicsSetting]]]]] = [
        (
            "General",
            [
                ("Preset", [
                    _h("Preset", _N,
                       "Sets the options below together. Changing one makes it Custom."),
                    _v("Preset", _N,
                       "Vanilla's own preset: sets only vanilla's options, as Minecraft does."),
                ]),
                ("Distance", [
                    _v("RenderDistance", _H,
                       "Full-detail terrain range. LOD Distance can extend local worlds farther."),
                    _h("LodDistance", _M,
                       "Coarse distant terrain in local worlds. Integrated GPUs stop at 128 chunks."),
                    _h("FarDetail", _M, far),
                    _h("BlueMapAutoDetect", _N,
                       "On servers, finds their BlueMap web map for far terrain. Next join."),
                    _h("BlueMapRadius", _N,
                       "How far around you BlueMap tiles are downloaded. Next join."),
                    _v("SimulationDistance", _M,
                       "How far mobs, crops and machines keep working. CPU time."),
                    _v("Gamma", _N, "Brightens dark places."),
                ]),
                ("Display", [
                    _v("GuiScale", _N, "Size of menus and the HUD."),
                    _v("Fullscreen", _N, "Fills the screen (borderless)."),
                    _v("ExclusiveFullscreen", _N,
                       "Fullscreen takes the display over, at the mode below."),
                    _v("ExclusiveMode", _N,
                       "The display mode exclusive fullscreen uses. Applies when you leave."),
                    _v("Vsync", _N,
                       "Waits for the display's refresh: no tearing, a little latency."),
                    _v("MaxFps", _N,
                       "Caps frames per second; a cap saves power and heat."),
                    _v("InactivityFps", _N,
                       "Lowers the frame rate when minimised, or idle too."),
                ]),
                ("Interface", [
                    _v("MenuBlur", _L, "Blurs the world behind menus."),
                    _v("AttackIndicator", _N, "Shows attack cooldown."),
                    _v("Autosave", _N, "Shows when the world saves."),
                ]),
            ],
        ),
        (
            "Quality",
            [
                ("Sky and weather", [
                    _v("Clouds", _L, "Cloud layer: off, flat (fast) or 3D (fancy)."),
                    _v("CloudRange", _L, "How far clouds reach, in chunks."),
                    _h("Sky", _L, "Draws the sky, sun, moon and stars."),
                    _h("Fog", _N, "Distance fog. Off shows the edge of the loaded world."),
                    _h("Weather", _H, "Draws rain and snow."),
                    _v("WeatherRadius", _M, "How far rain and snow fall around you."),
                    _v("Particles", _M, "How many particles effects spawn."),
                    _e("HideBlockParticles", _N),
                ]),
                ("Lighting and entities", [
                    _v("SmoothLighting", _L,
                       "Soft shadows in corners. Costs chunk building time only."),
                    _v("BiomeBlend", _L,
                       "Blends grass and water colours across biomes when building chunks."),
                    _v("EntityDistance", _M,
                       "How far away mobs and items are drawn, as a share of normal."),
                    _v("EntityShadows", _L, "Round shadows under mobs and items."),
                    _v("Vignette", _N, "Darkens the screen's edges."),
                    _v("ChunkFade", _N, "Fades newly loaded chunks in."),
                    _e("DynamicLights", _L),
                    _e("Fullbright", _N),
                ]),
                ("Textures", [
                    _v("Mipmaps", _N,
                       "Smaller copies of block textures for distant terrain: less shimmer."),
                    _v("TextureFiltering", _L,
                       "How textures are sampled: sharper at a slant with Anisotropic."),
                    _v("MaxAnisotropy", _L,
                       "How far Anisotropic filtering goes. Higher is sharper at a slant."),
                    _v("CutoutLeaves", _M,
                       "Leaves with see-through gaps. Off draws them solid."),
                    _v("ImprovedTransparency", _M,
                       "Sorts water and glass more exactly behind each other."),
                    _h("AnimatedTextures", _L,
                       "Animates water, lava, fire and other moving textures."),
                    _h("DitherCutoutMips", _L,
                       "Keeps fine plants in high-res packs from fading far away."),
                ]),
                ("Image", [
                    _h("ResolutionScale", _H,
                       "World pixels per screen pixel. Below 100% is faster on the GPU."),
                    _h("Antialiasing", _M,
                       "Smooths jagged edges. FXAA: softer. TAA: smoothest, moving things may trail."),
                    _h("Upscaling", _H,
                       "Renders the world smaller and rebuilds it with TAA. Faster, softer."),
                    _h("ScreenshotQuality", _N,
                       "F2 screenshots at this many times the game's resolution. Higher takes longer."),
                    _h("FrameGeneration", _M,
                       "Shows a made-up frame between each two real ones: smoother, a little more lag."),
                ]),
            ],
        ),
        (
            "Performance",
            [
                ("Chunk loading", [
                    _v("ChunkBuilder", _L,
                       "Which chunk rebuilds wait for the frame: none, nearby or yours."),
                    _h("ChunkUpdates", _L,
                       "Meshed sections uploaded per frame. Lower is smoother while loading."),
                    _h("UploadBudget", _L,
                       "Mesh data sent to the GPU per frame. Lower is smoother while loading."),
                    _h("Workers", _N,
                       "Threads that generate, light and mesh chunks. Next start."),
                ]),
                ("Culling", [
                    _h("CaveCulling", _S,
                       "Skips terrain hidden behind closed sections. Off costs a lot."),
                    _h("GpuCulling", _S,
                       "Culls nearby terrain on the GPU: less CPU at high render distance, more GPU."),
                    _h("EntityCulling", _N, "Hides entities behind opaque blocks."),
                    _h("ParticleCulling", _S,
                       "Skips particles outside the view, below one pixel or behind terrain."),
                    _h("EntityCullingPrecheck", _S,
                       "Runs the mob AABB precheck after this many loaded mobs. Zero disables it."),
                    _h("LeafCulling", _S,
                       "Draws or drops leaf faces inside canopies. Off keeps vanilla's fancy leaves."),
                ]),
                ("Block Entities", [
                    _h("CacheShulkerBoxes", _S,
                       "Reuses settled boxes; lid movement stays animated."),
                    _h("CacheSigns", _S,
                       "Reuses sign text until text, light, or font changes."),
                    _h("CacheDecoratedPots", _S,
                       "Reuses still pots; break wobble and sherd changes redraw."),
                    _h("CacheBells", _S, "Reuses still bells; ringing stays animated."),
                    _h("CacheChests", _S, "Reuses closed chests; moving lids stay animated."),
                    _h("CacheBanners", _S,
                       "Reuses poles; flags and pattern layers still update."),
                    _h("CacheCopperGolemStatues", _S,
                       "Reuses statue geometry until its block state changes."),
                ]),
                ("Power", [
                    _h("BatteryMode", _N,
                       "60 FPS cap (30 in menus or unfocused), half the workers: less power."),
                ]),
            ],
        ),
        (
            "Shaders",
            [
                ("Shader packs", [
                    _h("ShaderPacks", _H,
                       "Picks a shader pack, QuadRix's or a shaders/ folder one, and sets its options."),
                    _h("ShadowCache", _S,
                       "Reuses the pack shadow map when sun, view and world match. Off by default."),
                ]),
            ],
        ),
        (
            "Advanced",
            [
                ("Frames", [
                    _h("PresentMode", _N,
                       "How frames reach the screen while VSync is off."),
                    _h("Pacing", _N,
                       "Efficient sleeps until the next frame; Precise spins, like vanilla."),
                    _h("GraphicsApi", _N,
                       "Vulkan, then DirectX 12 (Windows) or OpenGL (Linux) where it fails. Next start."),
                    _h("TranslucentBatching", _S,
                       "Water and glass in one buffer: fewer draw calls, a bit more VRAM. Next start."),
                ]),
                ("Overlay", [
                    _h("Overlay", _N,
                       "Frame rate and frame times over the game, with a graph."),
                ]),
            ],
        ),
        (
            "HDR",
            [
                ("Output", [
                    _h("Hdr", _N,
                       "Lava, fire and sunlight shine brighter than white. Needs an HDR display."),
                    _h("HdrSmoothGradients", _L,
                       "16-bit frame: dark skies and shadows don't band. A bit more VRAM. Next start."),
                    _h("HdrCalibrate", _N,
                       "Sets the three below full screen, one test picture at a time."),
                ]),
                ("Brightness", [
                    _h("HdrBlackLevel", _N,
                       "Your display's darkest black. 0 for OLED; LCDs glow a little."),
                    _h("HdrPeak", _N,
                       "How bright highlights get. Auto: the peak your system reports."),
                    _h("HdrPaperWhite", _N,
                       "How bright white paper and menus look. Auto: your desktop's white."),
                    _h("HdrUiBrightness", _N,
                       "How bright the HUD and menus are, against paper white."),
                    _h("HdrLighting", _N,
                       "Light sources, the sun and sunlight shine past white. Off: just as SDR."),
                ]),
                ("Shortcut", [
                    _h("HdrKey", _N,
                       "A key that opens this screen from the game. Not bound at first."),
                ]),
            ],
        ),
    ]
    if _MACOS:
        drop = {"GraphicsApi", "TranslucentBatching", "GpuCulling"}
        pages = [
            (page, [
                (group, [s for s in rows if not (s.kind == "H" and s.name in drop)])
                for group, rows in groups
            ])
            for page, groups in pages
        ]
    return pages


GRAPHICS_PAGES = _rows()


# ---------------------------------------------------------------------------
# элементы строки: switch / slider / label / set_slider / cycle
# (graphics_ui.rs::H, options_ui.rs::Opt, extras.rs::Item)
# ---------------------------------------------------------------------------

RENDER_DISTANCE_MAX = 32  # options_file::MAX_RENDER_DISTANCE
VIDEO_FILTERING = ["options.textureFiltering.none", "options.textureFiltering.rgss",
                   "options.textureFiltering.anisotropic"]
PARTICLE_LABELS = ["options.particles.all", "options.particles.decreased",
                   "options.particles.minimal"]
ATTACK_LABELS = ["options.off", "options.attack.crosshair", "options.attack.hotbar"]
CHUNK_BUILDER_LABELS = ["options.prioritizeChunkUpdates.none",
                        "options.prioritizeChunkUpdates.byPlayer",
                        "options.prioritizeChunkUpdates.nearby"]
# options_ui.rs::PRESETS — ванильные пресеты (options.graphics.*).
VANILLA_PRESETS = ["fast", "fancy", "fabulous", "custom"]
# graphics_ui.rs::Item::touched — эти строки не сбрасывают пресет Horizon.
_H_PRESETLESS = {
    "Preset", "BlueMapAutoDetect", "BlueMapRadius", "Overlay", "ScreenshotQuality",
    "Pacing", "PresentMode", "Workers", "FrameGeneration", "BatteryMode",
    "ShadowCache", "GraphicsApi", "TranslucentBatching", "HdrSmoothGradients",
    "GpuCulling",
}
_OPT_PRESETLESS = {
    "GuiScale", "Fullscreen", "ExclusiveFullscreen", "ExclusiveMode", "Vsync",
    "MaxFps", "Gamma", "InactivityFps", "MenuBlur", "ChunkFade", "Vignette",
    "Autosave", "AttackIndicator",
}
# options_ui.rs::Opt::affects_preset — эти строки меняют ванильный пресет.
_OPT_AFFECTS_PRESET = {
    "RenderDistance", "SimulationDistance", "SmoothLighting", "Clouds", "CloudRange",
    "Particles", "EntityDistance", "EntityShadows", "BiomeBlend", "Mipmaps",
    "WeatherRadius", "CutoutLeaves", "ImprovedTransparency", "MenuBlur",
    "ChunkBuilder", "TextureFiltering", "MaxAnisotropy",
}
# options_ui.rs::Opt::caption — ключ подписи.
_OPT_CAPTION = {
    "RenderDistance": "options.renderDistance",
    "SimulationDistance": "options.simulationDistance",
    "GuiScale": "options.guiScale",
    "Gamma": "options.gamma",
    "MaxFps": "options.framerateLimit",
    "Vsync": "options.vsync",
    "Fullscreen": "options.fullscreen",
    "ExclusiveFullscreen": "options.exclusiveFullscreen",
    "ExclusiveMode": "options.fullscreen.exclusive.mode",
    "TextureFiltering": "options.textureFiltering",
    "MaxAnisotropy": "options.maxAnisotropy",
    "SmoothLighting": "options.ao",
    "Clouds": "options.renderClouds",
    "CloudRange": "options.renderCloudsDistance",
    "Particles": "options.particles",
    "EntityDistance": "options.entityDistanceScaling",
    "EntityShadows": "options.entityShadows",
    "BiomeBlend": "options.biomeBlendRadius",
    "Preset": "options.graphics.preset",
    "Mipmaps": "options.mipmapLevels",
    "WeatherRadius": "options.weatherRadius",
    "ChunkFade": "options.chunkFade",
    "Vignette": "options.vignette",
    "Autosave": "options.autosaveIndicator",
    "CutoutLeaves": "options.cutoutLeaves",
    "ImprovedTransparency": "options.improvedTransparency",
    "AttackIndicator": "options.attackIndicator",
    "InactivityFps": "options.inactivityFpsLimit",
    "ChunkBuilder": "options.prioritizeChunkUpdates",
    "MenuBlur": "options.accessibility.menu_background_blurriness",
}
# extras.rs::Item::caption_key/caption — подписи трёх Extra-строк Quality.
_EXTRA_CAPTION = {
    "Fullbright": ("horizon.extras.fullbright", "Fullbright"),
    "DynamicLights": ("horizon.extras.dynamic_lights", "Dynamic lights"),
    "HideBlockParticles": ("horizon.extras.hide_block_particles",
                           "Hide block-break particles"),
}


def _lang(key: str, fallback: str) -> str:
    return lang.get_or(key, fallback)


def _on_off_opt(v: bool) -> str:
    return _lang("options.on" if v else "options.off", "On" if v else "Off")


def _next(n: int, count: int, back: bool) -> int:
    return (n + count - 1) % count if back else (n + 1) % count


def _step(allv: list, now: Any, back: bool) -> Any:
    i = allv.index(now) if now in allv else 0
    n = len(allv)
    return allv[(i + n - 1) % n] if back else allv[(i + 1) % n]


def _preset_index(p: str) -> int:
    return VANILLA_PRESETS.index(p) if p in VANILLA_PRESETS else 1


def _unit(v: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.0, (v - lo) / (hi - lo)))


def _percent(caption: str, value: float) -> str:
    """``options_ui::percent`` — ``(value*100) as i32`` (усечение)."""
    return labelled_percent(caption, int(value * 100.0))


def _fbool(s: Any, key: str, default: bool = False) -> bool:
    return bool(s.file.get(key, default))


def _fint(s: Any, key: str, default: int = 0) -> int:
    try:
        return int(s.file.get(key, default))
    except (TypeError, ValueError):
        return default


def _fset(s: Any, key: str, value: Any) -> None:
    s.file[key] = value


def extra_caption_text(name: str) -> str:
    key, fallback = _EXTRA_CAPTION.get(name, (name, name))
    return lang.get_or(key, fallback)


# -- H (Horizon) ------------------------------------------------------------

def h_switch(s: Any, name: str) -> Optional[bool]:
    g = s.horizon
    if name == "BlueMapAutoDetect":
        return g.blue_map_auto_detect
    if name == "CaveCulling":
        return g.cave_culling
    if name == "GpuCulling":
        return g.gpu_culling and GPU_CULLING_OFFERED
    if name == "CacheShulkerBoxes":
        return g.cache_shulker_boxes
    if name == "CacheSigns":
        return g.cache_signs
    if name == "CacheDecoratedPots":
        return g.cache_decorated_pots
    if name == "CacheBells":
        return g.cache_bells
    if name == "CacheChests":
        return g.cache_chests
    if name == "CacheBanners":
        return g.cache_banners
    if name == "CacheCopperGolemStatues":
        return g.cache_copper_golem_statues
    if name == "Sky":
        return g.sky
    if name == "Fog":
        return g.fog
    if name == "Weather":
        return g.weather
    if name == "AnimatedTextures":
        return g.animated_textures
    if name == "DitherCutoutMips":
        return g.dither_cutout_mips
    if name == "Hdr":
        return g.hdr
    if name == "HdrLighting":
        return g.hdr_lighting
    if name == "BatteryMode":
        return g.battery
    if name == "ShadowCache":
        return g.shadow_cache
    if name == "TranslucentBatching":
        return g.translucent_batching and TRANSLUCENT_BATCHING_OFFERED
    if name == "HdrSmoothGradients":
        return g.hdr_smooth_gradients and SMOOTH_GRADIENTS_OFFERED
    return None


def h_slider(s: Any, name: str) -> Optional[float]:
    g = s.horizon
    if name == "ChunkUpdates":
        return g.chunk_updates / 64.0
    if name == "EntityCullingPrecheck":
        return g.entity_culling_precheck / 512.0
    if name == "UploadBudget":
        i = next((k for k, b in enumerate(UPLOAD_STEPS) if b >= g.upload_budget_kib),
                 len(UPLOAD_STEPS) - 1)
        return i / (len(UPLOAD_STEPS) - 1)
    if name == "LodDistance":
        i = next((k for k, d in enumerate(LOD_STEPS) if d >= g.lod_distance),
                 len(LOD_STEPS) - 1)
        return i / (len(LOD_STEPS) - 1)
    if name == "Workers":
        return g.workers / max_workers()
    if name == "ResolutionScale":
        return (g.resolution_scale - 50.0) / 150.0
    if name == "HdrPaperWhite":
        return g.hdr_paper_white / 480.0
    if name == "HdrPeak":
        return 0.0 if g.hdr_peak == 0 else (g.hdr_peak - 150.0) / 1850.0
    if name == "HdrBlackLevel":
        return g.hdr_black_level / 100.0
    if name == "HdrUiBrightness":
        return (g.hdr_ui_brightness - 25.0) / 75.0
    return None


def h_slider_steps(name: str) -> Optional[int]:
    return {
        "ChunkUpdates": 64,
        "EntityCullingPrecheck": 32,
        "UploadBudget": len(UPLOAD_STEPS) - 1,
        "Workers": max_workers(),
        "ResolutionScale": 30,
        "HdrPaperWhite": 41,
        "HdrPeak": 37,
        "HdrBlackLevel": 100,
        "HdrUiBrightness": 15,
    }.get(name)


def h_label(s: Any, name: str) -> str:
    g = s.horizon
    if name == "Preset":
        return labelled("Preset", PRESET_LABELS.get(g.preset, "Custom"))
    if name == "LodDistance":
        if g.lod_distance == 0:
            return labelled("LOD Distance", _lang("Off", "Off"))
        return labelled("LOD Distance", _tr("%s chunks", g.lod_distance,
                                            default="%s chunks"))
    if name == "FarDetail":
        return labelled("Far Detail", FAR_DETAIL_LABELS.get(g.far_detail, "Full"))
    if name == "BlueMapAutoDetect":
        return labelled("Find BlueMap", on_off(g.blue_map_auto_detect))
    if name == "BlueMapRadius":
        return labelled("BlueMap Radius", _tr("%s chunks", g.radius_chunks(),
                                              default="%s chunks"))
    if name == "CaveCulling":
        return labelled("Cave Culling", on_off(g.cave_culling))
    if name == "GpuCulling":
        return labelled("GPU Culling", on_off(g.gpu_culling and GPU_CULLING_OFFERED))
    if name == "EntityCulling":
        return labelled("Entity Culling", CULLING_LABELS.get(g.entity_culling, "Off"))
    if name == "EntityCullingPrecheck":
        value = (_lang("Off", "Off") if g.entity_culling_precheck == 0
                 else _tr("%s mobs", g.entity_culling_precheck, default="%s mobs"))
        return labelled("Entity Culling Precheck", value)
    if name == "ParticleCulling":
        return labelled("Particle Culling", CULLING_LABELS.get(g.particle_culling, "Off"))
    if name == "LeafCulling":
        return labelled("Leaf Culling", LEAF_LABELS.get(g.leaf_culling, "Off"))
    if name == "CacheShulkerBoxes":
        return labelled("Shulker Boxes", on_off(g.cache_shulker_boxes))
    if name == "CacheSigns":
        return labelled("Signs", on_off(g.cache_signs))
    if name == "CacheDecoratedPots":
        return labelled("Decorated Pots", on_off(g.cache_decorated_pots))
    if name == "CacheBells":
        return labelled("Bells", on_off(g.cache_bells))
    if name == "CacheChests":
        return labelled("Chests", on_off(g.cache_chests))
    if name == "CacheBanners":
        return labelled("Banners", on_off(g.cache_banners))
    if name == "CacheCopperGolemStatues":
        return labelled("Copper Golem Statues", on_off(g.cache_copper_golem_statues))
    if name == "ChunkUpdates":
        value = (_lang("Unlimited", "Unlimited") if g.chunk_updates == 0
                 else _tr("%s per frame", g.chunk_updates, default="%s per frame"))
        return labelled("Chunk Updates", value)
    if name == "UploadBudget":
        k = g.upload_budget_kib
        if k == 0:
            value = "Unlimited"
        elif k >= 1024:
            value = _tr("%s MiB/frame", k // 1024, default="%s MiB/frame")
        else:
            value = _tr("%s KiB/frame", k, default="%s KiB/frame")
        return labelled("Upload Budget", value)
    if name == "Sky":
        return labelled("Sky", on_off(g.sky))
    if name == "Fog":
        return labelled("Fog", on_off(g.fog))
    if name == "Weather":
        return labelled("Weather", on_off(g.weather))
    if name == "AnimatedTextures":
        return labelled("Animated Textures", on_off(g.animated_textures))
    if name == "DitherCutoutMips":
        return labelled("Distant Plant Dither", on_off(g.dither_cutout_mips))
    if name == "PresentMode":
        return labelled("Present Mode", PRESENT_MODE_LABELS.get(g.present_mode, "Auto"))
    if name == "Pacing":
        return labelled("Frame Pacing", PACING_LABELS.get(g.pacing, "Efficient"))
    if name == "Workers":
        if g.workers == 0:
            return labelled("Worker Threads",
                            _tr("Auto (%s)", g.worker_threads(), default="Auto (%s)"))
        return labelled("Worker Threads", g.workers)
    if name == "ResolutionScale":
        return labelled_percent("Resolution Scale", g.resolution_scale)
    if name == "Antialiasing":
        value = "TAA" if g.taa else ("FXAA" if g.fxaa else "Off")
        return labelled("Anti-aliasing", value)
    if name == "Upscaling":
        return labelled("Upscaling", UPSCALING_LABELS.get(g.upscaling, "Native"))
    if name == "ScreenshotQuality":
        return labelled("Screenshot Quality", "%dx" % g.screenshot_quality)
    if name == "FrameGeneration":
        return labelled("Frame Generation", FRAME_GEN_LABELS.get(g.frame_generation, "Off"))
    if name == "Hdr":
        return labelled("HDR", on_off(g.hdr))
    if name == "HdrCalibrate":
        if not HDR_OFFERED:
            return _lang("Calibrate...", "Calibrate...")
        if g.hdr_peak == 0 and g.hdr_paper_white == 0:
            return _lang("Calibrate Anyway...", "Calibrate Anyway...")
        return _lang("Use Automatic Setup", "Use Automatic Setup")
    if name == "HdrPaperWhite":
        if g.hdr_paper_white == 0:
            return labelled("Paper White", _tr("Auto (%s)", g.paper_white_nits(),
                                               default="Auto (%s)"))
        return labelled("Paper White", g.hdr_paper_white)
    if name == "HdrPeak":
        if g.hdr_peak == 0:
            return labelled("Peak Brightness", _tr("Auto (%s)", g.peak_nits(),
                                                   default="Auto (%s)"))
        return labelled("Peak Brightness", g.hdr_peak)
    if name == "HdrBlackLevel":
        if g.hdr_black_level == 0:
            return labelled("Black Level", _tr("Auto (%s)", "%.2f" % g.black_level_nits(),
                                               default="Auto (%s)"))
        return labelled("Black Level", "%.2f" % (g.hdr_black_level / 100.0))
    if name == "HdrUiBrightness":
        return labelled_percent("UI Brightness", g.hdr_ui_brightness)
    if name == "HdrLighting":
        return labelled("HDR Lighting", on_off(g.hdr_lighting))
    if name == "HdrKey":
        return _tr("Shortcut: %s", _key_display_name(g.hdr_key),
                   default="Shortcut: %s")
    if name == "BatteryMode":
        return labelled("Battery Mode", on_off(g.battery))
    if name == "ShadowCache":
        return labelled("Shadow Cache", on_off(g.shadow_cache))
    if name == "ShaderPacks":
        return _lang("Shader Packs...", "Shader Packs...")
    if name == "GraphicsApi":
        return labelled("Graphics API", GRAPHICS_API_LABELS.get(g.api, "Auto"))
    if name == "TranslucentBatching":
        return labelled("Translucent Batching",
                        on_off(g.translucent_batching and TRANSLUCENT_BATCHING_OFFERED))
    if name == "HdrSmoothGradients":
        return labelled("Smooth Gradients",
                        on_off(g.hdr_smooth_gradients and SMOOTH_GRADIENTS_OFFERED))
    if name == "Overlay":
        return labelled("Performance Overlay", OVERLAY_LABELS.get(g.overlay, "Off"))
    return ""


def _key_display_name(key: str) -> str:
    """FALLBACK: ``keybinds::display_name`` не портирован — имя ключа как есть."""
    if key in ("", "key.keyboard.unknown"):
        return "Unknown"
    return key.split(".")[-1].capitalize()


def h_set_slider(s: Any, name: str, v: float) -> None:
    g = s.horizon
    v = max(0.0, min(1.0, v))
    if name == "ChunkUpdates":
        g.chunk_updates = int(round(v * 64.0))
    elif name == "EntityCullingPrecheck":
        g.entity_culling_precheck = int(round(v * 512.0))
    elif name == "UploadBudget":
        g.upload_budget_kib = UPLOAD_STEPS[int(round(v * (len(UPLOAD_STEPS) - 1)))]
    elif name == "LodDistance":
        g.lod_distance = LOD_STEPS[int(round(v * (len(LOD_STEPS) - 1)))]
    elif name == "Workers":
        g.workers = int(round(v * max_workers()))
    elif name == "ResolutionScale":
        g.resolution_scale = int(50.0 + round(v * 30.0) * 5.0)
    elif name == "HdrPaperWhite":
        g.hdr_paper_white = int(round(v * 48.0)) * 10
    elif name == "HdrPeak":
        step = int(round(v * 37.0))
        g.hdr_peak = 0 if step == 0 else 150 + step * 50
    elif name == "HdrBlackLevel":
        g.hdr_black_level = int(round(v * 100.0))
    elif name == "HdrUiBrightness":
        g.hdr_ui_brightness = int(25.0 + round(v * 15.0) * 5.0)


def h_cycle(s: Any, name: str, back: bool) -> None:
    g = s.horizon
    if name == "Preset":
        preset = _step(PRESET_ALL, g.preset, back)
        horizon_apply_preset(preset, s)
        s.horizon.preset = preset
        return
    if name == "FarDetail":
        g.far_detail = _step(FAR_DETAIL_ALL, g.far_detail, back)
    elif name == "BlueMapAutoDetect":
        g.blue_map_auto_detect = not g.blue_map_auto_detect
    elif name == "BlueMapRadius":
        g.blue_map_radius = _step(BLUE_MAP_RADII, g.radius_chunks(), back)
    elif name == "CaveCulling":
        g.cave_culling = not g.cave_culling
    elif name == "GpuCulling":
        g.gpu_culling = not g.gpu_culling
    elif name == "EntityCulling":
        g.entity_culling = _step(ENTITY_CULLING_ALL, g.entity_culling, back)
    elif name == "ParticleCulling":
        g.particle_culling = _step(ENTITY_CULLING_ALL, g.particle_culling, back)
    elif name == "LeafCulling":
        g.leaf_culling = _step(LEAF_CULLING_ALL, g.leaf_culling, back)
    elif name == "CacheShulkerBoxes":
        g.cache_shulker_boxes = not g.cache_shulker_boxes
    elif name == "CacheSigns":
        g.cache_signs = not g.cache_signs
    elif name == "CacheDecoratedPots":
        g.cache_decorated_pots = not g.cache_decorated_pots
    elif name == "CacheBells":
        g.cache_bells = not g.cache_bells
    elif name == "CacheChests":
        g.cache_chests = not g.cache_chests
    elif name == "CacheBanners":
        g.cache_banners = not g.cache_banners
    elif name == "CacheCopperGolemStatues":
        g.cache_copper_golem_statues = not g.cache_copper_golem_statues
    elif name == "Sky":
        g.sky = not g.sky
    elif name == "Fog":
        g.fog = not g.fog
    elif name == "Weather":
        g.weather = not g.weather
    elif name == "AnimatedTextures":
        g.animated_textures = not g.animated_textures
    elif name == "DitherCutoutMips":
        g.dither_cutout_mips = not g.dither_cutout_mips
    elif name == "PresentMode":
        g.present_mode = _step(PRESENT_MODE_ALL, g.present_mode, back)
    elif name == "Antialiasing":
        i = 2 if g.taa else int(g.fxaa)
        i = (i + (2 if back else 1)) % 3
        g.fxaa, g.taa = (i == 1), (i == 2)
        if not g.taa:
            g.upscaling = "native"
    elif name == "Upscaling":
        g.upscaling = _step(UPSCALING_ALL, g.upscaling, back)
        if g.upscaling != "native":
            g.fxaa, g.taa = False, True
    elif name == "ScreenshotQuality":
        g.screenshot_quality = _step(SCREENSHOT_QUALITIES, g.screenshot_quality, back)
    elif name == "FrameGeneration":
        g.frame_generation = _step(FRAME_GEN_ALL, g.frame_generation, back)
    elif name == "Hdr":
        g.hdr = not g.hdr
    elif name == "HdrLighting":
        g.hdr_lighting = not g.hdr_lighting
    elif name == "BatteryMode":
        g.battery = not g.battery
    elif name == "ShadowCache":
        g.shadow_cache = not g.shadow_cache
    elif name == "GraphicsApi":
        g.api = _step(GRAPHICS_API_CHOICES, g.api, back)
    elif name == "TranslucentBatching":
        g.translucent_batching = not g.translucent_batching
    elif name == "HdrSmoothGradients":
        g.hdr_smooth_gradients = not g.hdr_smooth_gradients
    elif name == "Pacing":
        g.pacing = "precise" if g.pacing == "efficient" else "efficient"
    elif name == "Overlay":
        g.overlay = _step(OVERLAY_ALL, g.overlay, back)


def horizon_apply_preset(preset: str, s: Any) -> None:
    """Порт ``graphics::apply_preset`` (preset Performance..Ultra)."""
    table = {
        "performance": (8, 6, "false", 2, False, 0, 0, 0.5, False, 3),
        "balanced": (12, 8, "fast", 1, True, 1, 2, 0.75, True, 5),
        "quality": (16, 12, "true", 0, True, 2, 4, 1.0, True, 10),
        "ultra": (24, 12, "true", 0, True, 3, 4, 1.5, True, 10),
    }
    if preset not in table:
        return
    rd, sim, clouds, particles, shadows, blend, mipmaps, entity, leaves, weather_r = table[preset]
    s.render_distance = rd
    s.simulation_distance = sim
    s.clouds = clouds
    s.particles = particles
    s.entity_shadows = shadows
    s.biome_blend = blend
    s.mipmap_levels = mipmaps
    s.entity_distance = entity
    s.cutout_leaves = leaves
    s.weather_radius = weather_r
    s.graphics_preset = "custom"
    g = s.horizon
    g.preset = preset
    g.cave_culling = True
    g.animated_textures = True
    g.chunk_updates = 0
    g.upload_budget_kib = 0
    g.sky = True
    g.fog = True
    g.weather = True


# -- Opt (vanilla) ----------------------------------------------------------

def opt_switch(s: Any, name: str) -> Optional[bool]:
    if name == "Vsync":
        return s.vsync
    if name == "Fullscreen":
        return s.fullscreen
    if name == "ExclusiveFullscreen":
        return _fbool(s, "exclusiveFullscreen")
    if name == "SmoothLighting":
        return s.smooth_lighting
    if name == "EntityShadows":
        return s.entity_shadows
    if name == "Vignette":
        return s.vignette
    if name == "Autosave":
        return s.autosave_indicator
    if name == "CutoutLeaves":
        return s.cutout_leaves
    if name == "ImprovedTransparency":
        return s.improved_transparency
    return None


def opt_slider(s: Any, name: str) -> Optional[float]:
    if name == "RenderDistance":
        return _unit(float(s.render_distance), 2.0, float(RENDER_DISTANCE_MAX))
    if name == "SimulationDistance":
        return _unit(float(s.simulation_distance), 5.0, 32.0)
    if name == "Gamma":
        return float(s.gamma)
    if name == "MaxFps":
        return _unit(float(s.max_fps), 10.0, 260.0)
    if name == "CloudRange":
        return _unit(float(s.cloud_range), 2.0, 128.0)
    if name == "EntityDistance":
        return _unit(float(s.entity_distance), 0.5, 5.0)
    if name == "BiomeBlend":
        return _unit(float(s.biome_blend), 0.0, 7.0)
    if name == "Preset":
        return _unit(float(_preset_index(s.graphics_preset)), 0.0, 3.0)
    if name == "Mipmaps":
        return _unit(float(s.mipmap_levels), 0.0, 4.0)
    if name == "MaxAnisotropy":
        return _unit(float(_fint(s, "maxAnisotropyBit")), 1.0, 3.0)
    if name == "ExclusiveMode":
        modes = getattr(s, "video_modes", []) or []
        last = float(len(modes)) - 1.0
        if last < 0.0:
            return 0.0
        return _unit(float(s.video_mode_index()), -1.0, last)
    if name == "WeatherRadius":
        return _unit(float(s.weather_radius), 3.0, 10.0)
    if name == "ChunkFade":
        return _unit(float(s.chunk_fade), 0.0, 2.0)
    if name == "MenuBlur":
        return _unit(float(s.menu_blur), 0.0, 10.0)
    return None


def opt_slider_steps(name: str) -> Optional[int]:
    return {
        "RenderDistance": RENDER_DISTANCE_MAX - 2,
        "SimulationDistance": 27,
        "MaxFps": 25,
        "CloudRange": 126,
        "EntityDistance": 18,
        "BiomeBlend": 7,
        "Preset": 3,
        "Mipmaps": 4,
        "WeatherRadius": 7,
        "ChunkFade": 40,
        "MenuBlur": 10,
    }.get(name)


def opt_label(s: Any, name: str) -> str:
    c = _OPT_CAPTION.get(name, name)
    if name == "RenderDistance":
        return labelled(c, _tr("options.chunks", s.render_distance, default="%s chunks"))
    if name == "SimulationDistance":
        return labelled(c, _tr("options.chunks", s.simulation_distance,
                               default="%s chunks"))
    if name == "GuiScale":
        value = (_lang("options.guiScale.auto", "Auto") if s.gui_scale == 0
                 else str(s.gui_scale))
        return labelled(c, value)
    if name == "Gamma":
        v = int(s.gamma * 100.0)
        if v == 0:
            return labelled(c, _lang("options.gamma.min", "Moody"))
        if v == 50:
            return labelled(c, _lang("options.gamma.default", "Default"))
        if v == 100:
            return labelled(c, _lang("options.gamma.max", "Bright"))
        return labelled(c, v)
    if name == "MaxFps":
        if s.max_fps >= 260:
            return labelled(c, _lang("options.framerateLimit.max", "Unlimited"))
        return labelled(c, _tr("options.framerate", s.max_fps, default="%s fps"))
    if name == "CloudRange":
        return labelled(c, _tr("options.chunks", s.cloud_range, default="%s chunks"))
    if name == "EntityDistance":
        return _percent(c, s.entity_distance)
    if name == "BiomeBlend":
        return labelled(c, _lang("options.biomeBlendRadius.%d" % (s.biome_blend * 2 + 1),
                                 str(s.biome_blend * 2 + 1)))
    if name == "Preset":
        return labelled(c, _lang("options.graphics.%s" % s.graphics_preset,
                                 s.graphics_preset.title()))
    if name == "MaxAnisotropy":
        bit = _fint(s, "maxAnisotropyBit")
        if bit == 0:
            return labelled(c, _lang("options.off", "Off"))
        return labelled(c, _tr("options.multiplier", 1 << bit, default="%sx"))
    if name == "ExclusiveMode":
        modes = getattr(s, "video_modes", []) or []
        if not modes:
            return _lang("options.fullscreen.unavailable", "Fullscreen mode unavailable")
        return labelled(c, _lang("options.fullscreen.current", "Current"))
    if name == "Mipmaps":
        if s.mipmap_levels == 0:
            return labelled(c, _lang("options.off", "Off"))
        return labelled(c, s.mipmap_levels)
    if name == "WeatherRadius":
        return labelled(c, _tr("options.blocks", s.weather_radius, default="%s blocks"))
    if name == "ChunkFade":
        if s.chunk_fade <= 0.0:
            return _lang("options.chunkFade.none", "Instant")
        return _tr("options.chunkFade.seconds", "%.2f" % s.chunk_fade,
                   default="%s seconds")
    if name == "MenuBlur":
        if s.menu_blur == 0:
            return labelled(c, _lang("options.off", "Off"))
        return labelled(c, s.menu_blur)
    if name == "Vsync" or name == "Fullscreen" or name == "ExclusiveFullscreen" \
            or name == "SmoothLighting" or name == "EntityShadows" or name == "Vignette" \
            or name == "Autosave" or name == "CutoutLeaves" \
            or name == "ImprovedTransparency":
        return labelled(c, _on_off_opt(opt_switch(s, name)))
    if name == "Clouds":
        value = {"false": "options.off", "fast": "options.clouds.fast"}.get(
            s.clouds, "options.clouds.fancy")
        return labelled(c, _lang(value, "Fancy"))
    if name == "Particles":
        return labelled(c, _lang(PARTICLE_LABELS[min(s.particles, 2)], "All"))
    if name == "TextureFiltering":
        return labelled(c, _lang(VIDEO_FILTERING[min(max(_fint(s, "textureFiltering"), 0), 2)],
                                 "None"))
    if name == "AttackIndicator":
        return labelled(c, _lang(ATTACK_LABELS[min(s.attack_indicator, 2)], "Off"))
    if name == "InactivityFps":
        key = ("options.inactivityFpsLimit.minimized" if s.inactivity_fps_limit == "minimized"
               else "options.inactivityFpsLimit.afk")
        return labelled(c, _lang(key, "AFK"))
    if name == "ChunkBuilder":
        return labelled(c, _lang(CHUNK_BUILDER_LABELS[min(s.prioritize_chunk_updates, 2)],
                                 "None"))
    return ""


def _opt_affects_preset(name: str) -> bool:
    return name in _OPT_AFFECTS_PRESET


def opt_set_slider(s: Any, name: str, v: float) -> None:
    v = max(0.0, min(1.0, v))

    def step(lo: float, hi: float) -> int:
        return int(round(lo + v * (hi - lo)))

    if name == "RenderDistance":
        s.render_distance = step(2.0, float(RENDER_DISTANCE_MAX))
    elif name == "SimulationDistance":
        s.simulation_distance = step(5.0, 32.0)
    elif name == "Gamma":
        s.gamma = v
    elif name == "MaxFps":
        s.max_fps = step(1.0, 26.0) * 10
    elif name == "CloudRange":
        s.cloud_range = step(2.0, 128.0)
    elif name == "EntityDistance":
        s.entity_distance = step(2.0, 20.0) / 4.0
    elif name == "BiomeBlend":
        s.biome_blend = step(0.0, 7.0)
    elif name == "Preset":
        before = _preset_index(s.graphics_preset)
        s.graphics_preset = VANILLA_PRESETS[step(0.0, 3.0)]
        if _preset_index(s.graphics_preset) != before:
            vanilla_apply_preset(s)
    elif name == "Mipmaps":
        s.mipmap_levels = step(0.0, 4.0)
    elif name == "MaxAnisotropy":
        _fset(s, "maxAnisotropyBit", step(1.0, 3.0))
    elif name == "ExclusiveMode":
        modes = getattr(s, "video_modes", []) or []
        if not modes:
            return
        index = step(-1.0, float(len(modes) - 1))
        if 0 <= index < len(modes):
            _fset(s, "fullscreenResolution", modes[index])
    elif name == "WeatherRadius":
        s.weather_radius = step(3.0, 10.0)
    elif name == "ChunkFade":
        s.chunk_fade = step(0.0, 40.0) / 20.0
    elif name == "MenuBlur":
        s.menu_blur = step(0.0, 10.0)
    if _opt_affects_preset(name):
        s.graphics_preset = "custom"


def opt_cycle(s: Any, name: str, back: bool, framebuffer: tuple[int, int]) -> None:
    if name == "GuiScale":
        from quadrix.render.menu import calculate_scale
        maximum = calculate_scale(framebuffer, 0, False)
        value = min(int(s.gui_scale), maximum)
        if back:
            s.gui_scale = maximum if value == 0 else value - 1
        else:
            s.gui_scale = 0 if value == maximum else value + 1
    elif name == "Fullscreen":
        s.fullscreen = not s.fullscreen
    elif name == "ExclusiveFullscreen":
        _fset(s, "exclusiveFullscreen", not _fbool(s, "exclusiveFullscreen"))
    elif name == "Vsync":
        s.vsync = not s.vsync
    elif name == "Clouds":
        order = ["false", "fast", "true"]
        i = order.index(s.clouds) if s.clouds in order else 2
        s.clouds = order[_next(i, 3, back)]
    elif name == "Particles":
        s.particles = _next(s.particles, 3, back)
    elif name == "SmoothLighting":
        s.smooth_lighting = not s.smooth_lighting
    elif name == "EntityShadows":
        s.entity_shadows = not s.entity_shadows
    elif name == "Vignette":
        s.vignette = not s.vignette
    elif name == "Autosave":
        s.autosave_indicator = not s.autosave_indicator
    elif name == "CutoutLeaves":
        s.cutout_leaves = not s.cutout_leaves
    elif name == "ImprovedTransparency":
        s.improved_transparency = not s.improved_transparency
    elif name == "AttackIndicator":
        s.attack_indicator = _next(s.attack_indicator, 3, back)
    elif name == "InactivityFps":
        s.inactivity_fps_limit = ("minimized" if s.inactivity_fps_limit == "afk" else "afk")
    elif name == "ChunkBuilder":
        s.prioritize_chunk_updates = _next(s.prioritize_chunk_updates, 3, back)
    elif name == "TextureFiltering":
        n = _next(min(max(_fint(s, "textureFiltering"), 0), 2), 3, back)
        _fset(s, "textureFiltering", n)
    if _opt_affects_preset(name):
        s.graphics_preset = "custom"


def vanilla_apply_preset(s: Any) -> None:
    """Порт ``options_ui::apply_preset`` (Fast/Fancy/Fabulous)."""
    fabulous = s.graphics_preset == "fabulous"
    if s.graphics_preset == "fast":
        s.biome_blend = 1
        s.render_distance = 8
        s.prioritize_chunk_updates = 0
        s.simulation_distance = 6
        s.smooth_lighting = False
        s.clouds = "fast"
        s.particles = 1
        s.mipmap_levels = 2
        s.entity_shadows = False
        s.entity_distance = 0.75
        s.menu_blur = 2
        s.cloud_range = 32
        s.cutout_leaves = False
        s.improved_transparency = False
        s.weather_radius = 5
        _fset(s, "maxAnisotropyBit", 0)
        _fset(s, "textureFiltering", 1)
    elif s.graphics_preset in ("fancy", "fabulous"):
        s.biome_blend = 2
        s.render_distance = 32 if fabulous else 16
        s.prioritize_chunk_updates = 1
        s.simulation_distance = 12
        s.smooth_lighting = True
        s.clouds = "true"
        s.particles = 0
        s.mipmap_levels = 4
        s.entity_shadows = True
        s.entity_distance = 1.25 if fabulous else 1.0
        s.menu_blur = 5
        s.cloud_range = 128 if fabulous else 64
        s.cutout_leaves = True
        s.improved_transparency = fabulous
        s.weather_radius = 10
        _fset(s, "maxAnisotropyBit", 2 if fabulous else 1)
        _fset(s, "textureFiltering", 2 if fabulous else 1)


# -- Item (строка целиком) --------------------------------------------------

def _extra_key(name: str) -> str:
    """``Fullbright`` → ``fullbright`` (поля ``Extras`` — snake_case)."""
    out = []
    for i, c in enumerate(name):
        if c.isupper() and i:
            out.append("_")
        out.append(c.lower())
    return "".join(out)


def item_switch(s: Any, kind: str, name: str) -> Optional[bool]:
    if kind == "H":
        return h_switch(s, name)
    if kind == "Opt":
        return opt_switch(s, name)
    if kind == "Extra":
        return s.extras.switch(_extra_key(name))
    return None


def item_slider(s: Any, kind: str, name: str) -> Optional[float]:
    if kind == "H":
        return h_slider(s, name)
    if kind == "Opt":
        return opt_slider(s, name)
    return None


def item_slider_steps(kind: str, name: str) -> Optional[int]:
    if kind == "H":
        return h_slider_steps(name)
    if kind == "Opt":
        return opt_slider_steps(name)
    return None


def item_label(s: Any, kind: str, name: str) -> str:
    if kind == "H":
        return h_label(s, name)
    if kind == "Opt":
        if name == "RenderDistance" and s.horizon.lod_distance > 0:
            return labelled("Full Detail Distance",
                            _tr("%s chunks", s.render_distance, default="%s chunks"))
        return opt_label(s, name)
    if kind == "Extra":
        return labelled(extra_caption_text(name), s.extras.value(_extra_key(name)))
    return ""


def item_set_slider(s: Any, kind: str, name: str, v: float) -> None:
    if item_blocked(s, kind, name) is not None:
        return
    if kind == "H":
        h_set_slider(s, name, v)
    elif kind == "Opt":
        opt_set_slider(s, name, v)
    _touched(s, kind, name)


def item_cycle(s: Any, kind: str, name: str, back: bool, framebuffer: tuple[int, int]) -> None:
    if kind == "H":
        h_cycle(s, name, back)
    elif kind == "Opt":
        opt_cycle(s, name, back, framebuffer)
    elif kind == "Extra":
        s.extras.toggle(_extra_key(name))
    _touched(s, kind, name)


def _touched(s: Any, kind: str, name: str) -> None:
    if kind == "H" and name not in _H_PRESETLESS:
        s.horizon.preset = "custom"
    elif kind == "Opt" and name not in _OPT_PRESETLESS:
        s.horizon.preset = "custom"


def item_steps(s: Any, kind: str, name: str) -> bool:
    return (
        item_switch(s, kind, name) is None
        and item_slider(s, kind, name) is None
        and not (kind == "H" and name in ("HdrKey", "HdrCalibrate", "ShaderPacks"))
    )


def _gpu_culling_reason() -> Optional[str]:
    return None if GPU_CULLING_OFFERED else "Your GPU or graphics API doesn't support it."


def item_blocked(s: Any, kind: str, name: str) -> Optional[str]:
    """Порт ``graphics_ui::Item::blocked`` (почему нельзя сейчас)."""
    if kind == "Opt" and name == "ChunkBuilder":
        return "This feature is not yet available in QuadRix."
    if kind != "H":
        return None
    hdr_rows = ("Hdr", "HdrCalibrate", "HdrBlackLevel", "HdrPeak", "HdrPaperWhite",
                "HdrUiBrightness", "HdrLighting", "HdrSmoothGradients")
    if name in hdr_rows and not HDR_OFFERED:
        return "Your display or system doesn't offer HDR output."
    if name == "HdrSmoothGradients" and not SMOOTH_GRADIENTS_OFFERED:
        return "Your GPU or graphics API doesn't support it."
    if name in ("HdrCalibrate", "HdrBlackLevel", "HdrPeak", "HdrPaperWhite",
                "HdrUiBrightness", "HdrLighting", "HdrSmoothGradients") and not s.horizon.hdr:
        return "Turn HDR on to use it."
    if name == "TranslucentBatching" and not TRANSLUCENT_BATCHING_OFFERED:
        return "Your GPU or graphics API doesn't support it."
    if name == "EntityCullingPrecheck" and s.horizon.entity_culling != "async":
        return "Only applies to asynchronous entity culling."
    if name == "GpuCulling":
        return _gpu_culling_reason()
    return None
