import logging
import re
from functools import partialmethod
from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, MultiFetcher
from id_translation.toml import TranslatorFactory
from id_translation.toml._factory import SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS
from id_translation.toml.factories._fetcher import default_fetcher_factory
from id_translation.types import IdType, SourceType

from .conftest import ROOT


class AnotherFetcherType(MemoryFetcher[SourceType, IdType]):
    pass


@pytest.mark.parametrize(
    "clazz, expected_type",
    [
        ("MemoryFetcher", MemoryFetcher),
        ("id_translation.fetching.MemoryFetcher", MemoryFetcher),
        ("tests.test_factory.AnotherFetcherType", AnotherFetcherType),
    ],
)
def test_default_fetcher_factory(
    clazz: str,
    expected_type: type[AbstractFetcher[Any, Any]],
) -> None:
    fetcher: AbstractFetcher[str, int] = default_fetcher_factory(clazz, dict(data={}))
    assert isinstance(fetcher, expected_type)


def test_missing_config():
    path = ROOT.joinpath("bad-config.toml")
    with pytest.raises(ConfigurationError) as e:
        Translator.from_config(path)
    assert str(path) in str(e.value)


def test_top_level_mapping_key_raises(tmp_path):
    """A stray top-level `mapping` key is not used; the user wants `[translator.mapping]` or `[fetching.mapping]`."""
    main = """
    [translator]

    [fetching.MemoryFetcher]
    data = {}

    [mapping]
    """
    path = tmp_path / "main.toml"
    path.write_text(main, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"Forbidden keys \['mapping'\]"):
        Translator.from_config(path)


class TestEnvVars:
    @pytest.mark.parametrize("value", [True, False])
    def test_set(self, tmp_path, monkeypatch, value):
        monkeypatch.setenv("VAR_NAME", str(value).lower())
        self.run(tmp_path, expected=value)

    def test_unset(self, tmp_path):
        self.run(tmp_path, expected=True)

    @staticmethod
    def run(tmp_path, expected):
        main = """
        [translator]
        enable_uuid_heuristics = ${VAR_NAME:true}
        """
        main_path = tmp_path / "main.toml"
        main_path.write_text(main, encoding="utf-8")

        fetcher = """
        [fetching.MemoryFetcher]
        return_all = ${VAR_NAME:true}
        data = {}
        """
        fetcher_path = tmp_path / "fetcher.toml"
        fetcher_path.write_text(fetcher, encoding="utf-8")

        translator: Translator[str, str, int]
        translator = Translator.from_config(main_path, extra_fetchers=[fetcher_path])
        assert translator.enable_uuid_heuristics is expected
        assert isinstance(translator.fetcher, MemoryFetcher)
        assert translator.fetcher.return_all is expected


class TestCacheAccess:
    def test_does_not_inherit(self, tmp_path):
        cache = f"""
        [fetching.cache.'{__name__}.{BadCacheAccess.__name__}']
        password = "hunter2"
        """

        match = (
            "TypeError: Expected an instance of 'CacheAccess', but tests.test_factory.BadCacheAccess(password)"
            " produced a 'tests.test_factory.BadCacheAccess'."
        )
        with pytest.raises(ConfigurationError, match=re.escape(match)) as exc_info:
            self.create(tmp_path, cache)
        assert "hunter2" not in str(exc_info.value)

    def test_only_one_cached(self, tmp_path):
        from id_translation.fetching.exceptions import CacheAccessNotAvailableError

        cache = f"""
        [fetching.cache.'{__name__}.{DummyCacheAccess.__name__}']
        ttl = 3600
        """
        translator = self.create(tmp_path, cache)

        # Only check correct initialization. Behavioural tests in test_abstract_fetcher.py
        assert isinstance(translator.fetcher, MultiFetcher)
        fetcher_people, fetcher_animals = translator.fetcher.children

        # People fetcher - should be cached
        assert isinstance(fetcher_people, AbstractFetcher)
        assert isinstance(fetcher_people.cache_access, DummyCacheAccess)
        assert fetcher_people.cache_access.ttl == 3600

        # Animals fetcher - not cached
        assert isinstance(fetcher_animals, AbstractFetcher)
        with pytest.raises(CacheAccessNotAvailableError, match=r"documentation/examples/caching/on_disk.html"):
            _ = fetcher_animals.cache_access

    def test_type_key_is_deprecated(self, tmp_path):
        clazz = f"{__name__}.{DummyCacheAccess.__name__}"
        cache = f"""
        [fetching.cache]
        type = "{clazz}"
        ttl = 3600
        """

        with pytest.warns(FutureWarning, match=re.escape(f"Use a [fetching.cache.'{clazz}']-section instead.")):
            translator = self.create(tmp_path, cache)

        assert isinstance(translator.fetcher, MultiFetcher)
        fetcher_people, _ = translator.fetcher.children
        assert isinstance(fetcher_people, AbstractFetcher)
        assert isinstance(fetcher_people.cache_access, DummyCacheAccess)
        assert fetcher_people.cache_access.ttl == 3600

    def test_type_key_and_section_raises(self, tmp_path):
        """Half-migrated: the section was added, but `type` was not removed."""
        clazz = f"{__name__}.{DummyCacheAccess.__name__}"
        cache = f"""
        [fetching.cache]
        type = "{clazz}"

        [fetching.cache.'{clazz}']
        ttl = 3600
        """

        with pytest.raises(ConfigurationError, match=re.escape(f"keep only the [fetching.cache.'{clazz}']-section")):
            self.create(tmp_path, cache)

    @staticmethod
    def create(tmp_path, cache):
        main = """
        [translator]

        [fetching.MemoryFetcher.data]
        people = { id = [1991, 1999], name = ["Richard", "Sofia"] }
        """

        main_path = tmp_path / "main.toml"
        main_path.write_text(main + cache, encoding="utf-8")

        fetcher = """
        [fetching.MemoryFetcher.data]
        animals = { id = [2021], name = ["Morris"] }
        """
        fetcher_path = tmp_path / "fetcher.toml"
        fetcher_path.write_text(fetcher, encoding="utf-8")

        return Translator[str, str, int].from_config(main_path, extra_fetchers=[fetcher_path])


