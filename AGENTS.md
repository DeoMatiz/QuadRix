# QuadRix — Porting Rules (Horizon Rust → Python)

## Mission

Port Horizon (Rust Minecraft client) to `quadrix/` (Python 3.11+).

**Short-term:** a **playable headless client** — connects to a server, moves, places/breaks blocks,
manages inventory, controllable over TCP (`--daemon` + `quadrixctl.py`). This is what sessions currently work on.

**Long-term:** a **full port** — rendering, GUI, mobs, worldgen, gameplay. This is **in planning and not
guaranteed**. Python is 50–100× slower than Rust for hot paths (chunk meshing, entity AI, render loop).
Whether a full port is playable depends on optimization (numpy, Cython, native extensions).
The project will try, and stop if it is not viable. Do not promise a finished full port.

You are NOT writing Minecraft from scratch. You are translating Rust to Python, function by function.
Data files (`.nbt`, `.json`, `.png`) are ALREADY GENERATED in `.local/`. You only port CODE that READS them.

## Repository

- GitHub: `https://github.com/DeoMatiz/QuadRix`
- Default branch: `main`
- Python package: `quadrix/` (lowercase, no capital R)
- Entry point: `quadrix.py`
- Control CLI: `quadrixctl.py`
- Display name: `QuadRix` (capital Q, capital R)

## The `.local` layout (FIXED, do not change)

```
.local/
├── horizon-client/26.3/assets/minecraft/     ← textures, lang, sounds, entity-models.json
├── horizon-client-motion/                    ← movement-properties.nbt, cached-collision.nbt,
│                                                block-registry.nbt, landing-definitions.json,
│                                                landing-states.json, tags.json, classes/
├── horizon-client-collision/                 ← cached-collision.nbt, block-registry.nbt, classes/
├── horizon-client-health/                    ← health data (read from Rust)
├── horizon-client-block-behavior/            ← block behavior data
├── horizon-client-render/                    ← render data (for future render port)
├── horizon-client-structures/                ← structures
├── command-registries/                       ← command registries
└── minecraft/                                ← vanilla jars, only for horizon-prepare
```

QuadRix reads these paths EXACTLY. Never invent new paths.
If Rust does `root.join("horizon-client-motion")`, Python does `Path(".local/horizon-client-motion")`.

## Golden Rules

1. **One Rust file per session.** Read it entirely first.
2. **Read `.nbt` layout from Rust.** The `.nbt` files are binary. Rust has the reader
   (`horizon-world/src/nbt.rs`). Port it FIRST before porting any consumer.
3. **Never stub data.** If Rust does `read_dat("movement-properties.nbt")`, Python does the same.
   Not `return {}`.
4. **Preserve constants.** Rust `0.08` → Python `0.08`. Rust `240 | 240 << 8` → Python `240 | 240 << 8`.
5. **Preserve function names** (`snake_case`). Structs → `@dataclass`.
6. **Tests required.** Each ported module gets `tests/test_<name>.py`. At least 3 concrete assertions.
7. **No `pass`, no `TODO`, no `NotImplementedError`.** If blocked → write `BLOCKED: <reason>`
   in `PORTING_STATE.yaml` and move on. If a dependency is pending, use `# FALLBACK: <name> pending`
   and return a sensible default — but say so in `PORTING_STATE.yaml`.
8. **Large subsystems are NOT forbidden, but are LOW PRIORITY and PARTed.** `render/`, `mobs.rs`,
   `game.rs`, `menu.rs`, `title.rs`, `lan/`, `save/` — do not port in a session unless explicitly asked.
   When asked, split into PARTs (PART 1, PART 2, ...), one PART per session.
   Rationale: full port is a long-term goal, not guaranteed — depends on Python performance. See "Full Port" below.
9. **Log prefix.** Any print/log from QuadRix starts with `[QuadRix]`.
10. **No `PyCraft` anywhere.** Replace all `PyCraft` with `QuadRix` (capital R).

## Translation Table

