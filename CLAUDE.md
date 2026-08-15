# CLAUDE.md

## Project overview

`id-translation` is a Python library for translating database IDs into human-readable labels. It supports multiple ID
types (int, str, UUID), collection types (list, dict, DataFrame, etc.), and data sources (SQL, CSV, in-memory).

## Related repositories

- **`id-translation-project`** (`../id-translation-project/`, https://github.com/rsundqvist/id-translation-project/) — the
  official cookiecutter template for adopters. A generated project ships `create_translator()` wrappers, a bundled
  config, and a test suite that doubles as a config CI gate. **Before building onboarding/adoption tooling here**
  (CLIs, validators, bootstrappers), check what it already provides — start with its `README.md` and
  `{{cookiecutter.project_slug}}/`.
- **`rics`** (`../rics/`) — upstream dependency; also supplies the Sphinx patches this docs build relies on. A docs
  build that breaks without a local docs change usually broke there.

## Build and run

Run everything through `uv run`; `uv run inv --list` has the full task list. The non-obvious parts:

- **`inv mypy`, not `mypy src/id_translation`** — the task covers `tests/` too, and test-only type errors are
  otherwise invisible.
- **`inv tests` runs `--xdoctest` over `src/` as well as `tests/`** — a stale `>>>` example in a docstring fails
  the suite.
- **`inv docs` builds with `-W`** and generates `llms.txt` / `llms-full.txt`. RTD sets `fail_on_warning: true`.
- **`./run-docker-dvdrental.sh`** starts the databases `tests/dvdrental/` needs. That suite fails with an explicit
  message naming the script when they aren't running.

## Docs build

`.python-version` and `.readthedocs.yml` both pin **regular CPython 3.14**, and the build only works there:
`rics`'s `_internal_support/` monkeypatches `Autosummary.run` with a `functools.partial`, which became a method
descriptor in 3.14. Under 3.11-3.13 the build dies on a missing `self` argument, masking the real Sphinx warnings.
Avoid the free-threaded `3.14t` build for the venv generally — some deps (`pymssql`) have no wheels for it.

`nitpicky = True` makes an unresolved xref a hard error. A type alias used in a public signature must live in a
*documented* module, not a private one.

## Key concepts

Read source for API details, but the mapping/fetching vocabulary (names, sources, placeholders — and their
`Mapper` aliases values, candidates, context) and the TOML config grammar are *not* recoverable from signatures.
Read the narrative docs before non-trivial work: `docs/documentation/translation-primer.rst`,
`translator-config.rst`, and `mapping-primer.rst`.

## Conventions

Ruff enforces the mechanical rules (Google docstrings, PEP 604 unions, import order, `TYPE_CHECKING` guards) — run
`inv lint` rather than matching style by eye. Beyond that:

- **Heavy generics:** `Generic[NameType, SourceType, IdType]` and `@overload` throughout; match the existing
  parameterization when extending public API.
- **Log extras must be JSON-serializable** (enforced by test fixtures; use `sorted()` or `list()` to convert sets).
- **Types per module:** each subpackage has its own `types.py` and `exceptions.py` — put new ones there.

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
