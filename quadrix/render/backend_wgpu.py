"""wgpu-py бэкенд QuadRix — заготовка.

# FALLBACK: wgpu backend pending — wgpu-py отстаёт и в прототипе требовал
# приватного ``_wgpu_context.present()`` (см. proto_wgpu.py). Публичного
# аналога в wgpu 0.33 нет, поэтому реализация отложена. Основной бэкенд —
# moderngl (см. backend_moderngl.py).

Заготовка ниже показывает, как будет устроен бэкенд, когда wgpu-py
получит стабильный present. Код намеренно закомментирован: он опирается
на приватный API и не должен попасть в рабочий путь.

Прототип дал 649 FPS на чанке через GlfwRenderCanvas, то есть GPU-путь
рабочий — мешает только отсутствие публичного present().
"""

from __future__ import annotations

from typing import Any

_PENDING = "wgpu backend pending, use moderngl"


class WgpuBackend:
    """Заготовка wgpu-бэкенда. Все методы — NotImplementedError.

    Смысл класса: ``create_backend(BackendType.WGPU)`` может вернуть его
    (если пакет ``wgpu`` установлен), чтобы код-потребитель не падал на
    импорте и мог показать понятное сообщение.
    """

    def __init__(
        self,
        width: int = 800,
        height: int = 600,
        title: str = "QuadRix",
        vsync: bool = False,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.title = title
        self.vsync = bool(vsync)
        self.clear_color: tuple[float, float, float, float] = (0.10, 0.12, 0.16, 1.0)
        self.device: Any = None
        self.context: Any = None

    def create_context(self) -> Any:
        raise NotImplementedError(_PENDING)

    def create_pipeline(self, vert_src: str, frag_src: str) -> Any:
        raise NotImplementedError(_PENDING)

    def draw(self, vbo: Any, program: Any, texture: Any = None, **kwargs: Any) -> None:
        raise NotImplementedError(_PENDING)

    def present(self) -> None:
        raise NotImplementedError(_PENDING)

    def close(self) -> None:
        raise NotImplementedError(_PENDING)


# ---------------------------------------------------------------------------
# TODO-заготовка из proto_wgpu.py (не активна).
# # FALLBACK: wgpu backend pending
#
# Когда wgpu-py добавит публичный present, включить примерно так:
#
#     from rendercanvas.glfw import GlfwRenderCanvas
#     canvas = GlfwRenderCanvas(size=(W, H), title=title, vsync=False)
#     canvas.set_update_mode("manual")
#     adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance",
#                                            canvas=canvas)
#     device = adapter.request_device_sync()
#     ctx = canvas.get_wgpu_context()
#     fmt = ctx.get_preferred_format(adapter)
#     ctx.configure(device=device, format=fmt)
#     ...
#     # в конце кадра:
#     ctx.present()   # публичный метод появится в новых версиях
#
# Вершинный формат (как в moderngl): pos(3) + normal(3) + uv(2).
# WGSL из прототипа использует @group(0) @binding(0..2): mvp, texture, sampler
# и тот же directional light, что terrain.frag.
# ---------------------------------------------------------------------------
