import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from rics.env.interpolation import UnsetVariableError

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, CacheAccess, Fetcher, MemoryFetcher, MultiFetcher
from id_translation.fetching.exceptions import DuplicateSourceError, UnknownPlaceholderError
from id_translation.toml import TranslatorFactory
from id_translation.toml._factory import SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS
from id_translation.toml.exceptions import ConfigFileError
from id_translation.toml.factories import default_mapper_factory
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


def _recording_fetcher_factory(clazz: str, config: dict[str, Any]) -> AbstractFetcher[Any, Any]:
    config["data"] = {"recorded": {"id": [1], "name": ["one"]}}
    return default_fetcher_factory(clazz, config)


class _FunctionFactory(TranslatorFactory[str, str, int]):
    FETCHER_FACTORY = _recording_fetcher_factory


class _StaticMethodFactory(TranslatorFactory[str, str, int]):
    FETCHER_FACTORY = staticmethod(_recording_fetcher_factory)  # type: ignore[assignment]


@pytest.mark.parametrize("factory", [_FunctionFactory, _StaticMethodFactory])
def test_custom_fetcher_factory(tmp_path, factory):
    path = tmp_path / "main.toml"
    path.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")

    translator = factory(path, []).create()
    assert translator.translate(1, names="recorded", fmt="{name}") == "one"


def test_missing_config():
    path = ROOT.joinpath("bad-config.toml")
    with pytest.raises(ConfigFileError, match=r"At least one \[fetching\]-section is required") as e:
        Translator.from_config(path)
    assert str(path) in str(e.value)
    assert e.value.__notes__ == [f"Hint: In file: {path.resolve()}"]


@pytest.mark.parametrize("content", ['fmt = "{id}\n', 'fmt = "${ID_TRANSLATION_UNSET_VARIABLE}"\n'])
@pytest.mark.parametrize("broken", ["main.toml", "fetcher.toml"])
def test_unreadable_file_is_named(tmp_path, content, broken):
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher = tmp_path / "fetcher.toml"
    fetcher.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")
    (tmp_path / broken).write_text(f"[translator]\n{content}", encoding="utf-8")

    with pytest.raises(Exception) as exc_info:
        Translator.from_config(main, extra_fetchers=[fetcher])
    assert f"Hint: In file: {(tmp_path / broken).resolve()}" in exc_info.value.__notes__


def test_top_level_mapping_key_raises(tmp_path):
    main = """
    [translator]

    [fetching.MemoryFetcher]
    data = {}

    [mapping]
    """
    path = tmp_path / "main.toml"
    path.write_text(main, encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"Forbidden keys \['mapping'\]") as exc_info:
        Translator.from_config(path)
    assert "Hint: Use [translator.mapping] or [fetching.mapping]." in exc_info.value.__notes__


