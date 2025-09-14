import re
import sys
from importlib.util import find_spec

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

        translator = Translator[str, str, int](fetcher={"source": {1: "one!"}})
        assert translator.translate(1, "source") == "1:one!"

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
def reimport_id_translation(monkeypatch):
    names = [name for name in sys.modules if name.startswith("id_translation")]
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)


@pytest.fixture
def pandas_missing(monkeypatch):
    name = "pandas"
    monkeypatch.setitem(sys.modules, name, None)
    assert find_spec(name) is None


@pytest.fixture
def fsspec_missing(monkeypatch):
    name = "fsspec"
    monkeypatch.setitem(sys.modules, name, None)
    assert find_spec(name) is None


@pytest.fixture
def numpy_missing(monkeypatch):
    name = "numpy"
    monkeypatch.setitem(sys.modules, name, None)
    assert find_spec(name) is None


@pytest.fixture
def sqlalchemy_missing(monkeypatch):
    name = "sqlalchemy"
    monkeypatch.setitem(sys.modules, name, None)
    assert find_spec(name) is None