| Rust | Python |
|---|---|
| `struct X { a: f64 }` | `@dataclass class X: a: float` |
| `enum E { A, B(i32) }` | `class E(Enum): A; B` + payload dataclass |
| `Result<T, E>` | `def f() -> T` + `raise` |
| `Option<T>` | `Optional[T]` |
| `Vec<T>` | `list[T]` |
| `HashMap<K, V>` | `dict[K, V]` |
| `f64::from(x)` | `float(x)` |
| `x.floor() as i32` | `int(math.floor(x))` |
| `?` operator | `if err: raise err` |
| `#[derive(Default)]` | `field(default_factory=...)` |
| `impl X { fn f(&self) }` | `class X: def f(self)` |
| `glam::Vec3` | plain Python `Vec3` dataclass (do not import glm) |
| `trait X` | `class X(Protocol)` |
| `Arc<Mutex<T>>` | plain object (Python GIL) or `threading.Lock` if cross-thread |

## Reading Rust NBT / JSON data

Many constants live in `.local/horizon-client-motion/*.nbt` and `.json`. Do not hardcode them.
Rust reads them via `horizon-world::nbt::read_dat(...)` and `serde_json::from_str(...)`.

When porting a file that reads data:
1. Find the Rust `read_dat` / `from_str` / `include_bytes!` call.
2. Write the Python loader in `quadrix/assets.py` that reads the same path with the same key.
3. Add a test that loads the real file from `.local` and asserts on 1–2 known values.

Example:
```rust
let props = horizon_world::nbt::read_dat(&root.join("movement-properties.nbt"))?;
```
Python:
```python
from quadrix.world.nbt import read_dat
props = read_dat(Path(".local/horizon-client-motion/movement-properties.nbt"))
```

## Session Workflow

1. Read `PORTING_STATE.yaml`. Pick the **first** `status: pending` whose `depends_on` are all `done`.
2. Read the full Rust source file.
3. Read any `.nbt` / `.json` file it references.
4. Translate to `quadrix/<path>.py`.
5. Write `tests/test_<name>.py`. Load real `.local` data in at least one test.
6. Run `pytest tests/test_<name>.py -v`. Must pass.
7. Run full regression `pytest tests/ -q`. Must be 0 failed.
8. Update `PORTING_STATE.yaml`: `status: done`, add `python_path`, `test_path`, `lines_python`, `note`.
9. Commit and push (see "Git workflow").
10. Output **only**: python file + test file + YAML diff + pytest output.

## Git workflow

```
git add quadrix/... tests/... PORTING_STATE.yaml
git commit -m "port: <file> (<functions>, N tests)"
git push
```

Do not commit: `.gitignore` (unless intentional), `pytest_out.txt`, `test_output.txt`, `_*.py` debug files,
`DONE.txt`. Clean them before commit (`del` on Windows).

## Control server (quadrix.py --daemon + quadrixctl.py)

This is a **new feature**, not a Rust port. Lives in `quadrix/control/server.py` + `quadrixctl.py`.

- Protocol: JSON-lines over TCP (`:25566` default). One JSON request per line, one JSON response per line.
  Request: `{"id": N, "cmd": "...", "args": {...}}`. Response: `{"id": N, "ok": bool, "result": ..., "error": ...}`.
- Threading, not asyncio. The main client is sync.
- `poll()` runs in the main tick loop; connection threads push commands into a `queue.Queue`.
- Commands: `move`, `jump`, `sneak`, `sprint`, `fly`, `look`, `state`, `stop`. Chat/place/break — in progress.
- **Movement must go through `Client.tick()`**, not bypass it: control sets `client.pending_input` /
  `client.pending_input_ticks`, the tick loop calls `travel` + `tick` + `sync_client_to_server`.
  Directly calling `PlayerMotion.travel` outside the loop desyncs from the server.

## Full Port — Long-Term Goal (not guaranteed)

The project aims to eventually port **all** of Horizon. However:

1. **Python performance is the bottleneck.** Hot paths (chunk meshing, entity AI, render loop) may need
   numpy, Cython, or native extensions. If a subsystem cannot be made playable, it is not ported.
2. **Priority order:**
   - Playable core — **done**
   - Control server (chat / place / break) — in progress
   - Chat / commands — next
   - Enchant / potions / food / effects (full) — next
   - Rendering — planned, after core is stable
   - GUI — planned, depends on rendering
   - Mobs — planned, low priority
   - Worldgen — planned, lowest priority