@pytest.mark.parametrize("key", ["default_fmt", "transformers", "mapper", "bad"])
def test_translator_section_rejects_other_keys(tmp_path, key):
    path = tmp_path / "main.toml"
    path.write_text(f"[translator]\n{key} = 1\n\n[fetching.MemoryFetcher]\ndata = {{}}\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=rf"Forbidden keys \['{key}'\] in \[translator\]-section") as exc_info:
        Translator.from_config(path)
    if key == "default_fmt":
        assert "Hint: Use [unknown_ids] fmt." in exc_info.value.__notes__


@pytest.mark.parametrize(
    ("broken", "content", "key"),
    [
        ("main.toml", "transform = 1\n[fetching.MemoryFetcher]\ndata = {}\n", "transform"),
        ("fetcher.toml", "fetching = 1\n", "fetching"),
    ],
)
def test_section_given_a_value(tmp_path, broken, content, key):
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher = tmp_path / "fetcher.toml"
    fetcher.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")
    (tmp_path / broken).write_text(content, encoding="utf-8")

    with pytest.raises(ConfigFileError, match=rf"Top-level keys \['{key}'\] must be sections"):
        Translator.from_config(main, extra_fetchers=[fetcher])


def test_unknown_ids_section_is_named(tmp_path):
    path = tmp_path / "main.toml"
    path.write_text("[unknown_ids]\nbad = 1\n\n[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"Forbidden keys \['bad'\] in \[unknown_ids\]-section"):
        Translator.from_config(path)


class RegionalTranslator(Translator[str, str, int]):
    def __init__(self, fetcher: Any = None, *, region: str = "eu", **kwargs: Any) -> None:
        super().__init__(fetcher, **kwargs)
        self.region = region


@pytest.mark.parametrize("key, value", [("region", "'us'"), ("default_fmt", "'x'")])
def test_translator_section_accepts_subclass_arguments(tmp_path, key, value):
    path = tmp_path / "main.toml"
    path.write_text(f"[translator]\n{key} = {value}\n\n[fetching.MemoryFetcher]\ndata = {{}}\n", encoding="utf-8")

    if key == "default_fmt":
        with pytest.raises(ConfigFileError, match=r"Forbidden keys \['default_fmt'\]"):
            RegionalTranslator.from_config(path)
    else:
        assert RegionalTranslator.from_config(path).region == "us"


def test_top_level_mapping_key_in_fetcher_file_raises(tmp_path):
    fetcher = """
    [fetching.MemoryFetcher]
    data = {}

    [mapping]
    """
    path = tmp_path / "fetcher.toml"
    path.write_text(fetcher, encoding="utf-8")
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"Forbidden keys \['mapping'\]") as exc_info:
        Translator.from_config(main, extra_fetchers=[path])
    assert "Hint: Use [fetching.mapping]." in exc_info.value.__notes__


def test_dummy_override_hides_optional_placeholder(tmp_path):
    # The "Preventing unwanted mappings" example in translator-config.rst.
    path = tmp_path / "main.toml"
    config = """
    [translator]
    fmt = "[{title}. ]{name}"

    [fetching.MemoryFetcher.data.title_basics]
    id = [1]
    title = ["Top Hat"]
    name = ["Top Hat"]

    [fetching.MemoryFetcher.data.people]
    id = [2]
    title = ["Mr"]
    name = ["Astaire"]

    [fetching.mapping.overrides.title_basics]
    title = "_"
    """
    path.write_text(config, encoding="utf-8")

    translator: Translator[str, str, int] = Translator.from_config(path)
    expected = {"title_basics": "Top Hat", "people": "Mr. Astaire"}
    assert translator.translate({"title_basics": 1, "people": 2}) == expected


@pytest.mark.parametrize("table", ["", ".people"])
def test_override_tables_to_absent_column(tmp_path, table):
    path = tmp_path / "main.toml"
    config = f"""
    [fetching.MemoryFetcher.data.people]
    id = [1]
    name = ["Ada"]

    [fetching.mapping.overrides{table}]
    name = "nope"
    """
    path.write_text(config, encoding="utf-8")

    translator: Translator[str, str, int] = Translator.from_config(path)
    with pytest.raises(UnknownPlaceholderError, match=r"\['nope'\] not recognized") as ec:
        translator.initialize_sources()
    assert ("shared override" in ec.value.__notes__[0]) is not bool(table)


def test_source_conflict_names_both_files(tmp_path):
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MemoryFetcher.data.people]\nid = [1]\n", encoding="utf-8")
    extra = tmp_path / "extra.toml"
    extra.write_text("[fetching.MemoryFetcher.data.people]\nid = [2]\n", encoding="utf-8")

    translator: Translator[str, str, int] = Translator.from_config(main, extra_fetchers=[extra])
    with pytest.raises(DuplicateSourceError, match="both claim source='people'") as exc_info:
        translator.initialize_sources()
    assert "file='main.toml'" in str(exc_info.value)
    assert "file='extra.toml'" in str(exc_info.value)
    assert "on_source_conflict='warn'" in exc_info.value.__notes__[0]


