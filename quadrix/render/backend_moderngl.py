"""moderngl (OpenGL) бэкенд QuadRix — основной.

Эталон — ``proto_moderngl.py`` (стабилен, 1631 FPS на чанке).
Используем только публичный API moderngl/glfw, никаких приватных полей.

GLSL 330 core — moderngl создаёт OpenGL 3.3 core-контекст.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np


class ModernglBackend:
    """Рендер-бэкенд на moderngl + glfw.

    Конструктор ничего не открывает: окно создаётся в ``create_context()``.
    Это позволяет тестам работать без дисплея (CI).
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
        # цвет очистки как в прототипе: тёмно-сине-серый
        self.clear_color: tuple[float, float, float, float] = (0.10, 0.12, 0.16, 1.0)

        self.window: Any = None
        self.ctx: Any = None
        self._glfw: Any = None
        self._closed = False

    # ------------------------------------------------------------------
    # контекст / окно
    # ------------------------------------------------------------------

    def create_context(self) -> Any:
        """Создать glfw-окно и moderngl-контекст.

        Возвращает ``moderngl.Context``. При отсутствии дисплея/драйвера
        кидает ``RuntimeError`` с понятным сообщением.
        """
        if self.ctx is not None:
            return self.ctx

        try:
            import glfw
            import moderngl
        except ImportError as err:  # pragma: no cover - зависимости стоят
            raise RuntimeError(
                "[QuadRix] moderngl backend требует пакеты 'moderngl' и 'glfw'"
            ) from err

        self._glfw = glfw

        if not glfw.init():
            raise RuntimeError("[QuadRix] glfw.init() failed: нет дисплея/драйвера")

        try:
            glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
            glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
            glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
            glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)

            window = glfw.create_window(self.width, self.height, self.title, None, None)
            if not window:
                raise RuntimeError(
                    "[QuadRix] glfw.create_window() failed: OpenGL 3.3 core недоступен"
                )
            self.window = window
            glfw.make_context_current(window)
            # vsync off по умолчанию — измеряем честный throughput
            glfw.swap_interval(1 if self.vsync else 0)

            self.ctx = moderngl.create_context()
            # стандартное состояние сцены: глубина + отсечение задних граней
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.ctx.enable(moderngl.CULL_FACE)
        except Exception:
            # не оставляем висящее окно/инициализированный glfw
            if self.window is not None:
                glfw.destroy_window(self.window)
                self.window = None
            glfw.terminate()
            self._glfw = None
            self.ctx = None
            raise

        info = self.ctx.info
        print(
            f"[QuadRix] backend=moderngl GL={info['GL_VERSION']!r} "
            f"vendor={info['GL_VENDOR']!r}"
        )
        return self.ctx

    # ------------------------------------------------------------------
    # пайплайн / отрисовка
    # ------------------------------------------------------------------

    def create_pipeline(self, vert_src: str, frag_src: str) -> Any:
        """Скомпилировать шейдерную программу (GLSL 330 core)."""
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        return self.ctx.program(vertex_shader=vert_src, fragment_shader=frag_src)

    def draw(
        self,
        vbo: Any,
        program: Any,
        texture: Any = None,
        *,
        vertex_format: str = "3f 3f 2f",
        attributes: Sequence[str] = ("in_pos", "in_normal", "in_uv"),
        count: Optional[int] = None,
        mvp: Optional[np.ndarray] = None,
    ) -> None:
        """Один draw call.

        ``vbo`` — ``moderngl.Buffer`` (или numpy-массив, тогда буфер
        создаётся на месте и освобождается после кадра).
        ``texture`` — ``moderngl.Texture``; если задана, биндится в unit 0.
        ``count`` — число вершин (по умолчанию весь буфер).
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")

        owns_buffer = False
        buffer = vbo
        if isinstance(vbo, np.ndarray):
            buffer = self.ctx.buffer(np.ascontiguousarray(vbo).tobytes())
            owns_buffer = True

        if count is None:
            count = buffer.size // (8 * 4)  # stride: pos(3) + normal(3) + uv(2)

        if mvp is not None:
            # GLSL ждёт column-major, numpy даёт row-major -> транспонируем
            program["mvp"].write(np.asarray(mvp, dtype=np.float32).T.tobytes())

        if texture is not None:
            texture.use(location=0)
            if "texture0" in program:
                program["texture0"] = 0

        vao = self.ctx.vertex_array(
            program, [(buffer, vertex_format, *attributes)]
        )
        try:
            self.ctx.clear(*self.clear_color)
            vao.render(self._triangles(), vertices=count)
        finally:
            vao.release()
            if owns_buffer:
                buffer.release()

    @staticmethod
    def _triangles() -> int:
        import moderngl

        return moderngl.TRIANGLES

    # ------------------------------------------------------------------
    # кадр / закрытие
    # ------------------------------------------------------------------

    def read_screen(self) -> np.ndarray:
        """Прочитать экранный буфер (RGBA, верхняя строка — сверху).

        ВАЖНО: вызывать ДО ``present()`` — после swap содержимое
        back buffer не определено.
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        self.ctx.finish()
        # размер берём у framebuffer, а не из конструктора: при DPI-масштабе
        # окно и кадровый буфер могут отличаться
        fb_width, fb_height = self.ctx.screen.size
        data = self.ctx.screen.read(components=4, alignment=1)
        return np.frombuffer(data, dtype=np.uint8).reshape(fb_height, fb_width, 4)

    def present(self) -> None:
        """Показать кадр. Скриншот (если нужен) — строго до этого вызова."""
        if self._glfw is None or self.window is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        self._glfw.swap_buffers(self.window)

    def poll_events(self) -> None:
        """Обработать события окна (вызывать раз в кадр)."""
        if self._glfw is not None:
            self._glfw.poll_events()

    def should_close(self) -> bool:
        """``True``, если пользователь закрыл окно или контекста нет."""
        if self._glfw is None or self.window is None:
            return True
        return bool(self._glfw.window_should_close(self.window))

    def close(self) -> None:
        """Закрыть окно и завершить glfw. Повторный вызов безопасен."""
        if self._closed:
            return
        self._closed = True

        if self.ctx is not None:
            try:
                self.ctx.release()
            except Exception:  # pragma: no cover - контекст мог умереть сам
                pass
            self.ctx = None

        if self._glfw is not None:
            if self.window is not None:
                try:
                    self._glfw.destroy_window(self.window)
                except Exception:  # pragma: no cover
                    pass
            self.window = None
            try:
                self._glfw.terminate()
            except Exception:  # pragma: no cover
                pass
            self._glfw = None


# ---------------------------------------------------------------------------
# Загрузка шейдеров из quadrix/render/shaders
# ---------------------------------------------------------------------------

def load_shader(name: str) -> str:
    """Прочитать GLSL-файл из ``quadrix/render/shaders`` по имени."""
    from pathlib import Path

    path = Path(__file__).with_name("shaders") / name
    return path.read_text(encoding="utf-8")
