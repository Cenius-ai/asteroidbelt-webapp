# Using asteroidbelt

## Overview

Eyepiece magnifications, Messier viewing windows and per-session target mark-off

## Quickstart

```bash
asteroidbelt --help
# or, if installed from source without symlink:
python -m asteroidbelt --help
```

## Commands

This CLI exposes **12** subcommands. Each was extracted from the source.

| Command | Source file |
|---------|-------------|
| `asteroidbelt add` | `asteroidbelt.py` |
| `asteroidbelt config` | `asteroidbelt.py` |
| `asteroidbelt eyepieces` | `asteroidbelt.py` |
| `asteroidbelt list` | `asteroidbelt.py` |
| `asteroidbelt mark` | `asteroidbelt.py` |
| `asteroidbelt remove` | `asteroidbelt.py` |
| `asteroidbelt session` | `asteroidbelt.py` |
| `asteroidbelt set` | `asteroidbelt.py` |
| `asteroidbelt show` | `asteroidbelt.py` |
| `asteroidbelt start` | `asteroidbelt.py` |
| `asteroidbelt targets` | `asteroidbelt.py` |
| `asteroidbelt unmark` | `asteroidbelt.py` |

### Per-command help

```bash
asteroidbelt --help                # top-level help
asteroidbelt add --help    # help for `add`
```

## Worked example

1. Verify the CLI is on your PATH: `which asteroidbelt` (or run via `cargo run --`/`python -m`).
2. Show all subcommands: `asteroidbelt --help`.
3. Try the first detected subcommand:

```bash
asteroidbelt add --help
```

## Reference

### Entry points

| Kind | Name | Source |
|------|------|--------|
| Console script | `asteroidbelt` | `asteroidbelt:main` (pyproject.toml) |

### Surface index (auto-extracted)

| Kind | Title | Source file |
|------|-------|-------------|
| command | `add` | `asteroidbelt.py` |
| command | `config` | `asteroidbelt.py` |
| command | `eyepieces` | `asteroidbelt.py` |
| command | `list` | `asteroidbelt.py` |
| command | `mark` | `asteroidbelt.py` |
| command | `remove` | `asteroidbelt.py` |
| command | `session` | `asteroidbelt.py` |
| command | `set` | `asteroidbelt.py` |
| command | `show` | `asteroidbelt.py` |
| command | `start` | `asteroidbelt.py` |
| command | `targets` | `asteroidbelt.py` |
| command | `unmark` | `asteroidbelt.py` |

## Next steps

- Read [INSTALL.md](./INSTALL.md) if anything in the Quickstart didn't work.
- Inspect `.env.example` for the full list of environment variables this project understands.
- See [README.md](./README.md) for the architecture diagram + feature list.
