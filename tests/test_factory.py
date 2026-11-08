import logging
import re
from pathlib import Path
from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import ConfigurationError
from id_translation.fetching import AbstractFetcher, CacheAccess, MemoryFetcher, MultiFetcher
from id_translation.fetching.exceptions import UnknownPlaceholderError
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
    with pytest.raises(ConfigurationError) as e:
        Translator.from_config(path)
    assert str(path) in str(e.value)


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
    """A stray top-level `mapping` key is not used; the user wants `[translator.mapping]` or `[fetching.mapping]`."""
    main = """
    [translator]

    [fetching.MemoryFetcher]
    data = {}

    [mapping]
    """
    path = tmp_path / "main.toml"
    path.write_text(main, encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"Forbidden keys \['mapping'\]") as exc_info:
        Translator.from_config(path)
    assert "Hint: Use [translator.mapping] or [fetching.mapping]." in exc_info.value.__notes__


@pytest.mark.parametrize("key", ["default_fmt", "transformers", "mapper", "bad"])
def test_translator_section_rejects_other_keys(tmp_path, key):
    path = tmp_path / "main.toml"
    path.write_text(f"[translator]\n{key} = 1\n\n[fetching.MemoryFetcher]\ndata = {{}}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=rf"Forbidden keys \['{key}'\] in \[translator\]-section") as exc_info:
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

    with pytest.raises(ConfigurationError, match=rf"Top-level keys \['{key}'\] must be sections"):
        Translator.from_config(main, extra_fetchers=[fetcher])


def test_unknown_ids_section_is_named(tmp_path):
    path = tmp_path / "main.toml"
    path.write_text("[unknown_ids]\nbad = 1\n\n[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"Forbidden keys \['bad'\] in \[unknown_ids\]-section"):
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
        with pytest.raises(ConfigurationError, match=r"Forbidden keys \['default_fmt'\]"):
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

    with pytest.raises(ConfigurationError, match=r"Forbidden keys \['mapping'\]") as exc_info:
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

    @pytest.mark.parametrize("kwargs", ["", "ttl = 3600"])
    def test_type_key(self, tmp_path, kwargs):
        cache = f"""
        [fetching.cache]
        type = '{__name__}.{DummyCacheAccess.__name__}'
        {kwargs}
        """

        match = r"Expected only \[fetching.cache.'<type>'\]-sections in \[fetching.cache\]; got keys \[.*'type'\]"
        with pytest.raises(ConfigurationError, match=match) as exc_info:
            self.create(tmp_path, cache)
        assert not _suppress_hints(exc_info.value)

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
        assert any("bad-fetcher.toml" in note for note in exc_info.value.__notes__)
        assert _suppress_hints(exc_info.value), "optional=true; the variable would discard it"

    def test_not_optional(self, clazz, expected_error, caplog, tmp_path, monkeypatch):
        monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
        toml = f"""
        [fetching."{clazz}"]
        data = {{}}
        """

        with pytest.raises(ConfigurationError) as exc_info:
            self.run(caplog, tmp_path, toml, "not-used")

        assert str(expected_error) in repr(exc_info.value)
        assert not _suppress_hints(exc_info.value), "the variable cannot discard a fetcher that isn't optional"


def _suppress_hints(exc: BaseException) -> list[str]:
    notes = [*getattr(exc, "__notes__", []), *getattr(exc.__cause__, "__notes__", [])]
    return [note for note in notes if SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS in note]


def test_every_fetcher_discarded(tmp_path, monkeypatch):
    monkeypatch.setenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS, "true")
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    aux = tmp_path / "fetcher.toml"
    aux.write_text(f"[fetching.'{__name__}.CrashesOnInitFetcher']\noptional = true\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=r"All \[fetching\]-sections were discarded as optional"):
        Translator.from_config(main, extra_fetchers=[aux])


class CrashesOnInitFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ValueError("I always crash!")


class ConfigurationErrorOnInitFetcher(MemoryFetcher[Any, Any]):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        raise ConfigurationError("Bad option.", hints="Use another option.")


def test_optional_fetcher_configuration_error_is_not_rewrapped(tmp_path):
    main = tmp_path / "main.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    aux = tmp_path / "fetcher.toml"
    aux.write_text(
        f"[fetching.'{__name__}.ConfigurationErrorOnInitFetcher']\noptional = true\ndata = {{}}\n", encoding="utf-8"
    )

    with pytest.raises(ConfigurationError) as exc_info:
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

        with pytest.raises(ConfigurationError, match=r"Forbidden keys \['max_wokers'\] in \[fetching.MultiFetcher\]"):
            Translator.from_config(main)

    def test_bad_value_with_one_fetcher(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER + "[fetching.MultiFetcher]\non_source_conflict = 'bad'\n", encoding="utf-8")

        with pytest.raises(ConfigurationError, match=r"Bad on_source_conflict='bad'") as exc_info:
            Translator.from_config(main)
        assert f"Hint: In file: {main.resolve()}" in exc_info.value.__notes__

    def test_bad_value_names_file(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER + "[fetching.MultiFetcher]\non_source_conflict = 'bad'\n", encoding="utf-8")
        aux = tmp_path / "aux.toml"
        aux.write_text(self.FETCHER, encoding="utf-8")

        with pytest.raises(ConfigurationError) as exc_info:
            Translator.from_config(main, extra_fetchers=[aux])
        assert f"Hint: In file: {main.resolve()}" in exc_info.value.__notes__

    def test_in_auxiliary_file(self, tmp_path):
        main = tmp_path / "main.toml"
        main.write_text(self.FETCHER, encoding="utf-8")
        aux = tmp_path / "aux.toml"
        aux.write_text(self.FETCHER + "[fetching.MultiFetcher]\nmax_workers = 2\n", encoding="utf-8")

        with pytest.raises(ConfigurationError, match=r"allowed in the main file only") as exc_info:
            Translator.from_config(main, extra_fetchers=[aux])
        assert any(str(aux) in note for note in exc_info.value.__notes__)


@pytest.mark.parametrize(
    "content",
    ["fetching = [\n", "[translator]\nfmt = '${ID_TRANSLATION_SURELY_UNSET}'\n", b"[translator]\nfmt = '\xff'\n"],
)
@pytest.mark.parametrize("broken", ["main.toml", "fetcher.toml"])
def test_file_content_errors_are_configuration_errors(tmp_path, broken, content):
    """One exception type for any problem with a file's content, naming the file once; the original is the cause."""
    main, fetcher = tmp_path / "main.toml", tmp_path / "fetcher.toml"
    main.write_text("[translator]\n", encoding="utf-8")
    fetcher.write_text("[fetching.MemoryFetcher]\ndata = {}\n", encoding="utf-8")
    if isinstance(content, bytes):
        (tmp_path / broken).write_bytes(content)  # Not UTF-8.
    else:
        (tmp_path / broken).write_text(content, encoding="utf-8")

    with pytest.raises(ConfigurationError) as exc_info:
        Translator.from_config(main, extra_fetchers=[fetcher])

    assert exc_info.value.__cause__ is not None
    assert [n for n in exc_info.value.__notes__ if n.startswith("Hint: In file:")] == [
        f"Hint: In file: {(tmp_path / broken).resolve()}"
    ]


def test_missing_file_is_an_os_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        Translator.from_config(tmp_path / "missing.toml")


@pytest.mark.parametrize("key", ["mapper", "cache_access"])
def test_fetcher_keys_that_have_their_own_section(tmp_path, key):
    path = tmp_path / "main.toml"
    path.write_text(f"[fetching.MemoryFetcher]\ndata = {{}}\n{key} = 'x'\n", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=rf"Keys \['{key}'\] are not allowed in \[fetching.MemoryFetcher\]"):
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

    with pytest.raises(ConfigurationError, match=rf"not allowed in \[{section}.mapping\]") as exc_info:
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

    cached = Translator[str, str, int].load_persistent_instance(
        "~/cache", "~/main.toml", extra_fetchers="~/fetcher.toml"
    )
    assert cached.translate(1, names="s") == "1!"
