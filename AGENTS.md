# AGENTS.md
## Project overview
`id-translation` is a Python library for translating database IDs into human-readable labels. It supports multiple ID types (int, str, UUID), collection types (list, dict, DataFrame, etc.), and data sources (SQL, CSV, in-memory).

**Package import:** `id_translation`

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
```
Always use `uv run` to execute commands.

## Code layout
```
src/id_translation/       # Main package (src-layout)
  _translator.py           # Core Translator class
  fetching/                # Data source interfaces (AbstractFetcher, SqlFetcher, etc.)
  mapping/                 # Name-to-source mapping logic
  offline/                 # Format strings, TranslationMap
  dio/                     # Data I/O (pandas, polars, dask, pyarrow integrations)
  toml/                    # TOML config + TranslatorFactory
  types.py                 # Shared type definitions
tests/                    # Mirrors src structure
  dvdrental/               # Live database tests (require Docker)
```
Internal modules use a leading underscore (e.g. `_translator.py`). Public API is re-exported from `__init__.py` files.

## Conventions
- **Style:** Ruff for linting and formatting. Line length 120. Google-style docstrings.
- **Typing:** MyPy strict mode. Heavy use of generics (`Generic[NameType, SourceType, IdType]`), `@overload`, PEP 604 unions (`X | Y`).
- **Type-checking imports:** Guard with `if TYPE_CHECKING:`.
- **Tests:** pytest with xdoctest. 90% coverage minimum. Warnings treated as errors.
- **Log extras must be JSON-serializable** (enforced by test fixtures; use `sorted()` or `list()` to convert sets).
- **Private naming:** Leading underscore for internal modules, functions, and fields.
- **Types per module:** Each subpackage has its own `types.py` and `exceptions.py`.
