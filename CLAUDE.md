# CLAUDE.md

## Project overview

`id-translation` is a Python library for translating database IDs into human-readable labels. It supports multiple ID
types (int, str, UUID), collection types (list, dict, DataFrame, etc.), and data sources (SQL, CSV, in-memory).

**Package import:** `id_translation`

## Related repositories

- **`id-translation-project`** (`../id-translation-project/`, https://github.com/rsundqvist/id-translation-project/) — the
  official cookiecutter template for adopters. A generated project ships `create_translator()` wrappers, a bundled
  config, and a test suite that doubles as a config CI gate. **Before building onboarding/adoption tooling here**
  (CLIs, validators, bootstrappers), check what it already provides — read its `CLAUDE.md` for the full rundown.

## Build and run

```bash
# Install
uv sync --all-extras

# Run full test suite
uv run inv tests

# Run pytest directly
uv run pytest tests/ -x -q

# Lint
uv run inv lint

# Type check
uv run inv mypy

# Build the docs (also generates llms.txt / llms-full.txt)
uv run inv docs

# Start the dvdrental Docker databases (needed by tests/dvdrental/)
./run-docker-dvdrental.sh
```

Always use `uv run` to execute commands. The `tests/dvdrental/` suite fails with an explicit message naming the
script above when the databases aren't running.

Dev uses **regular CPython 3.14** (pinned in `.python-version`; matches CI and Read the Docs). Avoid 3.13 (the docs
build crashes in a `rics` Sphinx patch) and the free-threaded `3.14t` build (some deps such as `pymssql` have no
wheels for it).

## Code layout

Source uses a **src-layout** (`src/id_translation/`); the public API is re-exported from `__init__.py` files.
Module-level docstrings describe each subpackage. Tests mirror the `src/` structure.

## Key concepts

Read source for API details, but the mapping/fetching vocabulary (names, sources, placeholders — and their
`Mapper` aliases values, candidates, context) and the TOML config grammar are *not* recoverable from signatures.
Read the narrative docs before non-trivial work: `docs/documentation/translation-primer.rst`,
`translator-config.rst`, and `mapping-primer.rst`.

## Conventions

- **Typing style:** Heavy use of generics (`Generic[NameType, SourceType, IdType]`), `@overload`, and PEP 604
  unions (`X | Y`). Google-style docstrings. Guard type-checking-only imports with `if TYPE_CHECKING:`.
- **Log extras must be JSON-serializable** (enforced by test fixtures; use `sorted()` or `list()` to convert sets).
- **Private naming:** Leading underscore for internal modules, functions, and fields.
- **Types per module:** Each subpackage has its own `types.py` and `exceptions.py`.

## Commits

- **Group by area of concern:** one commit per concern; keep unrelated changes apart.
- **Refine with `fixup!`, don't rewrite:** when a later change reworks an earlier commit, record it
  as a `fixup!` commit (`git commit --fixup=<sha>`) instead of amending the original.
- **Never rebase on your own:** don't run the autosquash — the unsquashed history is useful during
  development. Rebase only when explicitly instructed.
- **Isolate disposable notes:** keep scratch/working notes (e.g. an `adoption-notes/` folder or `claude-todos.txt` file)
  in their own standalone commits, separate from real code/docs, so they can be dropped later.
- **Write lean messages:** state the *why* and any non-obvious *what*; omit whatever the diff shows.
  Prefer a single-line message when the subject already conveys the why. No mechanical consequences
  (renames, updated references, call-site fixups), and no "verified"/"tests pass"/"build clean" lines.