class PlainFetcher(Fetcher[str, int]):
    """A fetcher written from first principles: not an AbstractFetcher, and no AbstractFetcherParams."""

    def __init__(self, data: dict[str, dict[str, list[Any]]]) -> None:
        self._inner: MemoryFetcher[str, int] = MemoryFetcher(data)

    @property
    def allow_fetch_all(self) -> bool:
        return True

    def initialize_sources(self, task_id: int | None = None) -> None:
        self._inner.initialize_sources(task_id)

    @property
    def placeholders(self) -> Mapping[str, Sequence[str]]:
        return self._inner.placeholders

    def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.fetch(*args, **kwargs)

    def fetch_all(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.fetch_all(*args, **kwargs)


class PlainFetcherTakingParams(PlainFetcher):
    def __init__(self, data: dict[str, dict[str, list[Any]]], **kwargs: Any) -> None:  # noqa: ARG002
        super().__init__(data)


class RejectsParams(MemoryFetcher[str, int]):
    def __init__(self, data: dict[str, dict[str, list[Any]]]) -> None:
        super().__init__(data)


class TestFetchersFromFirstPrinciples:
    @staticmethod
    def write(tmp_path: Path, clazz: str, extra: str = "") -> Path:
        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "main.toml"
        path.write_text(
            f"[fetching.'{clazz}']\ndata.people = {{ id = [1], name = ['Ada'] }}\n{extra}", encoding="utf-8"
        )
        return path

    def test_default_factory_hints_at_a_custom_one(self, tmp_path):
        path = self.write(tmp_path, f"{__name__}.PlainFetcher")
        with pytest.raises(TypeError) as exc_info:
            Translator.from_config(path)
        assert "Fetcher that creates tests.test_factory.PlainFetcher; `config` holds" in exc_info.value.__notes__[0]

    def test_abstract_fetcher_rejecting_params_hints_at_forwarding(self, tmp_path):
        path = self.write(tmp_path, f"{__name__}.RejectsParams")
        with pytest.raises(TypeError) as exc_info:
            Translator.from_config(path)
        assert (
            "must accept the keyword arguments ['identifiers', 'mapper', 'cache_access']" in exc_info.value.__notes__[0]
        )

    def test_typo_gets_no_forwarding_hint(self, tmp_path):
        path = self.write(tmp_path, f"{__name__}.RejectsParams", "typo = 1\n")
        with pytest.raises(TypeError, match="unexpected keyword argument 'typo'") as exc_info:
            Translator.from_config(path)
        assert len(exc_info.value.__notes__) == 1, "only the file"

    def test_plain_fetcher_taking_the_params_hints_at_a_custom_factory(self, tmp_path):
        path = self.write(tmp_path, f"{__name__}.PlainFetcherTakingParams")
        with pytest.raises(ConfigFileError, match="Expected an instance of 'AbstractFetcher'") as exc_info:
            Translator.from_config(path)
        assert exc_info.value.__notes__[0] == (
            "Hint: Subclass AbstractFetcher, or set TranslatorFactory.FETCHER_FACTORY to a function that creates it."
        )

    def test_optional_gets_both_hints(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text("[fetching.MemoryFetcher.data.dogs]\nid = [1]\n", encoding="utf-8")
        extra = self.write(tmp_path / "extra", f"{__name__}.PlainFetcher", "optional = true\n")
        with pytest.raises(TypeError) as exc_info:
            Translator.from_config(main, extra_fetchers=[extra])
        notes = exc_info.value.__notes__
        assert "creates AbstractFetchers only" in notes[0]
        assert SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS in notes[1]

    def test_custom_factory_errors_get_no_hints(self, tmp_path, monkeypatch):
        def factory(clazz: str, config: dict[str, Any]) -> Fetcher[Any, Any]:
            return default_fetcher_factory(clazz, config)

        monkeypatch.setattr(TranslatorFactory, "FETCHER_FACTORY", factory)
        with pytest.raises(TypeError) as exc_info:
            Translator.from_config(self.write(tmp_path, f"{__name__}.PlainFetcher"))
        assert len(exc_info.value.__notes__) == 1, "only the file"

    def test_custom_factory(self, tmp_path, monkeypatch):
        def factory(clazz: str, config: dict[str, Any]) -> Fetcher[Any, Any]:
            if clazz.endswith("PlainFetcher"):
                return PlainFetcher(config["data"])
            return default_fetcher_factory(clazz, config)

        monkeypatch.setattr(TranslatorFactory, "FETCHER_FACTORY", factory)
        translator: Translator[str, str, int] = Translator.from_config(self.write(tmp_path, f"{__name__}.PlainFetcher"))
        assert translator.translate(1, names="people") == "1:Ada"

    @pytest.mark.parametrize("auxiliary", [False, True])
    def test_custom_factory_returning_a_non_fetcher(self, tmp_path, monkeypatch, auxiliary):
        """None is not a fetcher: auxiliary-only, it would mean Translator(fetcher=None), which makes fake translations."""
        monkeypatch.setattr(TranslatorFactory, "FETCHER_FACTORY", lambda _clazz, _config: None)
        fetcher_file = self.write(tmp_path / "fetcher", f"{__name__}.PlainFetcher")
        main = tmp_path / "main.toml"
        main.write_text("", encoding="utf-8")

        with pytest.raises(TypeError) as exc_info:
            if auxiliary:
                Translator.from_config(main, extra_fetchers=[fetcher_file])
            else:
                Translator.from_config(fetcher_file)
        expected = f"FETCHER_FACTORY returned a 'builtins.NoneType' for '{__name__}.PlainFetcher'; expected a Fetcher."
        assert str(exc_info.value) == expected
        assert exc_info.value.__notes__ == [f"Hint: In file: {fetcher_file.resolve()}"]

    def test_custom_factory_without_transform_support(self, tmp_path, monkeypatch):
        monkeypatch.setattr(TranslatorFactory, "FETCHER_FACTORY", lambda _clazz, config: PlainFetcher(config["data"]))
        extra = "[fetching.transform.people.BitmaskTransformer]\n"
        with pytest.raises(ConfigFileError, match=r"\[fetching.transform\]-section requires an AbstractFetcher"):
            Translator.from_config(self.write(tmp_path, f"{__name__}.PlainFetcher", extra))


@pytest.mark.parametrize(
    ("hook", "section", "expected"),
    [
        ("CACHE_ACCESS_FACTORY", "[fetching.cache.Cache]", "'builtins.NoneType' for 'Cache'; expected a CacheAccess."),
        ("MAPPER_FACTORY", "[fetching.mapping]", "'builtins.dict' for [fetching.mapping]; expected a Mapper."),
        ("MAPPER_FACTORY", "[translator.mapping]", "'builtins.dict' for [translator.mapping]; expected a Mapper."),
    ],
)
def test_custom_factory_returning_the_wrong_type(tmp_path, monkeypatch, hook, section, expected):
    """A None cache was taken to mean no cache. ``None`` from a ``MAPPER_FACTORY`` means a default, so a dict here."""
    monkeypatch.setattr(TranslatorFactory, hook, lambda *_: {} if hook == "MAPPER_FACTORY" else None)
    path = tmp_path / "main.toml"
    path.write_text(f"[fetching.MemoryFetcher]\ndata.people = {{ id = [1] }}\n{section}\n", encoding="utf-8")

    with pytest.raises(TypeError) as exc_info:
        Translator.from_config(path)
    assert str(exc_info.value) == f"{hook} returned a {expected}"
    assert exc_info.value.__notes__ == [f"Hint: In file: {path.resolve()}"]


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
            "Expected an instance of 'CacheAccess', but tests.test_factory.BadCacheAccess(password)"
            " produced a 'tests.test_factory.BadCacheAccess'."
        )
        with pytest.raises(ConfigFileError, match=re.escape(match)) as exc_info:
            self.create(tmp_path, cache)
        assert "hunter2" not in str(exc_info.value)
        assert exc_info.value.__notes__[0] == "Hint: Subclass CacheAccess."

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

    @pytest.mark.parametrize("kwargs", ["", "ttl = 3600"])
    def test_type_key(self, tmp_path, kwargs):
        cache = f"""
        [fetching.cache]
        type = '{__name__}.{DummyCacheAccess.__name__}'
        {kwargs}
        """

        match = r"Expected only \[fetching.cache.'<type>'\]-sections in \[fetching.cache\]; got keys \[.*'type'\]"
        with pytest.raises(ConfigFileError, match=match) as exc_info:
            self.create(tmp_path, cache)
        assert not [note for note in exc_info.value.__notes__ if SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS in note]

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
        # The section key does not resolve: the file is invalid. The variable discards it all the same.
        (
            "does_not_exist.FetcherClass",
            ConfigFileError(
                "Cannot resolve 'does_not_exist.FetcherClass': ModuleNotFoundError: No module named 'does_not_exist'"
            ),
        ),
        (
            f"{__name__}.NoSuchFetcher",
            ConfigFileError(
                f"Cannot resolve '{__name__}.NoSuchFetcher':"
                f" AttributeError: module '{__name__}' has no attribute 'NoSuchFetcher'"
            ),
        ),
        ("os.name", ConfigFileError("Cannot resolve 'os.name': a 'builtins.str' is not callable.")),
        # Raised by the fetcher itself: propagates as itself.
        (f"{__name__}.CrashesOnInitFetcher", ValueError("I always crash!")),
        (f"{__name__}.DatabaseDownFetcher", ConnectionRefusedError("Database is down.")),
        (
            f"{__name__}.MissingDriverFetcher",
            # The name too: from Python 3.15, an ImportError's repr() includes it.
            ModuleNotFoundError("No module named 'no_such_driver'", name="no_such_driver"),
        ),
    ],
    ids=["missing-module", "missing-attribute", "not-callable", "value-error", "os-error", "import-error"],
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

        with pytest.raises(type(expected_error)) as exc_info:
            self.run(caplog, tmp_path, toml, "not-used")

        assert type(exc_info.value) is type(expected_error)
        assert str(exc_info.value) == str(expected_error)
        assert exc_info.value.__notes__ == [
            f"Hint: Setting {SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true may help temporarily.",  # It would discard it.
            f"Hint: In file: {(tmp_path / 'bad-fetcher.toml').resolve()}",
        ]

    def test_not_optional(self, clazz, expected_error, caplog, tmp_path, monkeypatch):
        monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
        toml = f"""
        [fetching."{clazz}"]
        data = {{}}
        """

        with pytest.raises(type(expected_error)) as exc_info:
            self.run(caplog, tmp_path, toml, "not-used")

        assert type(exc_info.value) is type(expected_error)
        assert str(exc_info.value) == str(expected_error)
        # No suppress hint: the variable cannot discard a fetcher that isn't optional.
        assert exc_info.value.__notes__ == [f"Hint: In file: {(tmp_path / 'bad-fetcher.toml').resolve()}"]


