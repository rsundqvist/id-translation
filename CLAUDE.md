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
- **`uv run nox`** runs the CI matrix locally: `tests-3.11` … `tests-3.14` plus `mypy-3.*`. Use it to catch the
  version-specific breakage a single-interpreter run cannot — a bare `sys.version_info` assert, a 3.11-only syntax
  gap. `uv run nox -s tests-3.11` runs one session. Check the result, not the exit code of a pipeline ending in
  `tail`: a multi-session run prints `* tests-3.11: failed` per session, a single-session run only
  `Session tests-3.11 failed` — and a session killed by the interpreter assert says **`aborted`**, not
  `failed`. That assert is what stops a wrong interpreter quietly testing the same version four times.
  `uv run` bootstraps the outer `.venv` *unlocked* before nox starts, so run `uv sync --locked --all-extras`
  first (as CI does) if you want lockfile drift to be refused rather than silently written.

## Running alongside other agents

Several paths are shared process-wide, so parallel test runs (multiple agents, or nox beside a manual run) corrupt
each other silently. Give each run its own:

- **`pytest.log`** — `pyproject.toml` sets `log_file`, and `--log-file-mode` defaults to `w`, so concurrent runs
  *truncate* each other. Override with `PYTEST_ADDOPTS="--log-file=..."`, which reaches the inner `uv run pytest`
  even when you invoke `inv tests`.
- **`.coverage`** — `inv tests` passes `--cov-append`, so a second run inflates the first's totals. Set
  `COVERAGE_FILE=...`; nox sessions honour it in preference to their own per-version name, which also
  means all four `tests` sessions then share one file and you lose the per-version split.
- **`.nox/`** — sessions of the same name share one venv, so two concurrent runs sync over each other.
  Pass `--envdir ...`.
- **`.mypy_cache`** — not concurrency-safe within a version. Set `MYPY_CACHE_DIR=...`.
- **`.venv`** — `uv run --python <version>` retargets the project venv, and `uv sync --active` recreates it. Both
  change the interpreter under any run already in flight. Build a throwaway venv elsewhere instead.
- **`docs/_build`, `docs/api`** — `inv docs` regenerates both; two builds at once interleave.

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
