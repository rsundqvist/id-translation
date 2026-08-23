import builtins
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


class TestInitializeWithoutDependency:
    def test_pandas_fetcher(self, pandas_missing):
        from id_translation.fetching import PandasFetcher

        match = re.escape("Install `pandas` or `id-translation[fetching]` to use PandasFetcher.")
        with pytest.raises(ImportError, match=match):
            PandasFetcher()

    def test_sql_fetcher(self, sqlalchemy_missing):
        from id_translation.fetching import SqlFetcher

        match = re.escape("Install `sqlalchemy` or `id-translation[fetching]` to use SqlFetcher.")
        with pytest.raises(ImportError, match=match):
            SqlFetcher("connection-string")


class TestOptionalFetchers:
    def test_all_missing(self, pandas_missing, numpy_missing, sqlalchemy_missing, fsspec_missing):
        from id_translation import Translator
        from id_translation.dio import get_resolution_order

        translator = Translator[str, str, int](fetcher={"source": {1: "one!"}})
        assert translator.translate(1, "source") == "1:one!"
        assert translator.translate([1], "source") == ["1:one!"]  # SequenceIO numpy-free branch.

        # The entrypoint loader must have *skipped* integrations whose modules import hidden packages, while still
        # loading those that do not (polars is a required test dependency, so its absence here would be a bug too).
        loaded = {io.__module__.rpartition(".")[2] for io in get_resolution_order()}
        assert "pandas" not in loaded
        assert "dask" not in loaded
        assert {"_dict", "_sequence", "_set", "_single_value", "polars"} <= loaded

    def test_pandas_without_fsspec(self, tmp_path, sqlalchemy_missing, fsspec_missing):
        from id_translation import Translator
        from id_translation.fetching import PandasFetcher

        tmp_path.joinpath("source.json").write_text('{"id": [1], "name": ["one!"]}')
        fetcher = PandasFetcher[int](read_path_format=str(tmp_path / "{}.json"))

        translator = Translator[str, str, int](fetcher)
        assert translator.translate(1, "source") == "1:one!"

    def test_sqlalchemy_without_pandas(self, tmp_path, pandas_missing, numpy_missing):
        from sqlalchemy import create_engine, text

        from id_translation import Translator
        from id_translation.fetching import SqlFetcher

        connection_string = f"sqlite:///{tmp_path}.db"
        with create_engine(connection_string).connect() as conn:
            conn.execute(text("CREATE TABLE source(id INTEGER, name TEXT);"))
            conn.execute(text("INSERT INTO source VALUES(1, 'one!');"))
            conn.commit()

        fetcher = SqlFetcher[int](connection_string)
        translator = Translator[str, str, int](fetcher)
        assert translator.translate(1, "source") == "1:one!"


class TestFloatCoercion:
    """Numpy is used for performance reasons in a few places."""

    def test_without_numpy(self, numpy_missing, monkeypatch):
        from id_translation import Translator
        from id_translation._tasks import TranslationTask
        from id_translation.fetching import MemoryFetcher

        real = TranslationTask._coerce_float_to_int

        calls = 0

        def fake(_, ids):
            nonlocal calls
            calls += 1

            with pytest.raises(ModuleNotFoundError) as exc_info:
                return real(ids)

            raise exc_info.value

        monkeypatch.setattr(TranslationTask, "_coerce_float_to_int", fake)

        translator = Translator[str, str, int](fetcher=MemoryFetcher(data={"source": {1: "one!"}}))
        assert translator.translate([1.0], "source") == ["1:one!"]
        assert calls == 1

    def test_with_numpy(self, monkeypatch):
        import numpy as np

        from id_translation import Translator
        from id_translation._tasks import TranslationTask
        from id_translation.fetching import MemoryFetcher

        real = TranslationTask._coerce_float_to_int

        calls = 0

        def fake(_, ids):
            nonlocal calls
            calls += 1

            return real(ids)

        monkeypatch.setattr(TranslationTask, "_coerce_float_to_int", fake)

        translator = Translator[str, str, int](fetcher=MemoryFetcher(data={"source": {1: "one!"}}))
        actual = translator.translate(np.array([1.0]), "source")
        assert isinstance(actual, np.ndarray)
        assert actual == ["1:one!"]
        assert calls == 1


