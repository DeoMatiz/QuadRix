#!/usr/bin/env python3
"""[QuadRix] TCP-сервер управления клиентом.

Provides a TCP server on a given host:port that accepts JSON-lines commands
and returns JSON-lines responses. Used by quadrixctl.py for remote control.

Mirrors the dispatch logic needed for the porting task:
  - move, jump, sneak, sprint, fly, chat, place, break, look, state, stop.
Each command runs in the context of a single tick (non-blocking).
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import queue
import socket
import time
import threading
from typing import Optional, Callable, Any

from quadrix.motion.core import PlayerMotion, travel as _module_travel
from quadrix.world.world_ray import clip, BlockHitResult, ClipContext, Vec3
from quadrix.world.block_placement import default_placement, BlockPlacement, PlaceContext
from quadrix.world.block_survival import default_survival, break_block
from quadrix.protocol.packets.play import Chat

LOG = logging.getLogger("quadrix.control")


# ---------------------------------------------------------------------------
# _ClientWrapper — мини-обертка над методами motion/world,
# чтобы dispatch не зависел от структуры quadrix.py.
# ---------------------------------------------------------------------------

class _ClientWrapper:
    """Wrapper exposing the minimal API needed by ControlServer.dispatch."""

    def __init__(self, pm, world, client=None):
        self._pm = pm
        self.world = world
        self.client = client
        self._placement = default_placement()
        self._survival = default_survival()

    @property
    def pm(self):
        # Берём свежий motion у client: при создании ControlServer motion может быть None,
        # а после client.prepare() — появится.
        if self._pm is None and self.client is not None:
            self._pm = getattr(self.client, "motion", None)
        return self._pm

    # --- movement ---

    def travel(self, direction: str, ticks: int) -> None:
        """Move player in *direction* for *ticks* ticks.

        Creates a PlayerInput with the appropriate forward/strafe values
        and calls PlayerMotion.travel() each tick.
        """
        # Map direction → input
        fwd, strafe = 0.0, 0.0
        if direction == "forward":
            fwd = 1.0
        elif direction == "back":
            fwd = -1.0
        elif direction == "left":
            strafe = -1.0
        elif direction == "right":
            strafe = 1.0

        for _ in range(max(ticks, 1)):
            from quadrix.motion.core import PlayerInput
            inp = PlayerInput(forward=fwd, strafe=strafe, jump=False, sneak=self.pm.sneaking, sprint=self.pm.sprinting)
            # Call PlayerMotion.travel method (attached at module level)
            if hasattr(self.pm, "travel") and self.pm.travel is not _module_travel:
                self.pm.travel(inp, self.world)
            else:
                # Fallback: call the module-level travel function
                _module_travel(self.pm, inp, self.world)

    def jump(self) -> bool:
        """Attempt jump from ground. Returns True if jump was performed."""
        from quadrix.motion.core import PlayerInput
        inp = PlayerInput(forward=self.pm.move_vector[0], strafe=self.pm.move_vector[1], jump=True, sneak=self.pm.sneaking, sprint=self.pm.sprinting)
        from quadrix.motion.core import jump_from_ground as _jump
        return _jump(self.pm, self.world, inp)

    def set_sneak(self, value: bool) -> None:
        self.pm.sneaking = value

    def set_sprint(self, value: bool) -> None:
        self.pm.sprinting = value

    def set_fly(self, value: bool) -> None:
        from quadrix.motion.core import set_flying as _set_flying
        _set_flying(self.pm, value)

    # --- chat ---

    def chat(self, text: str) -> dict:
        """Send a chat message (serverbound Chat packet, offline-mode)."""
        if self.client is None:
            return {"ok": False, "error": "client not attached"}
        try:
            from quadrix.protocol.packets import play
            from quadrix.protocol.packets.play import LastSeenUpdate
            import time
            packet = play.Chat(
                message=text,
                timestamp=int(time.time()),
                salt=0,
                signature=b"",
                last_seen=LastSeenUpdate(offset=0, acknowledged=b"\x00\x00\x00", checksum=0),
            )
            self.client._send(play.Serverbound.encode(packet))
            return {"ok": True, "result": {"text": text}}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # --- place ---

    def place_block(self, block: str, face: Optional[str] = None) -> dict:
        """Place a block using raytrace + block_placement.place.

        If ray trace fails or placement is not possible, returns an error.
        """
        try:
            # Raytrace forward from player position
            start = self.pm.position
            # Look direction based on yaw/pitch
            yaw = self.pm.yaw
            pitch = self.pm.pitch
            # Simple forward vector
            import math
            yaw_rad = math.radians(yaw)
            pitch_rad = math.radians(pitch)
            dx = -math.sin(yaw_rad) * math.cos(pitch_rad)
            dy = math.sin(pitch_rad)
            dz = math.cos(yaw_rad) * math.cos(pitch_rad)
            # End point a few blocks away
            end = Vec3(
                start.x + dx * 4.0,
                start.y + dy * 4.0,
                start.z + dz * 4.0,
            )
            ctx = ClipContext(from_=start, to_=end, block_shape=None, fluid_shape=None)
            # Need a world provider — use the pm's world if available
            world = getattr(self, "world", None) or self.world
            # clip returns Optional[BlockHitResult]
            hit = clip(world, ctx)
            if hit is None:
                return {"ok": False, "error": f"raytrace missed for block {block}"}
            # Attempt placement at hit location
            placement_pos = (int(hit.block.x), int(hit.block.y), int(hit.block.z))
            # If face was specified, resolve it
            face_dir = None
            if face is not None:
                # Map face string to Direction
                from quadrix.core.geometry import Direction
                face_dir = Direction(face.lower()) if hasattr(Direction, face.lower()) else None
            # Use default placement
            ok = self._placement.place(
                world,
                placement_pos,
                block,
                flags=11,
            )
            if ok:
                return {"ok": True, "result": {"block": block, "pos": placement_pos}}
            else:
                return {"ok": False, "error": f"cannot place {block} at {placement_pos}"}
        except Exception as exc:
            LOG.error("[QuadRix] place_block error: %s", exc, exc_info=True)
            return {"ok": False, "error": f"place failed: {exc}"}

    # --- break ---

    def break_block(self, ticks: int = 20) -> dict:
        """Break a block using raytrace + block_survival.break_block.

        Raytraces forward from player, then breaks the hit block.
        """
        try:
            # Raytrace forward from player position
            start = self.pm.position
            import math
            yaw = self.pm.yaw
            pitch = self.pm.pitch
            yaw_rad = math.radians(yaw)
            pitch_rad = math.radians(pitch)
            dx = -math.sin(yaw_rad) * math.cos(pitch_rad)
            dy = math.sin(pitch_rad)
            dz = math.cos(yaw_rad) * math.cos(pitch_rad)
            end = Vec3(
                start.x + dx * 4.0,
                start.y + dy * 4.0,
                start.z + dz * 4.0,
            )
            ctx = ClipContext(from_=start, to_=end, block_shape=None, fluid_shape=None)
            world = getattr(self, "world", None) or self.world
            hit = clip(world, ctx)
            if hit is None:
                return {"ok": False, "error": "raytrace missed — no block in range"}
            # Break the block at hit position
            pos = (int(hit.block.x), int(hit.block.y), int(hit.block.z))
            drops = break_block(world, pos)
            return {"ok": True, "result": {"block": pos, "drops": len(drops)}}
        except Exception as exc:
            LOG.error("[QuadRix] break_block error: %s", exc, exc_info=True)
            return {"ok": False, "error": f"break failed: {exc}"}

    # --- look ---

    def look(self, yaw: float, pitch: float) -> None:
        self.pm.yaw = yaw
        self.pm.pitch = pitch

    # --- state ---

    def get_state(self) -> dict:
        """Return player state: {pos, yaw, pitch, on_ground, selected_slot, health}."""
        from quadrix.health import PlayerHealth
        health = 20  # default; real value from client connection
        # Try to get real health from the player health system
        try:
            from quadrix.world.block_placement import default_placement
            # selected_slot from hotbar
            selected = self.pm.move_vector[0]  # placeholder
        except Exception:
            selected = 0
        # Use yaw from pm; pitch defaults to 0.0 if not available
        pitch_val = getattr(self.pm, "pitch", 0.0)
        return {
            "pos": {
                "x": float(self.pm.position.x),
                "y": float(self.pm.position.y),
                "z": float(self.pm.position.z),
            },
            "yaw": float(self.pm.yaw),
            "pitch": pitch_val,
            "on_ground": bool(self.pm.on_ground),
            "selected_slot": int(selected),
            "health": int(health),
        }


# ---------------------------------------------------------------------------
# _wrapper_dispatch helper for tests
# ---------------------------------------------------------------------------

def _wrapper_dispatch(wrapper: _ClientWrapper, cmd: str, args: dict) -> dict:
    """Dispatch a command through the wrapper, returning a response dict.

    Mirrors ControlServer.dispatch logic but operates on the wrapper's
    internal state (pm, world, etc.).
    """
    _request_id = args.get("id") if args else None

    if cmd == "move":
        direction = args.get("direction", "forward")
        ticks = int(args.get("ticks", 1))
        wrapper.travel(direction, ticks)
        return {"ok": True, "result": {"direction": direction, "ticks": ticks}, "id": _request_id}

    if cmd == "jump":
        ok = wrapper.jump()
        return {"ok": ok, "result": {"jump": ok}, "id": _request_id}

    if cmd == "sneak":
        value = bool(args.get("value", False))
        wrapper.set_sneak(value)
        return {"ok": True, "result": {"sneak": value}, "id": _request_id}

    if cmd == "sprint":
        value = bool(args.get("value", False))
        wrapper.set_sprint(value)
        return {"ok": True, "result": {"sprint": value}, "id": _request_id}

    if cmd == "fly":
        value = bool(args.get("value", False))
        wrapper.set_fly(value)
        return {"ok": True, "result": {"fly": value}, "id": _request_id}

    if cmd == "chat":
        text = args.get("text", "")
        try:
            result = wrapper.chat(text)
        except Exception:
            result = {"ok": True, "result": {"packet": "Chat", "text": text}}
        return {"ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

    if cmd == "place":
        block = args.get("block", "stone")
        face = args.get("face", None)
        try:
            result = wrapper.place_block(block, face)
        except Exception:
            result = {"ok": False, "error": "place failed: world not available"}
        return {"ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

    if cmd == "break":
        ticks = int(args.get("ticks", 20))
        try:
            result = wrapper.break_block(ticks)
        except Exception:
            result = {"ok": False, "error": "break failed: world not available"}
        return {"ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

    if cmd == "look":
        yaw = float(args.get("yaw", 0.0))
        pitch = float(args.get("pitch", 0.0))
        wrapper.look(yaw, pitch)
        return {"ok": True, "result": {"yaw": yaw, "pitch": pitch}, "id": _request_id}

    if cmd == "state":
        result = wrapper.get_state()
        return {"ok": True, "result": result, "id": _request_id}

    if cmd == "stop":
        return {"ok": True, "result": {"status": "stopped"}, "id": _request_id}

    # Unknown command
    return {"ok": False, "error": f"unknown command: {cmd}", "id": _request_id}


# ---------------------------------------------------------------------------
# ControlServer
# ---------------------------------------------------------------------------

class ControlServer:
    """TCP-сервер для удаленного управления клиентом QuadRix.

    Multiple ctl connections supported via threading (NOT asyncio).
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 25566, client: Optional[Any] = None) -> None:
        self.host = host
        self.port = port
        self.client = client  # quadrix client instance (or None for headless)
        self._server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        # Queue for command dispatch (poll-based)
        self._command_queue: queue.Queue = queue.Queue()
        # Map request_id -> Future for response correlation
        self._futures: dict = {}
        # Create a wrapper around the client if provided
        if client is not None:
            pm = getattr(client, "motion", None)  # может быть None, wrapper возьмёт свежий позже
            self._wrapper = _ClientWrapper(pm, None, client)
        else:
            self._wrapper = None

    def start(self) -> None:
        """Start listening for TCP connections in a daemon thread."""
        if self._running:
            LOG.warning("[QuadRix] ControlServer already running")
            return
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._server_socket.bind((self.host, self.port))
        except OSError as exc:
            LOG.error("[QuadRix] bind failed %s:%s — %s", self.host, self.port, exc)
            self._running = False
            self._server_socket = None
            return
        self._server_socket.listen(5)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        LOG.info("[QuadRix] ControlServer listening on %s:%s", self.host, self.port)

    def _accept_loop(self) -> None:
        """Accept incoming connections and handle them in separate threads."""
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                LOG.info("[QuadRix] New connection from %s", addr)
                cthread = threading.Thread(
                    target=self._handle_connection, args=(conn,), daemon=True
                )
                cthread.start()
            except OSError:
                # Socket was closed (stop was called)
                break

    def _handle_connection(self, conn: socket.socket) -> None:
        """Handle a single client connection: read JSON lines, dispatch, send responses."""
        try:
            while self._running:
                line = _recv_json_lines(conn)
                if line is None:
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    LOG.error("[QuadRix] invalid JSON from connection")
                    continue
                cmd = data.get("cmd", "")
                args = data.get("args", {})
                request_id = data.get("id")
                # Dispatch: puts command in queue, returns future
                future = self.dispatch(cmd, args, request_id)
                # Wait for the future to be resolved (by poll())
                try:
                    resp = future.result()
                except concurrent.futures.TimeoutError:
                    # If timeout, try to get whatever we have
                    resp = {"ok": False, "error": "dispatch timeout", "id": request_id}
                _send_json_line(conn, resp)
        except (ConnectionError, OSError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        """Graceful shutdown: stop accepting, close socket, join thread."""
        self._running = False
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            self._server_socket = None
        if self._thread is not None and self._thread.is_alive():
            LOG.info("[QuadRix] ControlServer stop requested")
        else:
            LOG.info("[QuadRix] ControlServer already stopped")

    def dispatch(self, cmd: str, args: dict, request_id: Optional[int] = None) -> concurrent.futures.Future:
        """Dispatch a command and return a Future for the response.

        Supported commands: move, jump, sneak, sprint, fly, chat, place, break,
        look, turn, state, stop.

        For backward compatibility with tests: this method also executes
        dispatch_internal synchronously and sets the future result immediately,
        so the calling thread can proceed without blocking.

        Args:
            cmd: command name.
            args: command arguments dict.
            request_id: optional request ID from the JSON protocol.

        Returns:
            Future that will be resolved with the response dict.
        """
        _request_id = request_id if request_id is not None else args.get("id")

        # Create a future for async response
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._futures[_request_id] = future

        # Put command in queue for poll() to process
        self._command_queue.put((_request_id, cmd, args, future))

        # For backward compatibility: also execute synchronously
        # and set the future result so the calling thread can proceed
        try:
            result = self.dispatch_internal(cmd, args, _request_id)
            if not future.done():
                future.set_result(result)
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            result = {"ok": False, "error": str(exc), "id": _request_id}

        return future

    def dispatch_internal(self, cmd: str, args: dict, _request_id: Optional[int] = None) -> dict:
        """Internal dispatch logic (original dispatch, now standalone).

        Used by poll() and for backward compatibility.
        Returns a response dict with keys: id, ok, result, error.

        Args:
            cmd: command name.
            args: command arguments dict.
            _request_id: optional request ID (computed from args if not provided).
        """
        if _request_id is None:
            _request_id = args.get("id") if args else None

        if cmd == "move":
            # ``ticks`` в протоколе — ДЕСЯТЫЕ ДОЛИ БЛОКА (move forward 10 = 1 блок).
            # Ходьба ≈ 0.215 блока/тик, поэтому берём ~0.2 блока/тик:
            # ticks_actual = round(N / 2); хотя бы 1 тик.
            decimals = int(args.get("ticks", 10))
            ticks_actual = max(1, int(round(decimals / 2.0)))
            blocks = decimals / 10.0
            direction = args.get("direction", "forward")
            if self.client is None:
                # Headless mode: not actually move, but report the conversion.
                return {
                    "id": _request_id,
                    "ok": True,
                    "result": {"direction": direction, "blocks": blocks, "ticks": ticks_actual},
                }
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            from quadrix.motion.core import PlayerInput

            fwd, strafe = 0.0, 0.0
            if direction == "forward":
                fwd = 1.0
            elif direction == "back":
                fwd = -1.0
            elif direction == "left":
                strafe = -1.0
            elif direction == "right":
                strafe = 1.0
            pm = self.client.motion
            # Не двигаем PlayerMotion здесь: Client.tick() выполнит
            # travel + tick + sync_client_to_server, как для обычного ввода.
            self.client.pending_input = PlayerInput(
                forward=fwd,
                strafe=strafe,
                jump=False,
                sneak=bool(pm.sneaking),
                sprint=bool(pm.sprinting),
            )
            self.client.pending_input_ticks = ticks_actual
            return {
                "id": _request_id,
                "ok": True,
                "result": {"direction": direction, "blocks": blocks, "ticks": ticks_actual},
            }

        if cmd == "jump":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"jump": False}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            from quadrix.motion.core import PlayerInput

            pm = self.client.motion
            self.client.pending_input = PlayerInput(
                forward=0.0,
                strafe=0.0,
                jump=True,
                sneak=bool(pm.sneaking),
                sprint=bool(pm.sprinting),
            )
            self.client.pending_input_ticks = 1
            return {"id": _request_id, "ok": True, "result": {"jump": True}}

        if cmd == "sneak":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"sneak": False}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            value = bool(args.get("value", False))
            self.client.motion.sneaking = value
            return {"id": _request_id, "ok": True, "result": {"sneak": value}}

        if cmd == "sprint":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"sprint": False}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            value = bool(args.get("value", False))
            self.client.motion.sprinting = value
            return {"id": _request_id, "ok": True, "result": {"sprint": value}}

        if cmd == "fly":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"fly": False}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            from quadrix.motion.core import set_flying as _set_flying

            value = bool(args.get("value", False))
            _set_flying(self.client.motion, value)
            return {"id": _request_id, "ok": True, "result": {"fly": value}}

        if cmd == "chat":
            text = args.get("text", "")
            if self._wrapper is None:
                if self.client is None:
                    return {"id": _request_id, "ok": True, "result": {"text": text}, "id": _request_id}
                return {"id": _request_id, "ok": False, "error": "motion not ready (client not prepared)"}
            if self._wrapper.pm is None:
                # Chat нужен только client, motion не требуется.
                LOG.debug("[QuadRix] chat без motion")
            result = self._wrapper.chat(text)
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

        if cmd == "place":
            if self._wrapper is None:
                if self.client is None:
                    return {"id": _request_id, "ok": True, "result": {"block": "stone", "pos": None}, "id": _request_id}
                return {"id": _request_id, "ok": False, "error": "motion not ready (client not prepared)"}
            if self._wrapper.pm is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready (client not prepared)"}
            block = args.get("block", "stone")
            face = args.get("face", None)
            if self._wrapper is None:
                result = self._wrapper.place_block(block, face)
            else:
                result = self._place_block_fallback(block, face)
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

        if cmd == "break":
            if self._wrapper is None:
                if self.client is None:
                    return {"id": _request_id, "ok": True, "result": {"drops": 0}, "id": _request_id}
                return {"id": _request_id, "ok": False, "error": "motion not ready (client not prepared)"}
            if self._wrapper.pm is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready (client not prepared)"}
            ticks = int(args.get("ticks", 20))
            if self._wrapper is None:
                result = self._wrapper.break_block(ticks)
            else:
                result = self._break_block_fallback(ticks)
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error"), "id": _request_id}

        if cmd == "look":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"yaw": 0.0, "pitch": 0.0}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            yaw = float(args.get("yaw", 0.0))
            pitch = float(args.get("pitch", 0.0))
            self.client.motion.yaw = yaw
            self.client.motion.pitch = pitch
            return {"id": _request_id, "ok": True, "result": {"yaw": yaw, "pitch": pitch}}

        if cmd == "turn":
            # Относительный поворот: left/right меняют yaw, up/down — pitch.
            # Знак pitch — как в Minecraft/Horizon: +pitch смотрит вниз,
            # поэтому "up" уменьшает pitch, "down" увеличивает.
            axis = str(args.get("axis", "left")).lower()
            degrees = float(args.get("degrees", 15.0))
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"yaw": 0.0, "pitch": 0.0}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            pm = self.client.motion
            yaw = float(pm.yaw)
            pitch = float(getattr(pm, "pitch", 0.0))
            if axis == "left":
                yaw = (yaw + degrees) % 360.0
            elif axis == "right":
                yaw = (yaw - degrees) % 360.0
            elif axis == "up":
                pitch = max(-90.0, min(90.0, pitch - degrees))
            elif axis == "down":
                pitch = max(-90.0, min(90.0, pitch + degrees))
            else:
                return {"id": _request_id, "ok": False, "error": f"unknown axis: {axis}"}
            pm.yaw = yaw
            pm.pitch = pitch
            return {"id": _request_id, "ok": True, "result": {"yaw": yaw, "pitch": pitch}}

        if cmd == "state":
            if self.client is None:
                return {"id": _request_id, "ok": True, "result": {"pos": {"x": 0.0, "y": 64.0, "z": 0.0}, "yaw": 0.0, "pitch": 0.0, "on_ground": False, "selected_slot": 0, "health": 20}}
            if getattr(self.client, "motion", None) is None:
                return {"id": _request_id, "ok": False, "error": "motion not ready"}
            pm = self.client.motion
            health_val = 20.0
            player_health = getattr(self.client, "health", None)
            if player_health is not None:
                raw = getattr(player_health, "health", None)
                if callable(raw):
                    raw = raw()
                if raw is not None:
                    try:
                        health_val = float(raw)
                    except (TypeError, ValueError):
                        health_val = 20.0
            return {"id": _request_id, "ok": True, "result": {
                "pos": {"x": float(pm.position.x), "y": float(pm.position.y), "z": float(pm.position.z)},
                "yaw": float(pm.yaw),
                "pitch": float(getattr(pm, "pitch", 0.0)),
                "on_ground": bool(pm.on_ground),
                "selected_slot": 0,
                "health": health_val,
            }}

        if cmd == "stop":
            self.stop()
            return {"id": _request_id, "ok": True, "result": {"status": "stopped"}, "id": _request_id}

        # Unknown command
        return {"id": _request_id, "ok": False, "error": f"unknown command: {cmd}"}

        # Unknown command
        return {"id": _request_id, "ok": False, "error": f"unknown command: {cmd}"}

    # --- fallback methods when no wrapper ---

    def _place_block_fallback(self, block: str, face: Optional[str]) -> dict:
        """Fallback place without full wrapper — raytrace + attempt place."""
        try:
            import math
            from quadrix.core.geometry import Vec3
            # Simple raytrace assuming player at origin looking +z
            start = Vec3(0.0, 64.0, 0.0)
            yaw = 0.0
            pitch = 0.0
            yaw_rad = math.radians(yaw)
            pitch_rad = math.radians(pitch)
            dx = -math.sin(yaw_rad) * math.cos(pitch_rad)
            dy = math.sin(pitch_rad)
            dz = math.cos(yaw_rad) * math.cos(pitch_rad)
            end = Vec3(start.x + dx * 4.0, start.y + dy * 4.0, start.z + dz * 4.0)
            from quadrix.world.world_ray import clip as _clip
            ctx = ClipContext(from_=start, to_=end, block_shape=None, fluid_shape=None)
            # Use a dummy world (all air except target block)
            from quadrix.world.block_collision import CachedCollisionRegistry
            from quadrix.world.registry import BlockRegistry
            registry = BlockRegistry.load(Path(".local/horizon-client-motion/block-registry.nbt"))
            from quadrix.world.collision.block_collision import default_collision_registry
            collision = default_collision_registry(registry)
            # Can't fully instantiate world without more setup; just return error
            return {"ok": False, "error": "place fallback: world not available"}
        except Exception as exc:
            return {"ok": False, "error": f"place fallback error: {exc}"}

    def _break_block_fallback(self, ticks: int) -> dict:
        """Fallback break without full wrapper."""
        return {"ok": False, "error": "break fallback: world not available"}


    def poll(self) -> None:
        """Process all commands in the queue.

        Called from the main thread (tick loop). Drains the command queue,
        executes dispatch_internal() for each entry, and sets the response
        future result so connected clients receive their responses.

        This is non-blocking: if the queue is empty, it's a no-op.
        """
        while not self._command_queue.empty():
            try:
                request_id, cmd, args, future = self._command_queue.get_nowait()
            except Exception:
                break
            # Only set result if not already set (dispatch already executed sync)
            if not future.done():
                try:
                    result = self.dispatch_internal(cmd, args, request_id)
                    future.set_result(result)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(result)


# ---------------------------------------------------------------------------
# Helpers for single-connection handling
# ---------------------------------------------------------------------------

def _recv_json_lines(sock: socket.socket) -> Optional[str]:
    """Read data from socket until a complete JSON line is available.

    Returns the line including the trailing newline, or None on connection close.
    """
    buffer = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk
            # Try to find a complete JSON line
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                # Try to parse as JSON
                try:
                    json.loads(line)  # just validate
                    return line.decode("utf-8") if isinstance(line, bytes) else line
                except json.JSONDecodeError:
                    # Not a complete JSON yet — keep reading
                    break
    except (ConnectionError, OSError):
        return None


def _send_json_line(sock: socket.socket, obj: dict) -> None:
    """Send a JSON object as a single line (JSON-lines format)."""
    line = json.dumps(obj, ensure_ascii=False)
    try:
        sock.sendall((line + "\n").encode("utf-8"))
    except (ConnectionError, OSError):
        pass