@pytest.mark.parametrize("auxiliary", [False, True])
def test_main_key_in_fetching_section(tmp_path, auxiliary):
    """[fetching] was spread into keyword arguments, so `main = true` made an auxiliary file the main one."""
    main = tmp_path / "main.toml"
    fetching = "[fetching]\nmain = true\n[fetching.MemoryFetcher]\ndata.s = { id = [1] }\n"
    extra = tmp_path / "extra.toml"
    extra.write_text(fetching, encoding="utf-8")
    main.write_text("[translator]\n" if auxiliary else fetching, encoding="utf-8")

    expected = r"Expected only \[fetching.'<type>'\]-sections in \[fetching\]; got keys \['main'\]\."
    with pytest.raises(ConfigFileError, match=expected) as exc_info:
        Translator.from_config(main, extra_fetchers=[extra] if auxiliary else [])
    assert exc_info.value.__notes__ == [f"Hint: In file: {(extra if auxiliary else main).resolve()}"]


class RefusedCache(DummyCacheAccess):
    def __init__(self) -> None:
        raise ConnectionRefusedError("Cache is down.")


@pytest.mark.parametrize("suppress", [False, True])
def test_optional_fetcher_with_a_failing_cache(tmp_path, monkeypatch, suppress):
    """The cache was created before the fetcher, where the variable could not discard it."""
    monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, str(suppress).lower())
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MemoryFetcher]\ndata.s = { id = [1] }\n", encoding="utf-8")
    extra = tmp_path / "extra.toml"
    extra.write_text(
        f"[fetching.MemoryFetcher]\noptional = true\ndata.t = {{ id = [1] }}\n[fetching.cache.'{__name__}.RefusedCache']\n",
        encoding="utf-8",
    )

    if suppress:
        fetcher: Fetcher[Any, Any] = Translator.from_config(main, extra_fetchers=[extra]).fetcher
        assert isinstance(fetcher, MultiFetcher)
        assert len(fetcher.children) == 1, "the optional fetcher is discarded"
    else:
        with pytest.raises(ConnectionRefusedError) as exc_info:
            Translator.from_config(main, extra_fetchers=[extra])
        assert SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS in exc_info.value.__notes__[0]


