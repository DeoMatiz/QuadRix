"""moderngl (OpenGL) бэкенд QuadRix — основной.

Эталон — ``proto_moderngl.py`` (стабилен, 1631 FPS на чанке).
Используем только публичный API moderngl/glfw, никаких приватных полей.

GLSL 330 core — moderngl создаёт OpenGL 3.3 core-контекст.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

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

        #: Обработчик UI-событий ``handler(kind, *args)`` — назначает ``App``.
        self.event_handler: Optional[Callable[..., None]] = None
        #: Последняя позиция курсора в оконных координатах (обновляет glfw).
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        #: Пропустить первый сдвиг после захвата/смены режима курсора.
        self._ignore_next_cursor: bool = True
        #: Курсор захвачен (игра): glfw держит его невидимым и по центру.
        self._mouse_grabbed: bool = False
        #: glfw key-code -> строковое имя, понятное ``ScreenStack.handle_key``.
        self._key_names: dict[int, str] = {}
        #: glfw key-code -> ванильное имя (``key.keyboard.w``) для InputState.
        self._key_vanilla: dict[int, str] = {}

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

            # Обратные вызовы ввода: без них glfw только опрашивается, а
            # клики/клавиши не доходят до ``App.handle_event``.
            self._key_names = {
                glfw.KEY_ESCAPE: "escape",
                glfw.KEY_E: "e",
                glfw.KEY_ENTER: "enter",
                glfw.KEY_KP_ENTER: "enter",
                glfw.KEY_BACKSPACE: "backspace",
                glfw.KEY_DELETE: "delete",
                glfw.KEY_LEFT: "left",
                glfw.KEY_RIGHT: "right",
                glfw.KEY_UP: "up",
                glfw.KEY_DOWN: "down",
                glfw.KEY_HOME: "home",
                glfw.KEY_END: "end",
                glfw.KEY_TAB: "tab",
            }
            # Цифры 1..9 выбирают слот hotbar (``Inventory.setSelected``).
            for _digit in range(1, 10):
                _code = glfw.__dict__.get(f"KEY_{_digit}")
                if _code is not None:
                    self._key_names[_code] = str(_digit)
            glfw.set_cursor_pos_callback(window, self._on_cursor)
            glfw.set_mouse_button_callback(window, self._on_mouse_button)
            glfw.set_scroll_callback(window, self._on_scroll)
            glfw.set_key_callback(window, self._on_key)
            glfw.set_char_callback(window, self._on_char)
            glfw.set_framebuffer_size_callback(window, self._on_framebuffer_size)
            self._key_vanilla = _build_vanilla_keys(glfw)
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

    def create_texture(self, image: Any) -> Any:
        """Загрузить RGBA-картинку (numpy ``HxWx4`` uint8) в ``moderngl.Texture``.

        Используется для атласа шрифта (``Font.atlas_image``).  Батч UI
        ожидает именно ``moderngl.Texture`` (``Batch.flush`` -> ``draw`` ->
        ``texture.use(location=0)``).
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        import moderngl

        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise RuntimeError(
                f"[QuadRix] create_texture ждёт HxWx4, получено {arr.shape}"
            )
        height, width = int(arr.shape[0]), int(arr.shape[1])
        pixels = np.ascontiguousarray(arr, dtype=np.uint8).tobytes()
        texture = self.ctx.texture((width, height), 4, pixels)
        # UI рисуется без сглаживания — шрифт должен оставаться резким.
        texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
        return texture

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
        depth_test: bool = True,
        cull_face: bool = True,
        blend: bool = False,
    ) -> None:
        """Один draw call.

        ``vbo`` — ``moderngl.Buffer`` (или numpy-массив, тогда буфер
        создаётся на месте и освобождается после кадра).
        ``texture`` — ``moderngl.Texture``; если задана, биндится в unit 0.
        ``count`` — число вершин (по умолчанию весь буфер).
        ``depth_test``/``cull_face``/``blend`` — состояние GL для вызова:
        2D-UI после Y-флипа проекции обходит по часовой стрелке и требует
        ``cull_face=False`` и ``blend=True``, иначе всё отсекается/без альфы.
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        if program is None:
            # Без программы moderngl падает глубже с AttributeError
            # ('NoneType' has no attribute '_attribute_locations'); сообщаем
            # понятно, что App.setup() не создал UI-пайплайн.
            raise RuntimeError(
                "[QuadRix] program not initialized, call setup() first"
            )

        import moderngl

        # Каждый draw выставляет состояние явно, чтобы результат не зависел
        # от предыдущего вызова (UI-батч переключает на 2D-режим).
        if cull_face:
            self.ctx.enable(moderngl.CULL_FACE)
        else:
            self.ctx.disable(moderngl.CULL_FACE)
        if depth_test:
            self.ctx.enable(moderngl.DEPTH_TEST)
        else:
            self.ctx.disable(moderngl.DEPTH_TEST)
        if blend:
            self.ctx.enable(moderngl.BLEND)
            self.ctx.blend_func = (
                moderngl.SRC_ALPHA,
                moderngl.ONE_MINUS_SRC_ALPHA,
            )
        else:
            self.ctx.disable(moderngl.BLEND)

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
            # Очистка кадра — отдельным вызовом ``clear()`` (один раз за
            # кадр), иначе каждый draw стирает панораму/предыдущий слой.
            vao.render(self._triangles(), vertices=count)
        finally:
            vao.release()
            if owns_buffer:
                buffer.release()

    def clear(self) -> None:
        """Очистить кадр цветом ``clear_color`` (вызывается один раз за кадр)."""
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        self.ctx.clear(*self.clear_color)

    def resize(self, width: int, height: int) -> None:
        """Обновить размер кадрового буфера и GL viewport (resize окна)."""
        self.width = int(width)
        self.height = int(height)
        if self.ctx is not None:
            self.ctx.viewport = (0, 0, int(width), int(height))

    # ------------------------------------------------------------------
    # панорама главного меню (порт gfx/panorama.rs)
    # ------------------------------------------------------------------

    def create_cube_texture(self, faces: Any) -> Any:
        """Залить кубмап-текстуру из ``Faces`` (6 лиц, face-major).

        Порт ``CubeMapTexture``: ``glTexImage2D``/``texture_cube`` ждёт шесть
        квадратных лиц подряд, каждое с перевёрнутыми по Y строками (это уже
        сделано в ``Faces``). Линейная фильтрация (``blur = true``).
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        import moderngl

        size = int(faces.size)
        cube = self.ctx.texture_cube((size, size), 4, faces.bytes())
        cube.filter = (moderngl.LINEAR, moderngl.LINEAR)
        return cube

    def draw_panorama(
        self, cube: Any, program: Any, projection: np.ndarray
    ) -> None:
        """Нарисовать куб панорамы (``gl_VertexID``-куб, без vertex buffer).

        Порт ``Panorama::draw``: 36 вершин, кубмап на samplerCube, матрица
        проекции в uniform ``projection`` (column-major).
        """
        if self.ctx is None:
            raise RuntimeError("[QuadRix] create_context() не вызван")
        if program is None or cube is None:
            return
        import moderngl

        # Куб: без отсечения граней (вид изнутри), глубина не пишется.
        self.ctx.disable(moderngl.CULL_FACE)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)

        if "projection" in program:
            program["projection"].write(
                np.ascontiguousarray(projection, dtype=np.float32).T.tobytes()
            )
        cube.use(location=0)
        if "panorama" in program:
            program["panorama"] = 0

        vao = self.ctx.vertex_array(program, [])
        try:
            vao.render(moderngl.TRIANGLES, vertices=36)
        finally:
            vao.release()

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
        pixels = np.frombuffer(data, dtype=np.uint8).reshape(fb_height, fb_width, 4)
        # glReadPixels отдаёт строки снизу вверх — переворачиваем, чтобы
        # первая строка массива соответствовала верху экрана.
        return np.flipud(pixels)

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

    # ------------------------------------------------------------------
    # ввод: glfw callbacks -> event_handler (App.handle_event)
    # ------------------------------------------------------------------

    def set_event_handler(self, handler: Optional[Callable[..., None]]) -> None:
        """Назначить обработчик UI-событий ``handler(kind, *args)``."""
        self.event_handler = handler

    def _emit(self, kind: str, *args: Any) -> None:
        """Передать событие обработчику, если он установлен."""
        handler = self.event_handler
        if handler is not None:
            handler(kind, *args)

    def _to_framebuffer(self, x: float, y: float) -> tuple[float, float]:
        """Оконные координаты курсора → пиксели кадрового буфера (DPI).

        Проекция UI строится под размер framebuffer, поэтому клики нужно
        привести к тем же пикселям.
        """
        glfw = self._glfw
        if glfw is None or self.window is None:
            return float(x), float(y)
        win_w, win_h = glfw.get_window_size(self.window)
        fb_w, fb_h = glfw.get_framebuffer_size(self.window)
        if win_w > 0 and win_h > 0:
            return float(x) * fb_w / win_w, float(y) * fb_h / win_h
        return float(x), float(y)

    def _on_cursor(self, window: Any, x: float, y: float) -> None:
        """glfw: курсор переместился — дельта для игры + ``("move", x, y)``."""
        dx = float(x) - self._mouse_x
        dy = float(y) - self._mouse_y
        self._mouse_x = float(x)
        self._mouse_y = float(y)
        if self._ignore_next_cursor:
            # Первый сдвиг после захвата курсора: только запоминаем позицию.
            self._ignore_next_cursor = False
        else:
            self._emit("mouse_move", dx, dy)
        fx, fy = self._to_framebuffer(x, y)
        self._emit("move", fx, fy)

    def set_mouse_grabbed(self, grabbed: bool) -> None:
        """Захватить/отпустить курсор (порт ``MouseHandler.grabMouse``)."""
        grabbed = bool(grabbed)
        if grabbed == self._mouse_grabbed:
            return
        self._mouse_grabbed = grabbed
        # Первый сдвиг после смены режима — служебный (курсор прыгает).
        self._ignore_next_cursor = True
        glfw = self._glfw
        if glfw is None or self.window is None:
            return
        try:
            if grabbed:
                glfw.set_input_mode(self.window, glfw.CURSOR, glfw.CURSOR_DISABLED)
            else:
                glfw.set_input_mode(self.window, glfw.CURSOR, glfw.CURSOR_NORMAL)
        except Exception:  # pragma: no cover - некоторые платформы не умеют
            pass

    def _on_mouse_button(
        self, window: Any, button: int, action: int, mods: int
    ) -> None:
        """glfw: ЛКМ/ПКМ → ``("click", x, y, button)`` / ``("release", x, y, button)``.

        ``button`` — 0 (левый) / 1 (правый): ``GameScreen`` по нему различает
        разрушение и установку. Отпускание обязательно: без него слайдер
        остаётся в ``dragging`` и ручка «прилипает» к курсору
        (порт ``MouseInput`` в options_ui.rs).
        """
        glfw = self._glfw
        if glfw is None:
            return
        if button == glfw.MOUSE_BUTTON_LEFT:
            index = 0
        elif button == getattr(glfw, "MOUSE_BUTTON_RIGHT", -1):
            index = 1
        else:
            return
        x, y = self._to_framebuffer(self._mouse_x, self._mouse_y)
        if action == glfw.PRESS:
            self._emit("click", x, y, index)
        elif action == glfw.RELEASE:
            self._emit("release", x, y, index)

    def _on_scroll(self, window: Any, xoffset: float, yoffset: float) -> None:
        """glfw: колесо мыши → ``("scroll", dy)``."""
        self._emit("scroll", float(yoffset))

    def _on_key(
        self, window: Any, key: int, scancode: int, action: int, mods: int
    ) -> None:
        """glfw: клавиша → ``("key", short)`` и ``("keydown"/"keyup", vanilla)``.

        ``key`` — короткое имя для меню (``escape``); ``keydown``/``keyup`` —
        ванильное имя (``key.keyboard.w``) для ``InputState``/GameScreen.
        """
        glfw = self._glfw
        if glfw is None:
            return
        vanilla = self._key_vanilla.get(key)
        name = self._key_names.get(key)
        if action == glfw.RELEASE:
            if vanilla is not None:
                self._emit("keyup", vanilla)
            return
        # PRESS и REPEAT: короткое имя только на PRESS (меню), ванильное —
        # на оба, чтобы удержание клавиши не теряло состояние.
        if action == glfw.PRESS and name is not None:
            self._emit("key", name, None)
        if vanilla is not None:
            self._emit("keydown", vanilla)

    def _on_char(self, window: Any, codepoint: int) -> None:
        """glfw: печатный символ → ``("key", "", ch)``."""
        if codepoint < 32:
            return
        try:
            ch = chr(codepoint)
        except ValueError:
            return
        self._emit("key", "", ch)

    def _on_framebuffer_size(self, window: Any, width: int, height: int) -> None:
        """glfw: размер кадрового буфера изменился → ``("resize", w, h)``."""
        self._emit("resize", float(width), float(height))

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

