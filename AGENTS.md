# Horizon → QuadRix Porting Rules

## Mission
Port `horizon/crates/horizon-client/src/` + `horizon-core` + `horizon-world` + `horizon-protocol`
to `quadrix/` (Python 3.11+).

You are NOT writing Minecraft from scratch. You are translating Rust to Python, function by function.
Data files (`.nbt`, `.json`, `.png`) are ALREADY GENERATED in `.local/`. You only port CODE that READS them.

## Project name: QuadRix
Always written `QuadRix` — capital Q, capital R, the rest lowercase.
- Python package: `quadrix` (lowercase, no R)
- Entry point: `quadrix.py`
- Config file: `quadrix.toml`
- Env vars: `QUADRIX_*` (all caps)
- CLI: `quadrix`
- Class prefix if any: `QR` (e.g. `QRWorld`, `QRPlayer`)

## Renaming rule: `PyCraft` → `QuadRix`
Anywhere you see the string `PyCraft` (old project name) — replace with `QuadRix` (capital R).
- Docstring comments: `# PyCraft` → `# QuadRix`
- Log prefixes: `[PyCraft]` → `[QuadRix]`
- Class names: `PyCraftGame` → `QuadRixGame`
- Directory names: `pycraft/` → `quadrix/`
- Package imports: `from pycraft.x` → `from quadrix.x`
- Old save format: `saves/` stays, but print as `[QuadRix] saves/...`

Do NOT change `PyPI`, `pytest`, `python`, `PyObject`, `Py_*` C-API names — only the word `PyCraft`.

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
├── horizon-client-render/                    ← render data
├── horizon-client-structures/                ← structures
├── command-registries/                       ← command registries
└── minecraft/                                ← vanilla jars, only for horizon-prepare
```

QuadRix reads these paths EXACTLY. Never invent new paths. If Rust does `root.join("horizon-client-motion")`, Python does `Path(".local/horizon-client-motion")`.

## Golden Rules
1. **One Rust file per session.** Read it entirely first.
2. **Read `.nbt` layout from Rust.** The `.nbt` files are binary. Rust has the reader (`horizon-world/src/nbt.rs`). Port it FIRST before porting any consumer.
3. **Never stub data.** If Rust does `read_dat("movement-properties.nbt")`, Python does the same. Not `return {}`.
4. **Preserve constants.** Rust `0.08` → Python `0.08`. Rust `240 | 240 << 8` → Python `240 | 240 << 8`.
5. **Preserve function names** (`snake_case`). Structs → `@dataclass`.
6. **Tests required.** Each ported module gets `tests/test_<name>.py`. At least 3 assertions on concrete values.
7. **No `pass`, no `TODO`, no `NotImplementedError`.** If blocked → write `BLOCKED: <reason>` in `PORTING_STATE.yaml` and move on.
8. **Do NOT read `game.rs`, `mobs.rs`, `lan/`, `menu.rs`, `title.rs`.** Too big (1 MB+). Skip.
9. **Log prefix.** Any print/log from QuadRix starts with `[QuadRix]`.

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
1. Read `PORTING_STATE.yaml`. Pick the first `status: pending` whose `depends_on` are all `done`.
2. Read the full Rust source.
3. Read any `.nbt` / `.json` file it references.
4. Translate to `quadrix/<path>.py`.
5. Write `tests/test_<name>.py`. Load real `.local` data in at least one test.
6. Run `pytest tests/test_<name>.py -v`. Must pass.
7. Update `PORTING_STATE.yaml`: `status: done`, add `python_path`, `test_path`, `lines_python`.
8. Output ONLY: python file + test file + YAML diff.

## Forbidden
- Do not read `game.rs`, `mobs.rs`, `lan/`, `title.rs`, `menu.rs`.
- Do not invent constants. All constants come from Rust or from `.nbt`/`.json`.
- Do not use `asyncio` unless Rust uses `async`. `motion.rs`, `fluids.rs`, `environment.rs` are sync.
- Do not import from `horizon` or from `pycraft` (old project). QuadRix is standalone in `quadrix/`.
- Do not rewrite `horizon/` — it is read-only reference.
- Do not use the word `PyCraft` anywhere. Use `QuadRix`.

## Order of porting (do not skip)
1. `horizon-core/src/geometry.rs` — Vec3, Aabb, Direction, BlockPos
2. `horizon-world/src/nbt.rs` — NBT reader (necessary for `.nbt` in `.local`)
3. `horizon-world/src/registry.rs` — reads `block-registry.nbt`
4. `entities/fluids.rs` — water/lava interaction (reads `movement-properties.nbt`)
5. `motion/fluids.rs` — swimming, currents
6. `motion/environment.rs` — fire, drowning
7. `motion.rs` — ONLY `PlayerMotion`, gravity, walk, jump, fly (leave the rest for later)
8. `player_sync.rs` — network packet (needs `horizon-protocol/src/packets/play.rs` ported first)

## `motion.rs` is 256 KB. How to port it
Do NOT port the whole file. Instead:
1. Find `impl PlayerMotion`.
2. Port only these methods one session each:
   - `PlayerMotion::new`
   - `PlayerMotion::tick` (gravity, ground check)
   - `PlayerMotion::travel` (walk/sprint/sneak)
   - `PlayerMotion::jump_from_ground`
   - `PlayerMotion::fly`
3. For each method, write a test that loads `movement-properties.nbt` and asserts one concrete case (e.g., walk speed = 0.215 blocks/tick).