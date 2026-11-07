# QuadRix

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Status: early port](https://img.shields.io/badge/status-early%20port-orange.svg)](PORTING_STATE.yaml)

**QuadRix** is a Python port of [Horizon](https://github.com/horizon-rust/horizon) (Rust Minecraft client).

> **Status:** early port. Only the foundation is being ported. See [`PORTING_STATE.yaml`](PORTING_STATE.yaml) for progress.

## Why

Horizon is a full Minecraft client in Rust (~22 MB source, ~700 files). QuadRix ports it to Python so it can run where Rust cannot (or where Python is preferred).

## What works

Nothing yet. The port is in progress:
- [ ] `horizon-core` (Vec3, Aabb, BlockPos, Direction)
- [ ] `horizon-world` (NBT, BlockRegistry)
- [ ] `horizon-client` (motion, fluids, environment)
- [ ] network (`player_sync`, packets)

## What does NOT work

- Rendering
- Mobs
- UI
- Multiplayer

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
   python quadrix.py
   ```

## Layout

```
quadrix/          Python port (this repo)
horizon/          Rust original (read-only reference, not committed)
.local/           Generated assets (not committed, see .gitignore)
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Each porting session ports **one Rust file** to Python, with tests.

## License

MIT — see [`LICENSE`](LICENSE).

**Not affiliated with Mojang or Microsoft.** "Minecraft" is a trademark of Mojang Synergies AB. QuadRix contains no Mojang code or assets.