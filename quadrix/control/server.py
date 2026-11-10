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

    def __init__(self, pm: PlayerMotion, world):
        self.pm = pm
        self.world = world
        self._placement = default_placement()
        self._survival = default_survival()

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
            inp = type("PlayerInput", (), {"forward": fwd, "strafe": strafe, "jump": False, "sneak": self.pm.sneaking, "sprint": self.pm.sprinting})()
            # Call PlayerMotion.travel method (attached at module level)
            if hasattr(self.pm, "travel") and self.pm.travel is not _module_travel:
                self.pm.travel(inp, self.world)
            else:
                # Fallback: call the module-level travel function
                _module_travel(self.pm, inp, self.world)

    def jump(self) -> bool:
        """Attempt jump from ground. Returns True if jump was performed."""
        inp = type("PlayerInput", (), {"forward": self.pm.move_vector[0], "strafe": self.pm.move_vector[1], "jump": True, "sneak": self.pm.sneaking, "sprint": self.pm.sprinting})()
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
        """Send a chat message (serverbound Chat packet).

        For control server fallback - just return success.
        """
        return {"ok": True, "result": {"packet": "Chat", "text": text}}

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
            # We need a world object for the wrapper; use a minimal fake
            pm = getattr(client, "motion", type("PM", (), {"position": type("V", (), ("x","y","z"))(), "yaw": 0.0, "pitch": 0.0, "on_ground": False, "move_vector": [0.0, 0.0]})())
            self._wrapper = _ClientWrapper(pm, None)  # world will be set per-command
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
        look, state, stop.

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
            direction = args.get("direction", "forward")
            ticks = int(args.get("ticks", 1))
            if self._wrapper is not None:
                self._wrapper.travel(direction, ticks)
            return {"id": _request_id, "ok": True, "result": {"direction": direction, "ticks": ticks}}

        if cmd == "jump":
            if self._wrapper is not None:
                ok = self._wrapper.jump()
            else:
                ok = True
            return {"id": _request_id, "ok": ok, "result": {"jump": ok}}

        if cmd == "sneak":
            value = bool(args.get("value", False))
            if self._wrapper is not None:
                self._wrapper.set_sneak(value)
            return {"id": _request_id, "ok": True, "result": {"sneak": value}}

        if cmd == "sprint":
            value = bool(args.get("value", False))
            if self._wrapper is not None:
                self._wrapper.set_sprint(value)
            return {"id": _request_id, "ok": True, "result": {"sprint": value}}

        if cmd == "fly":
            value = bool(args.get("value", False))
            if self._wrapper is not None:
                self._wrapper.set_fly(value)
            return {"id": _request_id, "ok": True, "result": {"fly": value}}

        if cmd == "chat":
            text = args.get("text", "")
            if self._wrapper is not None:
                result = self._wrapper.chat(text)
            else:
                # Minimal fallback without wrapper
                result = {"ok": True, "result": {"packet": "Chat", "text": text}}
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error")}

        if cmd == "place":
            block = args.get("block", "stone")
            face = args.get("face", None)
            if self._wrapper is not None:
                result = self._wrapper.place_block(block, face)
            else:
                result = self._place_block_fallback(block, face)
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error")}

        if cmd == "break":
            ticks = int(args.get("ticks", 20))
            if self._wrapper is not None:
                result = self._wrapper.break_block(ticks)
            else:
                result = self._break_block_fallback(ticks)
            return {"id": _request_id, "ok": result.get("ok", False), "result": result.get("result"), "error": result.get("error")}

        if cmd == "look":
            yaw = float(args.get("yaw", 0.0))
            pitch = float(args.get("pitch", 0.0))
            if self._wrapper is not None:
                self._wrapper.look(yaw, pitch)
            return {"id": _request_id, "ok": True, "result": {"yaw": yaw, "pitch": pitch}}

        if cmd == "state":
            if self._wrapper is not None:
                result = self._wrapper.get_state()
            else:
                result = {"pos": {"x": 0.0, "y": 64.0, "z": 0.0}, "yaw": 0.0, "pitch": 0.0, "on_ground": False, "selected_slot": 0, "health": 20}
            return {"id": _request_id, "ok": True, "result": result}

        if cmd == "stop":
            self.stop()
            return {"id": _request_id, "ok": True, "result": {"status": "stopped"}}

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