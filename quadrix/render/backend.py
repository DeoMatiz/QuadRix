"""Абстракция рендер-бэкенда QuadRix.

Фаза 0 (render-фундамент): единый интерфейс, чтобы остальной код
(мешинг, сцена, позже HUD/GUI) не зависел от конкретного GPU API.

Основной бэкенд — moderngl (OpenGL 3.3+), опциональный — wgpu-py.
Прототипы показали: GPU держит и то, и другое, узкое место — CPU-мешинг,
поэтому moderngl выбран основным (проще и стабильнее).

Порт Horizon: здесь пока нет прямого соответствия одному .rs-файлу,
это инфраструктура QuadRix (см. AGENTS.md, «Full Port»).
"""

from __future__ import annotations

import importlib.util
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class BackendType(Enum):
    """Доступные реализации рендер-бэкенда."""

    MODERNGL = "moderngl"
    WGPU = "wgpu"


@runtime_checkable
class RenderBackend(Protocol):
    """Контракт рендер-бэкенда.

    Жизненный цикл::

        backend = create_backend(BackendType.MODERNGL, 800, 600, "QuadRix")
        backend.create_context()          # окно + GPU-контекст
        program = backend.create_pipeline(vert, frag)
        backend.draw(vbo, program, texture)
        backend.present()                 # показать кадр
        backend.close()

    ``create_context`` отделён от конструктора намеренно: тесты могут
    создавать бэкенд без реального окна (в CI дисплея нет).
    """

    width: int
    height: int
    title: str

    def create_context(self) -> Any:
        """Создать окно и GPU-контекст. Возвращает нативный контекст."""
        ...

    def create_pipeline(self, vert_src: str, frag_src: str) -> Any:
        """Скомпилировать шейдерную программу из GLSL."""
        ...

    def draw(self, vbo: Any, program: Any, texture: Any = None, **kwargs: Any) -> None:
        """Один draw call."""
        ...

    def present(self) -> None:
        """Показать кадр (swap buffers)."""
        ...

    def close(self) -> None:
        """Освободить окно/контекст."""
        ...


def create_backend(
    backend_type: BackendType,
    width: int,
    height: int,
    title: str,
) -> RenderBackend:
    """Фабрика бэкендов.

    Окно не создаётся — только объект-конфигурация. Для реального
    рендера вызовите ``create_context()``.

    WGPU: если ``wgpu`` не установлен — ``RuntimeError``. Если установлен,
    возвращается заготовка ``WgpuBackend`` (её методы пока кидают
    ``NotImplementedError``, см. ``backend_wgpu.py``).
    """
    if backend_type is BackendType.MODERNGL:
        from quadrix.render.backend_moderngl import ModernglBackend

        return ModernglBackend(width=width, height=height, title=title)

    if backend_type is BackendType.WGPU:
        if importlib.util.find_spec("wgpu") is None:
            raise RuntimeError(
                "[QuadRix] wgpu backend недоступен: пакет 'wgpu' не установлен. "
                "Установите 'wgpu' или используйте BackendType.MODERNGL."
            )
        from quadrix.render.backend_wgpu import WgpuBackend

        return WgpuBackend(width=width, height=height, title=title)

    raise ValueError(f"[QuadRix] неизвестный backend_type: {backend_type!r}")