def _build_vanilla_keys(glfw: Any) -> dict[int, str]:
    """glfw key-code → ванильное имя клавиши (``key.keyboard.w``).

    Покрывает буквы, цифры, пробел, Shift/Ctrl/Alt и стрелки — то, что
    читает ``InputState``/``KeyBinds`` (порт ``keybinds::key_name``).
    """
    names: dict[int, str] = {}
    for code in range(ord("A"), ord("Z") + 1):
        names[glfw.__dict__.get(f"KEY_{chr(code)}", -1)] = f"key.keyboard.{chr(code).lower()}"
    for i in range(10):
        names[glfw.__dict__.get(f"KEY_{i}", -1)] = f"key.keyboard.{i}"
    specials = {
        "KEY_SPACE": "key.keyboard.space",
        "KEY_ESCAPE": "key.keyboard.escape",
        "KEY_ENTER": "key.keyboard.enter",
        "KEY_TAB": "key.keyboard.tab",
        "KEY_BACKSPACE": "key.keyboard.backspace",
        "KEY_LEFT_SHIFT": "key.keyboard.left.shift",
        "KEY_RIGHT_SHIFT": "key.keyboard.right.shift",
        "KEY_LEFT_CONTROL": "key.keyboard.left.control",
        "KEY_RIGHT_CONTROL": "key.keyboard.right.control",
        "KEY_LEFT_ALT": "key.keyboard.left.alt",
        "KEY_RIGHT_ALT": "key.keyboard.right.alt",
        "KEY_UP": "key.keyboard.up",
        "KEY_DOWN": "key.keyboard.down",
        "KEY_LEFT": "key.keyboard.left",
        "KEY_RIGHT": "key.keyboard.right",
        "KEY_F1": "key.keyboard.f1",
        "KEY_F2": "key.keyboard.f2",
        "KEY_F3": "key.keyboard.f3",
        "KEY_F4": "key.keyboard.f4",
        "KEY_F5": "key.keyboard.f5",
        "KEY_F11": "key.keyboard.f11",
    }
    for const, vanilla in specials.items():
        code = glfw.__dict__.get(const)
        if code is not None:
            names[code] = vanilla
    # Убрать служебную запись -1 (если код не нашёлся).
    names.pop(-1, None)
    return names


def load_shader(name: str) -> str:
    """Прочитать GLSL-файл из ``quadrix/render/shaders`` по имени."""
    from pathlib import Path

    path = Path(__file__).with_name("shaders") / name
    return path.read_text(encoding="utf-8")
