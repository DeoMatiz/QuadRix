# Contributing to QuadRix

## Porting workflow

QuadRix is a **file-by-file** port of Horizon (Rust). We do not rewrite logic. We translate.

1. Read `AGENTS.md` — the porting rules.
2. Read `PORTING_STATE.yaml` — the current progress.
3. Pick the first `status: pending` whose `depends_on` are all `done`.
4. Port **one file**. Write tests. Run `pytest`.
5. Update `PORTING_STATE.yaml`.
6. Open a PR.

## Rules

- **One Rust file per PR.** Do not port multiple files at once.
- **No `pass`, no `TODO`, no `NotImplementedError`.** If blocked, write `BLOCKED: <reason>` in `PORTING_STATE.yaml`.
- **Tests required.** Each ported module gets `tests/test_<name>.py`.
- **Preserve constants.** Rust `0.08` → Python `0.08`. Not `0.1`.
- **Do not commit `.local/` or `horizon/`.** They are ignored.
- **Never read `game.rs`, `mobs.rs`, `lan/`, `menu.rs`, `title.rs`.** Too big.

## Setup

See `README.md`.

## License

By contributing, you agree your work is licensed under MIT (see `LICENSE`).