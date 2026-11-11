"""Панорама главного меню QuadRix (порт Horizon ``gfx/panorama.rs``).

Кубмап из шести ``panorama_*.png`` + медленное вращение. В Horizon куб
живёт на GPU только пока открыт титульный экран; мы держим его по тому же
принципу — ``Faces`` (данные) отделены от ``Panorama`` (GPU-ресурсы).

Порт (Rust → Python):
    * ``FACE_ORDER = [1, 3, 5, 4, 0, 2]`` — CubeMapTexture.SUFFIXES
      (нативный порядок +X,-X,+Y,-Y,+Z,-Z).
    * ``Faces`` — шесть лиц, каждое с перевёрнутыми по вертикали строками
      (``CubeMapTexture`` грузит с ``flipY=true``); fallback — серый
      ``[96, 110, 111, 255]``.
    * ``projection`` — ``perspective_rh(85°, aspect, 0.05, 10) *
      rotX(PI) * rotX(pitch) * rotY(yaw)``.
    * ``Rotation`` — ``yaw = (yaw - max(dt,0) * 2 * speed) % 360``.
    * pitch титульного кадра = 10.0 (``game.rs``), speed =
      ``panoramaScrollSpeed`` (по умолчанию 1.0).

Данные: ``.local/horizon-client/26.3/assets/minecraft/textures/gui/title/background``.
"""

from __future__ import annotations

import functools
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from quadrix.render.ui import load_png_rgba

PACK_ROOT = Path(".local/horizon-client/26.3")
BACKGROUND = "assets/minecraft/textures/gui/title/background"

#: CubeMapTexture.SUFFIXES — нативный порядок (gfx/panorama.rs L11).
FACE_ORDER: tuple[int, ...] = (1, 3, 5, 4, 0, 2)

#: Цвет плейсхолдера, если панорамы нет (gfx/panorama.rs L42).
FALLBACK_COLOUR = (96, 110, 111, 255)

#: Угол наклона титульного кадра (game.rs: ``pitch: 10.0``).
TITLE_PITCH = 10.0

#: Вертикальный FOV панорамы (gfx/panorama.rs L175).
PANORAMA_FOV = 85.0


def _log(message: str) -> None:
    print("[QuadRix] panorama: " + message)


def perspective_rh(fovy_rad: float, aspect: float, near: float, far: float) -> np.ndarray:
    """``glam::Mat4::perspective_rh`` (правосторонняя, глубина 0..1)."""
    f = 1.0 / np.tan(fovy_rad / 2.0)
    z = near - far
    m = np.zeros((4, 4), dtype=np.float64)
    m[0, 0] = 1.0 / (aspect * f) if aspect else 0.0
    m[1, 1] = f
    m[2, 2] = far / z
    m[2, 3] = near * far / z
    m[3, 2] = -1.0
    return m