def test_optional_fetcher_cache_factory_returning_the_wrong_type(tmp_path, monkeypatch):
    """A factory result of the wrong type is never discarded, unlike a failing cache."""
    monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
    monkeypatch.setattr(TranslatorFactory, "CACHE_ACCESS_FACTORY", lambda *_: None)
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MemoryFetcher]\ndata.s = { id = [1] }\n", encoding="utf-8")
    extra = tmp_path / "extra.toml"
    extra.write_text(
        "[fetching.MemoryFetcher]\noptional = true\ndata.t = { id = [1] }\n[fetching.cache.Cache]\n",
        encoding="utf-8",
    )

    with pytest.raises(TypeError, match=r"^CACHE_ACCESS_FACTORY returned a 'builtins\.NoneType' for 'Cache'"):
        Translator.from_config(main, extra_fetchers=[extra])


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        ("bogus = 1\n", r"Forbidden keys \['bogus'\] at the top level"),
        ("[translator]\nbogus = 1\n", r"Forbidden keys \['bogus'\] in \[translator\]-section"),
    ],
)
def test_key_typo_is_reported_before_the_fetchers_are_built(tmp_path, toml, match):
    """A fetcher that failed to construct used to hide the typo."""
    path = tmp_path / "main.toml"
    path.write_text(f"{toml}[fetching.'{__name__}.CrashesOnInitFetcher']\n", encoding="utf-8")
    with pytest.raises(ConfigFileError, match=match):
        Translator.from_config(path)


@pytest.mark.parametrize("count", [1, 2])
def test_every_fetcher_discarded(tmp_path, monkeypatch, count):
    """Names each auxiliary file: the main file cannot hold a discarded fetcher."""
    monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    extra = [tmp_path / f"fetcher{i}.toml" for i in range(count)]
    for path in extra:
        path.write_text(f"[fetching.'{__name__}.CrashesOnInitFetcher']\noptional = true\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"All \[fetching\]-sections were discarded as optional") as exc_info:
        Translator.from_config(main, extra_fetchers=extra)
    assert exc_info.value.__notes__ == [f"Hint: In file: {path.resolve()}" for path in extra]


def test_lone_survivor_stays_wrapped(tmp_path, monkeypatch):
    monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MultiFetcher]\nmax_workers = 3\n", encoding="utf-8")
    good = tmp_path / "good.toml"
    good.write_text("[fetching.MemoryFetcher]\ndata = { s = { id = [1], name = ['one'] } }\n", encoding="utf-8")
    bad = tmp_path / "bad.toml"
    bad.write_text(f"[fetching.'{__name__}.CrashesOnInitFetcher']\noptional = true\n", encoding="utf-8")

    fetcher: Fetcher[Any, Any] = Translator.from_config(main, extra_fetchers=[good, bad]).fetcher
    assert isinstance(fetcher, MultiFetcher)
    assert len(fetcher.children) == 1
    assert fetcher.max_workers == 3


class CrashesOnInitFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ValueError("I always crash!")


class DatabaseDownFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ConnectionRefusedError("Database is down.")


class MissingDriverFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ModuleNotFoundError("No module named 'no_such_driver'", name="no_such_driver")


class NotAFetcher:
    def __init__(self, **kwargs: Any) -> None:
        pass


