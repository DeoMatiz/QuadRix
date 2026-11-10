#!/usr/bin/env python3
"""[QuadRix] Клиент управления по TCP (quadrixctl.py).

REPL-интерфейс для отправки JSON-команд на TCP-сервер ControlServer,
запущенный quadrix.py --daemon. Команды отправляются в формате JSON-lines,
ответы печатаются с цветным выводом (зеленый ok, красный error, желтый help).

Использование:
    python quadrixctl.py --host localhost --port 25566

Команды (короткие алиасы):
    move forward 20   — идти вперед 20 тиков
    move back 10      — отstep назад
    move left 5       — влево
    move right 5      — вправо
    jump              — прыжок
    sneak             — затаиться (toggle)
    sprint            — спринт (toggle)
    fly               — полёт (toggle)
    chat hello        — отправить сообщение
    place stone       — поставить блок stone
    break             — разрушить блок (20 тиков по умолчанию)
    look 90 60        — установить yaw/pitch
    state             — показать состояние игрока
    stop              — корректно завершить клиента
    help              — справка
    quit              — выйти
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import signal  # noqa: F401 — используется в обработке Ctrl+C

from quadrix.control.server import ControlServer, _ClientWrapper

# ANSI цветовой вывод
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"
BOLD = "\033[1m"

# Глобальный флаг остановки
_stop_requested = False


def _def_handler(sig, frame):  # noqa: F811 — переопределение сигнала
    global _stop_requested
    _stop_requested = True
    print(f"\n{YELLOW}[QuadRix] Ctrl+C получен, отправка stop...{RESET}", flush=True)


signal.signal(signal.SIGINT, _def_handler)


def parse_args_args(text: str) -> dict:
    """Parse a command line like 'move forward 20' or 'jump' into {'cmd': ..., 'args': {...}}.

    Supported formats:
        cmd arg1 arg2 ...   (positional args)
        cmd key=value key2=value2  (keyword args)
    """
    text = text.strip()
    if not text:
        return None

    parts = text.split()
    cmd = parts[0].lower()
    rest = parts[1:]

    # Try keyword-style parsing (key=value)
    kwargs = {}
    for p in rest:
        if "=" in p:
            k, v = p.split("=", 1)
            kwargs[k] = v
        else:
            kwargs.setdefault("_arg", p)

    # Build args dict based on command
    args: dict = {}

    # Command mapping helpers
    if cmd in ("move", "m"):
        # move direction ticks
        direction = kwargs.get("_arg", rest[0] if rest else "forward") if rest else "forward"
        # Validate direction
        dir_ok = direction in ("forward", "back", "left", "right")
        if not dir_ok and rest:
            direction = rest[0]
        ticks = int(kwargs.get("ticks", rest[-1] if len(rest) >= 2 else "1"))
        args = {"direction": direction, "ticks": ticks}
        cmd = "move"

    elif cmd in ("jump", "j"):
        args = {}

    elif cmd in ("sneak", "sk"):
        val = kwargs.get("_arg", rest[0] if rest else "false")
        args = {"value": val.lower() in ("true", "1", "yes", "on")}

    elif cmd in ("sprint", "sp"):
        val = kwargs.get("_arg", rest[0] if rest else "false")
        args = {"value": val.lower() in ("true", "1", "yes", "on")}

    elif cmd in ("fly", "f"):
        val = kwargs.get("_arg", rest[0] if rest else "false")
        args = {"value": val.lower() in ("true", "1", "yes", "on")}

    elif cmd in ("chat", "c"):
        text = kwargs.get("_arg", " ".join(rest)) if rest else ""
        args = {"text": text}

    elif cmd in ("place", "p"):
        block = kwargs.get("_arg", rest[0] if rest else "stone")
        face = kwargs.get("face", None)
        args = {"block": block, "face": face}

    elif cmd in ("break", "b"):
        ticks = int(kwargs.get("ticks", "20"))
        args = {"ticks": ticks}

    elif cmd in ("look", "l"):
        try:
            yaw = float(kwargs.get("_arg", rest[0] if len(rest) >= 1 else "0.0"))
            pitch = float(kwargs.get("_arg", rest[1] if len(rest) >= 2 else "0.0"))
        except (ValueError, IndexError):
            yaw = 0.0
            pitch = 0.0
        args = {"yaw": yaw, "pitch": pitch}

    elif cmd in ("state", "s"):
        args = {}

    elif cmd in ("stop",):
        args = {}

    elif cmd in ("help", "h"):
        # Print help and return None to indicate help was shown
        return {"cmd": "help", "args": {}, "show_help": True}

    else:
        # Unknown command
        args = {"_unknown": cmd}

    return {"cmd": cmd, "args": args}


def repl_loop(server: ControlServer) -> None:
    """Read-eval-print loop for the CLI.

    Reads lines from stdin, parses commands, sends them to the server,
    and prints coloured responses.
    """
    print(f"{YELLOW}[QuadRix] Type 'help' for commands, Ctrl+C to exit{RESET}", flush=True)
    while not _stop_requested:
        try:
            line = input().strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{YELLOW}[QuadRix] Use 'stop' to exit{RESET}", flush=True)
            break

        if not line:
            continue

        parsed = parse_args_args(line)
        if parsed is None:
            continue

        # Handle help specially
        if parsed.get("show_help"):
            print(
                f"{YELLOW}Available commands:{RESET}",
                flush=True,
            )
            print(
                f"  {GREEN}move forward|back|left|right TICKS{RESET}",
                flush=True,
            )
            print(
                f"  {GREEN}jump{RESET} — прыжок",
                flush=True,
            )
            print(
                f"  {GREEN}sneak|sprint|fly TOGGLE{RESET} — переключатели (true/false)",
                flush=True,
            )
            print(
                f"  {GREEN}chat TEXT{RESET} — отправить сообщение",
                flush=True,
            )
            print(
                f"  {GREEN}place BLOCK[ face]{RESET} — поставить блок",
                flush=True,
            )
            print(
                f"  {GREEN}break[TICKS]{RESET} — разрушить блок",
                flush=True,
            )
            print(
                f"  {GREEN}look YAW PITCH{RESET} — установить углы",
                flush=True,
            )
            print(
                f"  {GREEN}state{RESET} — показать состояние",
                flush=True,
            )
            print(
                f"  {GREEN}stop{RESET} — завершить",
                flush=True,
            )
            print(
                f"  {YELLOW}help{RESET} — эта справка",
                flush=True,
                flush=True,
            )
            print(
                f"  {YELLOW}quit{RESET} — выйти",
                flush=True,
            )
            continue

        cmd = parsed["cmd"]
        args = parsed["args"]

        # Check for unknown command
        if cmd != "help" and "_unknown" in str(args):
            response = server.dispatch("unknown", {})
            print(f"{RED}[error] unknown command: {cmd}{RESET}", flush=True)
            print(f"  {json.dumps(response, ensure_ascii=False)}", flush=True)
            continue

        # Send command to server
        try:
            response = server.dispatch(cmd, args)
            ok = response.get("ok", False)

            # Print response with colour
            if ok:
                print(f"{GREEN}[ok]{RESET}", flush=True)
            else:
                print(f"{RED}[error]{RESET}", flush=True)

            # Print result/error
            result = response.get("result")
            error = response.get("error")
            if result is not None:
                print(f"  {json.dumps(result, ensure_ascii=False, flush=False)}", flush=True)
            if error is not None:
                print(f"  {json.dumps({"error": error}, ensure_ascii=False, flush=False)}", flush=True)

        except Exception as exc:
            print(f"{RED}[error] dispatch exception: {exc}{RESET}", flush=True)


def main() -> None:
    """Entry point for quadrixctl.py."""
    parser = argparse.ArgumentParser(description="QuadRix TCP control client")
    parser.add_argument("--host", default="127.0.0.1", help="TCP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=25566, help="TCP port (default: 25566)")
    args = parser.parse_args()

    # Create ControlServer instance (without client wrapper for standalone mode)
    # The server will be connected to by the quadrix.py --daemon process
    server = ControlServer(host=args.host, port=args.port, client=None)

    # Start the server (listen thread)
    server.start()

    print(f"{GREEN}[QuadRix] Control server listening on {args.host}:{args.port}{RESET}", flush=True)
    print(f"{YELLOW}[QuadRix] Connect quadrix.py --daemon to the same port{RESET}", flush=True)

    # Run REPL loop
    try:
        repl_loop(server)
    finally:
        server.stop()
        print(f"{YELLOW}[QuadRix] Client exited{RESET}", flush=True)


if __name__ == "__main__":
    main()