3. **Render backend:** `wgpu-py` (Vulkan / Metal / DX12, like Horizon) is preferred; `moderngl` (OpenGL) is a fallback.
   Horizon supports multiple backends — QuadRix should do the same (switchable render engine).
4. **GUI:** ImGui via `dearpygui` (or an `imgui` wrapper). Same style as Horizon's menu.
5. **Window:** `glfw` (like Horizon) or `pyglet`.
6. **Optimization:** numpy for chunks and bulk array ops; Cython / numba for hot loops. Pure Python
   will be too slow for render.
7. **No promises.** The project may stop at "headless client with control server" if full render is not viable.
   That is an acceptable outcome. Do not overpromise in docs or commit messages.
8. **When porting a large subsystem:** split into PARTs. Each PART is a separate session. Do not try to
   port `render/` or `mobs.rs` in one session.

## Forbidden

- Do not rewrite `horizon/` — it is read-only reference.
- Do not invent constants. All constants come from Rust or from `.nbt` / `.json`.
- Do not use `asyncio` unless Rust uses `async`. `motion.rs`, `fluids.rs`, `environment.rs` are **sync**.
- Do not import from `horizon` (Rust source, read-only) or from any old `pycraft` package.
- Do not use the word `PyCraft` anywhere. Use `QuadRix`.
- Do not silently stub data or behavior. If blocked — `# FALLBACK: <reason>` + note in `PORTING_STATE.yaml`.
- Do not bypass `Client.tick()` for movement (see "Control server" above).

## Order of porting (do not skip)

**Done:**
1. `horizon-core/src/geometry.rs` — Vec3, Aabb, Direction, BlockPos
2. `horizon-world/src/nbt.rs` — NBT reader
3. `horizon-world/src/registry.rs` — reads `block-registry.nbt`
4. `entities/fluids.rs`, `motion/fluids.rs`, `motion/environment.rs`
5. `motion.rs` — `PlayerMotion`, gravity, walk, jump, fly, swim, climb, fall damage
6. `horizon-protocol` — buf, ids, crypto, connection, 144 CB + 69 SB packets
7. `player_sync.rs`
8. `items/` — registry, components (partial), tools
9. `health.rs`, `effects.rs`, `combat.rs`, `totem.rs`
10. `world/chunk.py`, `heightmap`, `collision`
11. `block_placement.rs`, `block_survival.rs`, `world_ray.rs`
12. `item_use*.rs`, `inventory_use.rs`, `simple_container.rs`, `player_inventory.rs`

**Next (playable core completion):**
13. Control server: `chat` (send `play.Chat`), `place` / `break` (raytrace + placement/survival) — fix bypass
14. Chat / commands parsing
15. Enchant / potions / food / effects (full)

**Later (full port — PARTed, low priority):**
16. Render (PART 1..N) — wgpu-py or moderngl backend
17. GUI (PART 1..N) — ImGui
18. Mobs (PART 1..N) — AI, pathfinding, animation
19. Worldgen (PART 1..N) — biomes, structures, features
20. Save / LAN (if ever)

## `motion.rs` is 256 KB. How to port it

Do NOT port the whole file. Instead:

1. Find `impl PlayerMotion`.
2. Port only these methods one session each:
   - `PlayerMotion::new`
   - `PlayerMotion::tick` (gravity, ground check)
   - `PlayerMotion::travel` (walk/sprint/sneak)
   - `PlayerMotion::jump_from_ground`
   - `PlayerMotion::fly`
3. For each method, write a test that loads `movement-properties.nbt` and asserts one concrete case
   (e.g., walk speed = 0.215 blocks/tick).

## Windows shell notes

Commands used in sessions run in `cmd.exe` on Windows, not bash:

- Use `dir`, `type`, `del`, `findstr`, `powershell -Command "Get-Content ... | Select-Object -Skip N -First M"`.
- Do NOT use `&&`, `||`, `grep`, `tail`, `ls -la` — they are not available.
- Pytest output: `python -m pytest tests/ -q > pytest_out.txt 2>&1`, then `type pytest_out.txt`, then `del pytest_out.txt`.
- Encoding: `.yaml` files are UTF-8; `type` in cmd may show Russian as `╨╛╤А╤В...`. That is a display issue, not a file issue.