class BadCacheAccess:
    def __init__(self, **kwargs: Any) -> None:
        pass


class DummyCacheAccess(CacheAccess[Any, Any]):
    def __init__(self, ttl):
        super().__init__()
        self.ttl = ttl

    def load(self, instr):
        raise NotImplementedError

    def store(self, instr, translations):
        raise NotImplementedError


@pytest.mark.parametrize(
    "clazz, expected_error",
    [
        (
            "does_not_exist.FetcherClass",
            # The name too: from Python 3.15, an ImportError's repr() includes it.
            ModuleNotFoundError("No module named 'does_not_exist'", name="does_not_exist"),
        ),
        (f"{__name__}.CrashesOnInitFetcher", ValueError("I always crash!")),
    ],
)
class TestOptionalFetchers:
    @staticmethod
    def run(caplog, tmp_path, toml, expected_error):
        bad = tmp_path / "bad-fetcher.toml"
        bad.write_text(toml, encoding="utf-8")

        toml = """
        [translator]
        [fetching.MemoryFetcher.data]
        people = { id = [0], name = [""] }
        """
        main = tmp_path / "main.toml"
        main.write_text(toml, encoding="utf-8")

        toml = """
        [fetching.MemoryFetcher.data]
        animals = { id = [2021], name = ["Morris"] }
        """
        good = tmp_path / "ok-fetcher.toml"
        good.write_text(toml, encoding="utf-8")

        translator = Translator[Any, Any, Any].from_config(main, [good, bad])
        assert translator.sources == ["people", "animals"]

        fetcher = translator.fetcher
        assert isinstance(fetcher, MultiFetcher)
        assert len(fetcher.children) == 2
        assert not any(c.optional for c in fetcher.children)

        # Verify logged information.
        record = caplog.records[0]

        # Verify message
        message = record.getMessage()
        assert "ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS=true" in message
        assert "translator-config.html#optional-fetchers" in message
        assert "bad-fetcher.toml" in message
        assert repr(expected_error) in message

        # Check record details
        assert record.name == "id_translation.toml.TranslatorFactory"
        assert record.levelno == logging.ERROR
        assert record.fetcher_file.endswith("bad-fetcher.toml")
        actual_error = record.exc_info[1]
        assert str(actual_error) == str(expected_error)
        assert type(actual_error) is type(expected_error)

    def test_on(self, clazz, expected_error, caplog, tmp_path, monkeypatch):
        monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
        toml = f"""
        [fetching."{clazz}"]
        optional = true
        data = {{}}
        """
        self.run(caplog, tmp_path, toml, expected_error)

    def test_off(self, clazz, expected_error, caplog, tmp_path):
        toml = f"""
        [fetching."{clazz}"]
        optional = true
        data = {{}}
        """

        with pytest.raises(ConfigurationError) as exc_info:
            self.run(caplog, tmp_path, toml, "not-used")

        exc_repr = repr(exc_info.value)
        assert type(expected_error).__name__ in exc_repr
        assert str(expected_error) in exc_repr
        assert "bad-fetcher.toml" in exc_repr


class CrashesOnInitFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ValueError("I always crash!")