def rotation_x(angle_rad: float) -> np.ndarray:
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.0, c, -s, 0.0], [0.0, s, c, 0.0], [0.0, 0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def rotation_y(angle_rad: float) -> np.ndarray:
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array(
        [[c, 0.0, s, 0.0], [0.0, 1.0, 0.0, 0.0], [-s, 0.0, c, 0.0], [0.0, 0.0, 0.0, 1.0]],
        dtype=np.float64,
    )


def projection(width: int, height: int, yaw: float, pitch: float) -> np.ndarray:
    """Проекция кубмапа панорамы (gfx/panorama.rs L172)."""
    aspect = float(width) / float(max(1, height))
    return (
        perspective_rh(np.radians(PANORAMA_FOV), aspect, 0.05, 10.0)
        @ rotation_x(np.pi)
        @ rotation_x(np.radians(pitch))
        @ rotation_y(np.radians(yaw))
    )


@dataclass
class Faces:
    """Шесть лиц кубмапа: ``(6, size, size, 4)`` uint8. См. ``gfx/panorama.rs``."""

    size: int
    texels: np.ndarray  # (6, size, size, 4) uint8
    loaded: bool = True

    @classmethod
    def load(cls, root: Path | str = PACK_ROOT) -> "Faces":
        """Загрузить лица; при неполном/несовпадающем кубе — серый placeholder."""
        try:
            return cls._try_load(Path(root))
        except Exception as exc:  # noqa: BLE001 - панорама не критична
            _log(f"нет панорамы ({exc}); плейсхолдер {FALLBACK_COLOUR}")
            return cls.colour(FALLBACK_COLOUR)

    @classmethod
    def _try_load(cls, root: Path) -> "Faces":
        faces_dir = root / BACKGROUND
        layers: list[np.ndarray] = []
        size = 0
        for face in FACE_ORDER:
            path = faces_dir / f"panorama_{face}.png"
            image = load_png_rgba(path)
            h, w = image.shape[:2]
            if w != h or (size != 0 and w != size):
                raise ValueError(f"{path}: panorama faces must be equally sized squares")
            size = w
            # CubeMapTexture копирует с flipY=true — строки в обратном порядке.
            layers.append(np.flipud(image))
        return cls(size=size, texels=np.stack(layers, axis=0), loaded=True)

    @classmethod
    def colour(cls, colour: tuple[int, int, int, int]) -> "Faces":
        """Одноцветный куб (1 тексель на лицо)."""
        texel = np.array(colour, dtype=np.uint8).reshape(1, 1, 1, 4).repeat(6, axis=0)
        return cls(size=1, texels=texel, loaded=False)

    def bytes(self) -> bytes:
        """6 лиц подряд, как ждёт ``glTexImage2D`` (face-major)."""
        return np.ascontiguousarray(self.texels, dtype=np.uint8).tobytes()


@dataclass
class Rotation:
    """``gfx/panorama.rs::Rotation`` — накопленный поворот (не прыгает)."""

    last: float = 0.0
    yaw: float = 0.0

    def update(self, now: float, speed: float) -> float:
        # Rust `%` на f32 — остаток со знаком делимого (fmod), не Python `%`.
        self.yaw = math.fmod(self.yaw - max(0.0, now - self.last) * 2.0 * speed, 360.0)
        self.last = now
        return self.yaw


@dataclass
class Panorama:
    """GPU-часть: программа + кубмап-текстура. Создаётся/рисуется бэкендом."""

    faces: Faces
    program: object = None
    cube: object = None

    def prepare(self, backend: object) -> None:
        """Скомпилировать шейдер и залить куб (идемпотентно)."""
        if self.program is None:
            create = getattr(backend, "create_pipeline", None)
            if callable(create):
                from quadrix.render.backend_moderngl import load_shader

                self.program = create(
                    load_shader("panorama.vert"), load_shader("panorama.frag")
                )
        if self.cube is None:
            create_cube = getattr(backend, "create_cube_texture", None)
            if callable(create_cube):
                self.cube = create_cube(self.faces)

    def draw(self, backend: object, width: int, height: int, yaw: float) -> bool:
        """Нарисовать куб. ``False``, если GPU-части нет."""
        if self.program is None or self.cube is None:
            return False
        draw = getattr(backend, "draw_panorama", None)
        if not callable(draw):
            return False
        proj = projection(width, height, yaw, TITLE_PITCH)
        draw(self.cube, self.program, proj)
        return True

    def release(self) -> None:
        """Отдать VRAM куба (порт ``Panorama::release``)."""
        self.cube = None


@functools.lru_cache(maxsize=4)
def _load_cached(root: str) -> Faces:
    """Загрузка лиц панорамы с кэшем (6x1024x1024 PNG недёшевы)."""
    return Faces.load(root)


def load_panorama(root: Path | str = PACK_ROOT) -> Faces:
    """Загрузить лица панорамы (``Faces::load``)."""
    return _load_cached(str(root))


__all__ = [
    "BACKGROUND",
    "FACE_ORDER",
    "FALLBACK_COLOUR",
    "Faces",
    "PANORAMA_FOV",
    "PACK_ROOT",
    "Panorama",
    "Rotation",
    "TITLE_PITCH",
    "load_panorama",
    "perspective_rh",
    "projection",
    "rotation_x",
    "rotation_y",
]
