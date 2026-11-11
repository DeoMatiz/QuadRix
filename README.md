# QuadRix

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Status: playable core](https://img.shields.io/badge/status-playable%20core-green.svg)](PORTING_STATE.yaml)

**QuadRix** is a Python port of [Horizon](https://github.com/horizon-rust/horizon) (Rust Minecraft client).

> **Status:** playable core. A client connects to a server, moves, places/breaks blocks, manages inventory.
> The long-term goal is a **full port** (rendering, GUI, mobs, worldgen) — but that depends on whether
> Python can be optimized enough to make it playable. See [`PORTING_STATE.yaml`](PORTING_STATE.yaml).

## Why

Horizon is a full Minecraft client in Rust. QuadRix ports it to Python so it can run where Rust cannot
(or where Python is preferred), and to enable scripted/automated control of a client.

The end goal is a complete Python client: render, GUI, gameplay, mobs, worldgen. But Python is 50–100×
slower than Rust for hot paths. Whether a full port is playable depends on how far we can push
optimization (numpy, Cython, native extensions). The project is honest about this: **we try, but do not
promise a finished full port.**

## What works

**Network** — full protocol (1.21.x / 26.x):
- Handshake → login → configuration → play (144 clientbound + 69 serverbound packets)
- Compression, encryption (AES/CFB8 + RSA), state machine
- Chunk data, heightmaps, light, block entities
- Real connection to a Horizon LAN server (200+ ticks without disconnect)

**World** — reads the world:
- `BlockRegistry` (35723 block states), NBT, chunk palettes, collision shapes
- Block properties, survival rules, fluid flow

**Player** — client-side simulation:
- Motion (gravity, travel, jump, fly, swim, climb, fall damage, landing)
- Health, effects, combat, totem
- Item usage (catalog, lifecycle, after-use), inventory, containers
- Block placement, block survival (break + drops), raycast

**Control server** (`--daemon`) — remote control over TCP:
- JSON-lines protocol, commands: `move`, `jump`, `sneak`, `sprint`, `fly`, `look`, `state`, `stop`
- `quadrixctl.py` — CLI client (REPL) for interactive control
- Multiple `quadrixctl` instances can connect in parallel

## What does NOT work (yet)

- **Chat** and **place/break** over control server — in progress
- Enchantments, potions, food — partial (FALLBACK)
- Signed chat (1.19+ online-mode) — not started
- Commands / command parsing — not started

## Roadmap (in planning — no promise)

The long-term goal is a full port of Horizon. Planned, but not guaranteed to be finished:

- **Rendering** — wgpu/moderngl backend, chunk meshing, textures, lighting
- **GUI** — ImGui-based (menu, inventory, chat)
- **Mobs** — AI, pathfinding, animation
- **Worldgen** — biomes, structures, features
- **Gameplay** — enchantments, potions, food, commands, signed chat

Whether these are playable depends on optimization. Python may not be fast enough for smooth rendering.
The project will try, and stop if it is not viable.

## Setup

QuadRix does **not** ship Minecraft assets. You must own Minecraft: Java Edition and generate the assets yourself:

1. Clone the Rust client (read-only reference):
   ```bash
   git clone https://github.com/horizon-rust/horizon horizon
   ```
2. Run `horizon-prepare` from that repo to generate `.local/` (textures, NBT data, etc.).
3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run:
   ```bash
   python quadrix.py --host localhost --port 25565 --name QuadRix --offline-mode
   ```

### Control server

Run the client as a daemon (keeps the connection, listens on TCP `:25566`):

```bash
python quadrix.py --daemon --host localhost --port 25565 --name QuadRix --offline-mode
```

In another terminal, control it:

```bash
python quadrixctl.py
```

```
quadrix> state
quadrix> move forward 20
quadrix> jump
quadrix> stop
```

## Layout

```
quadrix/          Python port (this repo)
  core/           geometry, math, text
  world/          registry, chunk, collision, block_placement, block_survival
  motion/         player motion (gravity, travel, jump, fly, swim)
  items/          item registry, components, tools
  protocol/       buf, ids, crypto, connection, packets/
  control/        TCP control server (JSON-lines)
quadrix.py        client entry point (CLI)
quadrixctl.py     control CLI (REPL)
horizon/          Rust original (read-only reference, not committed)
.local/           Generated assets (not committed, see .gitignore)
tests/            pytest suite (711+ tests)
PORTING_STATE.yaml detailed porting status
```

## Tests

```bash
python -m pytest tests/ -q
```

Current: **711+ passed, 0 failed**.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Each porting session ports **one Rust file** to Python, with tests.

## License

MIT — see [`LICENSE`](LICENSE).

**Not affiliated with Mojang or Microsoft.** "Minecraft" is a trademark of Mojang Synergies AB. QuadRix contains no Mojang code or assets.