@pytest.mark.parametrize("optional", [False, True])
def test_not_a_fetcher(tmp_path, optional):
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    aux = tmp_path / "fetcher.toml"
    aux.write_text(f"[fetching.'{__name__}.NotAFetcher']\noptional = {str(optional).lower()}\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"Expected an instance of 'AbstractFetcher'") as exc_info:
        Translator.from_config(main, extra_fetchers=[aux])
    suppress_hint = f"Hint: Setting {SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true may help temporarily."
    assert exc_info.value.__notes__ == [
        "Hint: Subclass AbstractFetcher, or set TranslatorFactory.FETCHER_FACTORY to a function that creates it.",
        *([suppress_hint] if optional else []),
        f"Hint: In file: {aux.resolve()}",
    ]


class ConfigFileErrorOnInitFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ConfigFileError("Bad option.", hints="Use another option.")


def test_optional_fetcher_config_file_error_is_not_rewrapped(tmp_path):
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    aux = tmp_path / "fetcher.toml"
    aux.write_text(
        f"[fetching.'{__name__}.ConfigFileErrorOnInitFetcher']\noptional = true\ndata = {{}}\n", encoding="utf-8"
    )

    with pytest.raises(ConfigFileError) as exc_info:
        Translator.from_config(main, extra_fetchers=[aux])
    assert str(exc_info.value) == "Bad option."
    assert exc_info.value.__notes__ == [
        "Hint: Use another option.",
        f"Hint: Setting {SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true may help temporarily.",
        f"Hint: In file: {aux.resolve()}",
    ]


class TestMultiFetcherSection:
    FETCHER = "[fetching.MemoryFetcher.data.s]\nid = [1]\nname = ['a']\n"

    def test_bad_key_with_one_fetcher(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER + "[fetching.MultiFetcher]\nmax_wokers = 2\n", encoding="utf-8")

        with pytest.raises(ConfigFileError, match=r"Forbidden keys \['max_wokers'\] in \[fetching.MultiFetcher\]"):
            Translator.from_config(main)

    def test_bad_value_with_one_fetcher(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER + "[fetching.MultiFetcher]\non_source_conflict = 'bad'\n", encoding="utf-8")

        with pytest.raises(TypeError, match=r"Bad on_source_conflict='bad'") as exc_info:
            Translator.from_config(main)
        assert f"Hint: In file: {main.resolve()}" in exc_info.value.__notes__

    def test_bad_value_names_file(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER + "[fetching.MultiFetcher]\non_source_conflict = 'bad'\n", encoding="utf-8")
        aux = tmp_path / "aux.toml"
        aux.write_text(self.FETCHER, encoding="utf-8")

        with pytest.raises(TypeError, match=r"Bad on_source_conflict='bad'") as exc_info:
            Translator.from_config(main, extra_fetchers=[aux])
        assert f"Hint: In file: {main.resolve()}" in exc_info.value.__notes__

    def test_in_auxiliary_file(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER, encoding="utf-8")
        aux = tmp_path / "aux.toml"
        aux.write_text(self.FETCHER + "[fetching.MultiFetcher]\nmax_workers = 2\n", encoding="utf-8")

        with pytest.raises(ConfigFileError, match=r"allowed in the main file only") as exc_info:
            Translator.from_config(main, extra_fetchers=[aux])
        assert any(str(aux) in note for note in exc_info.value.__notes__)


@pytest.mark.parametrize(
    "content",
    ["fetching = [\n", "[translator]\nfmt = '${A:${B}}'\n", b"[translator]\nfmt = '\xff'\n"],
    ids=["toml", "nested-variable", "not-utf-8"],
)
@pytest.mark.parametrize("broken", ["main.toml", "fetcher.toml"])
def test_file_content_errors_are_config_file_errors(tmp_path, broken, content):
    main, fetcher = tmp_path / "main.toml", tmp_path / "fetcher.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")
    if isinstance(content, bytes):
        (tmp_path / broken).write_bytes(content)  # Not UTF-8.
    else:
        (tmp_path / broken).write_text(content, encoding="utf-8")

    with pytest.raises(ConfigFileError) as exc_info:
        Translator.from_config(main, extra_fetchers=[fetcher])

    assert exc_info.value.__cause__ is not None
    assert [n for n in exc_info.value.__notes__ if n.startswith("Hint: In file:")] == [
        f"Hint: In file: {(tmp_path / broken).resolve()}"
    ]


@pytest.mark.parametrize("broken", ["main.toml", "fetcher.toml"])
def test_unset_variable_is_not_a_config_file_error(tmp_path, broken):
    """The file is fine; the environment is not. The variable is named, and so is the file."""
    main, fetcher = tmp_path / "main.toml", tmp_path / "fetcher.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")
    (tmp_path / broken).write_text("[translator]\nfmt = '${ID_TRANSLATION_SURELY_UNSET}'\n", encoding="utf-8")

    with pytest.raises(UnsetVariableError, match="ID_TRANSLATION_SURELY_UNSET") as exc_info:
        Translator.from_config(main, extra_fetchers=[fetcher])
    assert exc_info.value.__notes__ == [f"Hint: In file: {(tmp_path / broken).resolve()}"]


class _BuggyTranslator(Translator[str, str, int]):
    def __init__(self, *_args: Any, **kwargs: Any) -> None:
        if kwargs.get("fmt") == "{bad}":
            raise ValueError("Bad fmt.")
        _ = 1 / 0


@pytest.mark.parametrize(
    "translator_section, expected",
    [
        ("", ZeroDivisionError),
        ("fmt = '{bad}'", ValueError),
    ],
)
def test_translator_class_errors(tmp_path, translator_section, expected):
    """Whatever the Translator class raises, bad [translator] arguments included, propagates as itself."""
    main = tmp_path / "main.toml"
    main.write_text(f"[translator]\n{translator_section}\n[fetching.MemoryFetcher.data]\n", encoding="utf-8")

    with pytest.raises(expected) as exc_info:
        _BuggyTranslator.from_config(main)
    assert type(exc_info.value) is expected
    assert exc_info.value.__notes__ == [f"Hint: In file: {main.resolve()}"]


def test_mapper_import_error_propagates(tmp_path):
    """A name inside a section is resolved by the object the section creates, so its error is that object's."""
    main = tmp_path / "main.toml"
    main.write_text(
        "[fetching.mapping.score_function.'no.such.module.score']\n[fetching.MemoryFetcher.data]\n", encoding="utf-8"
    )

    with pytest.raises(ModuleNotFoundError, match="No module named 'no'") as exc_info:
        Translator.from_config(main)
    assert exc_info.value.__notes__ == [f"Hint: In file: {main.resolve()}"]


def test_missing_file_is_an_os_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        Translator.from_config(tmp_path / "missing.toml")


