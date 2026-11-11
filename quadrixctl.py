#!/usr/bin/env python3
"""[QuadRix] Клиент управления по TCP (quadrixctl.py).

REPL-клиент, который подключается к ControlServer в quadrix.py --daemon
и шлёт JSON-lines команды.

Использование:
    python quadrixctl.py --host 127.0.0.1 --port 25566
"""

from __future__ import annotations

import argparse
import json
import socket
import sys

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

HELP = """Команды:
  move forward|back|left|right N       — идти N десятых блока (10 = 1 блок)
  turn left|right|up|down [DEG]        — повернуть голову (по умолчанию 15°)
  jump                                 — прыжок
  sneak|sprint|fly true|false          — переключатели
  chat TEXT                            — отправить сообщение
  place BLOCK [face]                   — поставить блок
  break [TICKS]                        — ломать блок
  look YAW PITCH                       — установить углы
  state                                — состояние игрока
  stop                                 — завершить демон
  help                                 — эта справка
  quit                                 — выйти из ctl (демон продолжит работу)

Алиасы: w/forward, s/back, a/left, d/right — шаг 1 блок;
        tl/tr/tu/td — поворот на 15°; space — прыжок.
"""


def build_request(line: str, req_id: int) -> dict | None:
    """Парсит строку в JSON-запрос. None — если это help/quit/пусто."""
    parts = line.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower()
    rest = parts[1:]

    if cmd in ("help", "h"):
        print(YELLOW + HELP + RESET)
        return None
    if cmd in ("quit", "q", "exit"):
        return {"__quit__": True}

    args: dict = {}

    # Алиасы: w/s/a/d — шаг на 1 блок (10 десятых), tl/tr/tu/td — 15°.
    _MOVE_ALIASES = {
        "w": "forward",
        "forward": "forward",
        "s": "back",
        "back": "back",
        "a": "left",
        "left": "left",
        "d": "right",
        "right": "right",
    }
    _TURN_ALIASES = {
        "tl": "left",
        "tr": "right",
        "tu": "up",
        "td": "down",
    }

    if cmd in _MOVE_ALIASES:
        args["direction"] = _MOVE_ALIASES[cmd]
        # По умолчанию 1 блок = 10 десятых; можно указать своё N.
        args["ticks"] = int(rest[0]) if rest else 10
        return {"id": req_id, "cmd": "move", "args": args}

    if cmd in _TURN_ALIASES:
        args["axis"] = _TURN_ALIASES[cmd]
        args["degrees"] = float(rest[0]) if rest else 15.0
        return {"id": req_id, "cmd": "turn", "args": args}

    if cmd == "space":
        return {"id": req_id, "cmd": "jump", "args": {}}

    if cmd == "move":
        args["direction"] = rest[0] if rest else "forward"
        args["ticks"] = int(rest[1]) if len(rest) > 1 else 10
    elif cmd == "turn":
        args["axis"] = rest[0] if rest else "left"
        args["degrees"] = float(rest[1]) if len(rest) > 1 else 15.0
    elif cmd == "jump":
        pass
    elif cmd in ("sneak", "sprint", "fly"):
        v = (rest[0] if rest else "true").lower()
        args["value"] = v in ("true", "1", "yes", "on")
    elif cmd == "chat":
        args["text"] = " ".join(rest)
    elif cmd == "place":
        args["block"] = rest[0] if rest else "stone"
        if len(rest) > 1:
            args["face"] = rest[1]
    elif cmd == "break":
        args["ticks"] = int(rest[0]) if rest else 20
    elif cmd == "look":
        args["yaw"] = float(rest[0]) if rest else 0.0
        args["pitch"] = float(rest[1]) if len(rest) > 1 else 0.0
    elif cmd == "state":
        pass
    elif cmd == "stop":
        pass
    else:
        print(RED + f"unknown command: {cmd}" + RESET)
        return None

    return {"id": req_id, "cmd": cmd, "args": args}


def main() -> None:
    ap = argparse.ArgumentParser(description="QuadRix TCP control client")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=25566)
    args = ap.parse_args()

    try:
        sock = socket.create_connection((args.host, args.port), timeout=5.0)
    except OSError as exc:
        print(RED + f"[QuadRix] connect failed {args.host}:{args.port} — {exc}" + RESET)
        sys.exit(1)
    sock.settimeout(None)
    rfile = sock.makefile("r", encoding="utf-8", newline="\n")

    print(GREEN + f"[QuadRix] connected to {args.host}:{args.port}" + RESET)
    print(YELLOW + "Type 'help' for commands, 'quit' to exit" + RESET)

    req_id = 0
    try:
        while True:
            try:
                line = input("quadrix> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            req = build_request(line, req_id + 1)
            if req is None:
                continue
            if req.get("__quit__"):
                break
            req_id += 1
            sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
            resp_line = rfile.readline()
            if not resp_line:
                print(RED + "[QuadRix] daemon closed connection" + RESET)
                break
            try:
                resp = json.loads(resp_line)
            except json.JSONDecodeError:
                print(RED + f"[QuadRix] bad response: {resp_line!r}" + RESET)
                continue
            if resp.get("ok"):
                print(GREEN + "[ok]" + RESET)
                if resp.get("result") is not None:
                    print("  " + json.dumps(resp["result"], ensure_ascii=False))
            else:
                print(RED + "[error]" + RESET)
                if resp.get("error"):
                    print("  " + resp["error"])
    finally:
        try:
            rfile.close()
        except Exception:
            pass
        sock.close()
        print(YELLOW + "[QuadRix] disconnected" + RESET)


if __name__ == "__main__":
    main()