@pytest.mark.parametrize("extra", ["~/aux.toml", ["~/aux.toml"]], ids=["bare", "list"])
@pytest.mark.parametrize("persistent", [False, True])
def test_home_relative_paths_and_a_single_extra_path(tmp_path, monkeypatch, extra, persistent):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # What expanduser() reads on Windows.
    (tmp_path / "main.toml").write_text('[fetching.MemoryFetcher.data]\npeople = { id = [1], name = ["Ada"] }\n')
    (tmp_path / "aux.toml").write_text('[fetching.MemoryFetcher.data]\npets = { id = [2], name = ["Rex"] }\n')

    if persistent:
        translator = Translator[str, str, int].load_persistent_instance(tmp_path / "cache", "~/main.toml", extra)
    else:
        translator = Translator[str, str, int].from_config("~/main.toml", extra)
    assert translator.sources == ["people", "pets"]


def _plain_factory(clazz: str, config: dict[str, Any]) -> AbstractFetcher[Any, Any]:
    fetcher: AbstractFetcher[Any, Any] = default_fetcher_factory(clazz, config)
    fetcher.made_by_plain = True  # type: ignore[attr-defined]
    return fetcher


class _PlainFunctionFactory(TranslatorFactory[str, str, int]):
    FETCHER_FACTORY = _plain_factory  # type: ignore[assignment]  # mypy binds it like a method, as 1.4.2 did.


class _MethodFactory(TranslatorFactory[str, str, int]):
    def FETCHER_FACTORY(self, clazz, config):  # noqa: N802
        assert isinstance(self, TranslatorFactory)
        return _plain_factory(clazz, config)


class _PartialMethodFactory(TranslatorFactory[str, str, int]):
    FETCHER_FACTORY = partialmethod(_MethodFactory.FETCHER_FACTORY)


class _PartialStaticMethodFactory(TranslatorFactory[str, str, int]):
    FETCHER_FACTORY = partialmethod(staticmethod(_plain_factory))


class _ClassMethodFactory(TranslatorFactory[str, str, int]):
    @classmethod
    def FETCHER_FACTORY(cls, clazz, config):  # noqa: N802
        return _plain_factory(clazz, config)


@pytest.mark.parametrize(
    "factory_class",
    [_PlainFunctionFactory, _MethodFactory, _PartialMethodFactory, _PartialStaticMethodFactory, _ClassMethodFactory],
)
def test_fetcher_factory_on_a_subclass(tmp_path, factory_class):
    path = tmp_path / "main.toml"
    path.write_text('[fetching.MemoryFetcher.data]\npeople = { id = [1], name = ["Ada"] }\n')
    if factory_class in (_MethodFactory, _PartialMethodFactory):  # Bound to the instance; 2.0 calls them unbound.
        with pytest.warns(FutureWarning, match=r"called as FETCHER_FACTORY\(<TranslatorFactory>"):
            translator = factory_class(path, []).create()
    else:
        translator = factory_class(path, []).create()  # Warnings are errors.
    assert translator.fetcher.made_by_plain


def test_fetcher_factory_on_an_instance_warns(tmp_path):
    path = tmp_path / "main.toml"
    path.write_text('[fetching.MemoryFetcher.data]\npeople = { id = [1], name = ["Ada"] }\n')
    factory: TranslatorFactory[str, str, int] = TranslatorFactory(path, [])
    factory.FETCHER_FACTORY = _plain_factory

    with pytest.warns(FutureWarning, match="will be ignored"):
        translator = factory.create()
    assert translator.fetcher.made_by_plain  # type: ignore[attr-defined]


_PEOPLE = '[fetching.MemoryFetcher.data]\npeople = { id = [1], name = ["Ada"] }\n'


@pytest.mark.parametrize(
    "toml, match",
    [
        ('[translator]\ndefault_fmt = "{id}"\n' + _PEOPLE, r"\['default_fmt'\] under \[translator\]"),
        (
            "[translator.default_fmt_placeholders.default]\nname = 'x'\n" + _PEOPLE,
            r"\['default_fmt_placeholders'\] under",
        ),
        ("[translator.transformers]\nx = 1\n" + _PEOPLE, r"\['transformers'\] under \[translator\]"),
        ("[fetching.MemoryFetcher]\nreturn_all = true\nmapper = { x = 1 }\n" + _PEOPLE, r"\['mapper'\] are replaced"),
        ("[translator.mapping]\nscore_function_kwargs = {}\n" + _PEOPLE, "score_function_kwargs mapping key"),
    ],
)
def test_keys_that_2_0_rejects_warn(tmp_path, toml, match):
    path = tmp_path / "main.toml"
    path.write_text(toml)
    with pytest.warns(FutureWarning, match=match):
        Translator.from_config(path)