@pytest.mark.parametrize("key", ["mapper", "cache_access"])
def test_fetcher_keys_that_have_their_own_section(tmp_path, key):
    path = tmp_path / "main.toml"
    path.write_text(f"[fetching.MemoryFetcher]\ndata = {{}}\n{key} = 'x'\n", encoding="utf-8")

    with pytest.raises(ConfigFileError, match=rf"Keys \['{key}'\] are not allowed in \[fetching.MemoryFetcher\]"):
        Translator.from_config(path)


@pytest.mark.parametrize("section", ["translator", "fetching"])
def test_score_function_kwargs_key_is_rejected(tmp_path, section):
    """One spelling: the [*.mapping.score_function.<name>] table."""
    path = tmp_path / "main.toml"
    path.write_text(
        f"[{section}.mapping]\nscore_function = 'modified_hamming'\nscore_function_kwargs = {{ add_length_ratio_term = true }}\n"
        "\n[fetching.MemoryFetcher]\ndata = {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigFileError, match=rf"not allowed in \[{section}.mapping\]") as exc_info:
        Translator.from_config(path)
    assert [n for n in exc_info.value.__notes__ if f"[{section}.mapping.score_function.<name>]" in n]


@pytest.mark.parametrize("as_type", [str, Path])
def test_single_extra_fetcher_path(tmp_path, as_type):
    main, fetcher = tmp_path / "main.toml", tmp_path / "fetcher.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher.write_text("[fetching.MemoryFetcher]\ndata.s = { id = [1], name = ['one'] }\n", encoding="utf-8")

    assert TranslatorFactory(main, as_type(fetcher)).extra_fetchers == [str(fetcher)]
    translator = Translator[str, str, int].from_config(main, extra_fetchers=as_type(fetcher))
    assert translator.translate(1, names="s") == "1:one"


def test_tilde_paths_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # What expanduser() reads on Windows.
    (tmp_path / "main.toml").write_text("[translator]\nfmt = '{id}!'\n", encoding="utf-8")
    (tmp_path / "metaconf.toml").write_text("[env]\nallow_interpolation = false\n", encoding="utf-8")
    fetcher = tmp_path / "fetcher.toml"
    fetcher.write_text("[fetching.MemoryFetcher]\ndata.s = { id = [1] }\n", encoding="utf-8")

    factory: TranslatorFactory[str, str, int] = TranslatorFactory("~/main.toml", "~/fetcher.toml")
    assert not factory.metaconf.env.allow_interpolation, "metaconf.toml beside the main file must be read"

    translator = Translator[str, str, int].from_config("~/main.toml", extra_fetchers="~/fetcher.toml")
    assert translator.translate(1, names="s") == "1!"

    translator.go_offline(path="~/cache/translator.pkl")
    assert Translator[str, str, int].restore("~/cache/translator.pkl").translate(1, names="s") == "1!"


class TestShapeErrors:
    FETCHER = "[fetching.MemoryFetcher.data.people]\nid = [1]\nname = ['Ada']\n"

    @pytest.mark.parametrize(
        "extra, match",
        [
            ("[translator]\nmapping = 'x'\n", r"\[translator.mapping\] must be a table, not str"),
            ("[fetching]\nmapping = 1\n", r"\[fetching.mapping\] must be a table, not int"),
            ("[fetching]\nMultiFetcher = 'abc'\n", r"\[fetching.MultiFetcher\] must be a table, not str"),
            ("[fetching]\ncache = 1\n", r"\[fetching.cache\] must be a table, not int"),
            ("[unknown_ids]\noverrides = 'x'\n", r"\[unknown_ids.overrides\] must be a table, not str"),
            ("[translator.mapping.score_function]\n", r"score_function\] must hold exactly one entry, got \[\]"),
            (
                "[translator.mapping.score_function]\nmodified_hamming = 1\n",
                r"\[translator.mapping.score_function.modified_hamming\] must be a table, not int",
            ),
            (
                "[translator.mapping]\nfilter_functions = ['filter_names']\n",
                r"\[\[translator.mapping.filter_functions\]\] must be a list of tables",
            ),
            (
                "[translator.mapping]\nscore_function = 'equality'\n[[translator.mapping.score_function_heuristics]]\n"
                "x = 1\n",
                r"score_function_heuristics\]\] entries \[0\] have no 'function' key",
            ),
        ],
    )
    def test_wrong_shape(self, tmp_path, extra, match):
        path = tmp_path / "main.toml"
        path.write_text(self.FETCHER + extra, encoding="utf-8")
        with pytest.raises(ConfigFileError, match=match):
            Translator.from_config(path)

    @pytest.mark.parametrize(
        "key, hint",
        [
            ("default_fmt_placeholders = {}", "each .specific.<source> table becomes [unknown_ids.overrides.<source>]"),
            ("mapper = 1", "Use [translator.mapping]."),
            ("transformers = {}", "Delete the transformers key to keep current results"),
        ],
    )
    def test_translator_key_hints(self, tmp_path, key, hint):
        path = tmp_path / "main.toml"
        path.write_text(f"[translator]\n{key}\n\n{self.FETCHER}", encoding="utf-8")
        with pytest.raises(ConfigFileError) as exc_info:
            Translator.from_config(path)
        assert any(hint in note for note in exc_info.value.__notes__)

    def test_auxiliary_root(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER, encoding="utf-8")
        extra = tmp_path / "extra.toml"
        extra.write_text(
            "[translator]\nfmt = '{id}'\n\n[fetching.MemoryFetcher.data.dogs]\nid = [1]\n", encoding="utf-8"
        )
        with pytest.raises(ConfigFileError, match=r"Forbidden keys \['translator'\] at the top level") as exc_info:
            Translator.from_config(main, extra_fetchers=[extra])
        assert "Hint: Auxiliary files may only contain a [fetching]-section." in exc_info.value.__notes__

    def test_mapping_without_fetcher(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text("[fetching.mapping.overrides]\nname = 'name'\n", encoding="utf-8")
        extra = tmp_path / "extra.toml"
        extra.write_text(self.FETCHER, encoding="utf-8")
        with pytest.raises(ConfigFileError, match="Fetcher implementation section missing") as exc_info:
            Translator.from_config(main, extra_fetchers=[extra])
        assert "Hint: Declare the fetcher for [fetching.mapping] in the same file." in exc_info.value.__notes__

    def test_cache_without_fetcher(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text("[fetching.cache.'no_such_module.Cache']\n", encoding="utf-8")
        extra = tmp_path / "extra.toml"
        extra.write_text(self.FETCHER, encoding="utf-8")
        with pytest.raises(ConfigFileError, match="Fetcher implementation section missing") as exc_info:
            Translator.from_config(main, extra_fetchers=[extra])
        assert "Hint: Declare the fetcher for [fetching.cache] in the same file." in exc_info.value.__notes__

    def test_delegating_mapper_factory_rejects_two_score_functions(self, tmp_path, monkeypatch):
        """A custom factory skips the shape checks, but the default factory it calls still has one score function."""

        def delegate(config: dict[str, Any], for_fetcher: bool) -> Any:
            return default_mapper_factory(config, for_fetcher)

        monkeypatch.setattr(TranslatorFactory, "MAPPER_FACTORY", delegate)
        two = "[translator.mapping.score_function.equality]\n[translator.mapping.score_function.disabled]\n"
        path = tmp_path / "main.toml"
        path.write_text(self.FETCHER + two, encoding="utf-8")
        with pytest.raises(ConfigFileError, match=r"must hold exactly one entry, got \['disabled', 'equality'\]"):
            Translator.from_config(path)

    def test_custom_mapper_factory_keeps_its_own_grammar(self, tmp_path, monkeypatch):
        received = []
        monkeypatch.setattr(TranslatorFactory, "MAPPER_FACTORY", lambda config, _for_fetcher: received.append(config))
        path = tmp_path / "main.toml"
        path.write_text(self.FETCHER + "[translator.mapping]\nfilter_functions = ['filter_names']\n", encoding="utf-8")
        Translator.from_config(path)
        assert received == [{"filter_functions": ["filter_names"]}]

    @pytest.mark.parametrize(
        "mapping",
        [
            "[fetching.mapping]\non_unmapped = 'ignore'\n",
            "[fetching.mapping.score_function.disabled]\n",
        ],
    )
    def test_fetcher_mapping_without_overrides(self, tmp_path, mapping):
        path = tmp_path / "main.toml"
        path.write_text(self.FETCHER + mapping, encoding="utf-8")
        translator: Translator[str, str, int] = Translator.from_config(path)
        assert translator.translate(1, names="people") == "1:Ada"


@pytest.mark.parametrize(
    "clazz, key, exc_type, match",
    [
        ("MemoryFetcher", "optional = 'true'", ConfigFileError, "Bad optional of type builtins.str"),
        # Checked before the import.
        ("'no_such_module.Fetcher'", "optional = 'true'", ConfigFileError, "Bad optional of type builtins.str"),
        # Checked by AbstractFetcher.
        ("MemoryFetcher", "identifiers = 'abc'", TypeError, "Bad identifiers of type builtins.str"),
        ("MemoryFetcher", "identifiers = 1", TypeError, "Bad identifiers of type builtins.int"),
    ],
)
def test_common_fetcher_key_types(tmp_path, clazz, key, exc_type, match):
    main = tmp_path / "main.toml"
    main.write_text("[fetching.MemoryFetcher.data.dogs]\nid = [1]\n", encoding="utf-8")
    extra = tmp_path / "extra.toml"
    extra.write_text(f"[fetching.{clazz}]\n{key}\ndata.people = {{ id = [1] }}\n", encoding="utf-8")
    with pytest.raises(exc_type, match=match) as exc_info:
        Translator.from_config(main, extra_fetchers=[extra])
    assert type(exc_info.value) is exc_type
    assert exc_info.value.__notes__ == [f"Hint: In file: {extra.resolve()}"]


def test_non_string_fmt(tmp_path):
    path = tmp_path / "main.toml"
    path.write_text("[translator]\nfmt = 1\n\n[fetching.MemoryFetcher.data.people]\nid = [1]\n", encoding="utf-8")
    with pytest.raises(TypeError, match=r"Bad fmt of type builtins\.int; expected a str or Format") as exc_info:
        Translator.from_config(path)
    assert exc_info.value.__notes__ == [f"Hint: In file: {path.resolve()}"]