@pytest.fixture(autouse=True)
def reimport_id_translation():
    """Force the test body to (re)import :mod:`id_translation` modules while the hook is active.

    Teardown restores the exact pre-test ``sys.modules`` state for the ``id_translation`` namespace. Deleting with
    ``monkeypatch.delitem`` is not enough: it restores the modules it deleted, but modules first imported *during* the
    test stay cached. Those copies were created with the hook active -- e.g. ``dio.default._sequence`` with a dummy
    ``ndarray``, or classes derived from a different ``DataStructureIO`` than the restored one -- and corrupt every
    later test that imports them (unless something happened to cache the real module before the test ran).
    """
    is_ours = lambda name: name.partition(".")[0] == PACKAGE  # noqa: E731
    snapshot = {name: module for name, module in sys.modules.items() if is_ours(name)}
    for name in snapshot:
        del sys.modules[name]
    try:
        yield
    finally:
        for name in [name for name in sys.modules if is_ours(name)]:
            del sys.modules[name]
        sys.modules.update(snapshot)


PACKAGE = "id_translation"

_HIDDEN: frozenset[str] = frozenset()
_REAL_IMPORT = builtins.__import__


def _import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> ModuleType:
    top = name.partition(".")[0]
    importer = "" if globals is None else globals.get("__name__", "")

    if level == 0 and top in _HIDDEN and importer.partition(".")[0] == PACKAGE:
        msg = f"No module named {top!r}"
        raise ModuleNotFoundError(msg, name=top)

    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def hide_module(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make `name` (and its submodules) unimportable from within :mod:`id_translation`.

    Stubbing ``sys.modules[name] = None`` is not enough. Already-imported submodules are returned straight from the
    cache by :func:`importlib._bootstrap._find_and_load` without consulting the stubbed parent, so e.g.
    ``from fsspec.core import url_to_fs`` keeps working whenever some earlier test has imported ``fsspec.core``. Adding
    the submodules to the stub fixes that, but a global stub is too blunt: third-party modules that are imported lazily
    and do ``try: import numpy / except ImportError: np = None`` (:mod:`pyarrow.pandas_compat` does exactly this) latch
    onto the stub permanently, breaking unrelated tests later in the session.

    Blocking at the ``__import__`` level instead is both order-independent and limited to our own import sites.
    """
    monkeypatch.setattr(builtins, "__import__", _import)
    monkeypatch.setitem(globals(), "_HIDDEN", _HIDDEN | {name})

    assert builtins.__import__ is _import  # The hook must actually be installed for the checks below to mean anything.
    with pytest.raises(ModuleNotFoundError):
        __import__(name, {"__name__": PACKAGE})
    with pytest.raises(ModuleNotFoundError):
        __import__(f"{name}.submodule", {"__name__": f"{PACKAGE}.fetching"})  # Submodules of hidden packages, too.
    # Positive control: `name` must remain importable outside the id_translation namespace. Proves that the module
    # really is installed (so the checks above cannot pass vacuously) and that the hook does not leak into
    # third-party import sites -- the failure mode that broke the `sys.modules` stubbing approach.
    assert isinstance(__import__(name), ModuleType)


def test_source_does_not_use_import_functions_hidden_from_the_hook():
    """Guard the known blind spot of :func:`hide_module`.

    The hook intercepts ``builtins.__import__``, which every ``import`` *statement* goes through -- including
    statements in entrypoint modules loaded via ``importlib.metadata``. But ``importlib.import_module``,
    ``importlib.util.find_spec`` and direct ``__import__(...)`` calls bypass ``builtins.__import__`` entirely: an
    optional dependency imported that way would silently escape every ``*_missing`` fixture. No source module uses
    them today; if this test fails, either use a plain import statement or extend :func:`hide_module`.
    """
    import id_translation

    pattern = re.compile(r"\bimport_module\s*\(|\bfind_spec\s*\(|\b__import__\s*\(")

    root = Path(id_translation.__file__).parent
    offenders = [
        f"{path.relative_to(root)}:{lineno}: {line.strip()}"
        for path in sorted(root.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if pattern.search(line)
    ]
    assert not offenders, "\n".join(offenders)


@pytest.fixture
def pandas_missing(monkeypatch):
    hide_module(monkeypatch, "pandas")


@pytest.fixture
def fsspec_missing(monkeypatch):
    hide_module(monkeypatch, "fsspec")


@pytest.fixture
def numpy_missing(monkeypatch):
    hide_module(monkeypatch, "numpy")


@pytest.fixture
def sqlalchemy_missing(monkeypatch):
    hide_module(monkeypatch, "sqlalchemy")
