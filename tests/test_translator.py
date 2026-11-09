import inspect
import logging
import subprocess
import sys
import warnings
from contextlib import contextmanager
from itertools import product
from types import MappingProxyType
from typing import Any, assert_type
from unittest.mock import Mock
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from id_translation import Translator as RealTranslator
from id_translation.dio.exceptions import NotInplaceTranslatableError, UntranslatableTypeError
from id_translation.exceptions import (
    ConfigurationChangedError,
    ConnectionStatusError,
    MissingNamesError,
    NoSourcesError,
    TooManyFailedTranslationsError,
    TranslationAbortedWarning,
    TranslationDisabledWarning,
    TranslationWarning,
)
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.logging import enable_verbose_debug_messages
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import (
    BadOverrideError,
    MappingWarning,
    UnmappedExplicitNamesError,
    UserMappingError,
)
from id_translation.toml.meta import _config_metadata
from id_translation.transform import BitmaskTransformer

from .conftest import ROOT, NotCloneableFetcher

LOGGER = logging.getLogger("UnitTestTranslator")


def crash(*args, **kwargs):
    raise AssertionError(f"Called with: {args=}, {kwargs=}.")


@contextmanager
def verification_context(purpose):
    LOGGER.info(f"{f' Start: {purpose} ':=^80}")
    yield
    LOGGER.info(f"{f' Stop: {purpose} ':=^80}")


class UnitTestTranslator(RealTranslator[str, str, int]):
    """Test implementation that performs additional verification."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.now = pd.Timestamp.now()


class SlottedTranslator(RealTranslator[str, str, int]):
    """Subclass state lives outside `__dict__`; see `test_pickle_keeps_subclass_slots`. Module-level to be picklable."""

    __slots__ = ("tag",)

    tag: str


class ConfigMetadataForTest(_config_metadata.ConfigMetadata):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        assert self.clazz in ("id_translation._translator.Translator", "tests.test_translator.Translator")


@pytest.mark.parametrize("with_id, with_override, store", list(product([False, True], repeat=3)))
def test_dummy_translation_doesnt_crash(with_id, with_override, store):
    t = UnitTestTranslator(fmt="{id}:{first}:{second}:{third}")

    names = list(map("placeholder{}".format, range(3)))
    data = np.random.default_rng(2019_05_11).integers(0, 100, (3, 10))

    def override_function(name: str, *_: Any) -> str | None:
        return names[0] if name == "id" else None

    if with_id:
        names[0] = "id"
    if store:
        t.go_offline(data, names=names)

    ans = t.translate(
        data,
        names=names,
        override_function=override_function if with_override else None,
    )
    assert ans is not None
    assert isinstance(ans, np.ndarray)
    assert ans.shape == (3, 10)


def test_translate_without_id(hex_fetcher):
    without_id = "{hex}, positive={positive}"
    ans = UnitTestTranslator(hex_fetcher, fmt=without_id).translate({"positive_numbers": [-1, 0, 1]})
    assert ans == {
        "positive_numbers": [
            "<Failed: id=-1>",
            "0x0, positive=True",
            "0x1, positive=True",
        ]
    }


@pytest.mark.parametrize("copy", [False, True])
def test_can_pickle(translator, copy):
    from rics.misc import serializable

    assert serializable(translator.copy() if copy else translator)


def test_pickle_keeps_subclass_slots():
    import pickle

    translator = SlottedTranslator({"guests": {"id": [1], "name": ["a"]}})
    translator.tag = "kept"

    assert pickle.loads(pickle.dumps(translator)).tag == "kept"  # noqa: S301


@pytest.mark.parametrize("copy", [False, True])
def test_offline(hex_fetcher, copy):
    translator = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]").go_offline()
    if copy:
        translator = translator.copy()
    _translate(translator)


@pytest.mark.parametrize("copy", [False, True])
def test_online(translator, copy):
    _translate(translator.copy() if copy else translator)


def test_unmapped_explicit_names_error(translator):
    with pytest.raises(UnmappedExplicitNamesError):
        translator.map(0, names="unknown")


def test_unmapped_explicit_names_error_when_others_map(translator):
    with pytest.raises(UnmappedExplicitNamesError) as exc_info:
        translator.map(0, names=["positive_numbers", "unknown"])
    assert exc_info.value.unmapped == ("unknown",)


def test_map_scores_shows_unmapped_explicit_names(translator):
    scores = translator.map_scores(0, names=["positive_numbers", "unknown"]).to_pandas()
    assert scores.index.tolist() == ["positive_numbers", "unknown"]


def test_unmapped_explicit_names_error_when_filtered(hex_fetcher):
    mapper: Mapper[str, str, None] = Mapper(
        "equality", filter_functions=[("filter_names", {"regex": "^positive_numbers$"})]
    )
    translator = UnitTestTranslator(hex_fetcher, mapper=mapper)
    data = {"positive_numbers": [1], "negative_numbers": [-1]}

    with pytest.raises(UnmappedExplicitNamesError) as exc_info:
        translator.map(data, names=["positive_numbers", "negative_numbers"])
    assert exc_info.value.unmapped == ("negative_numbers",)

    as_dict = {"positive_numbers": "positive_numbers", "negative_numbers": "negative_numbers"}
    assert translator.map(data, names=as_dict) == as_dict


class TestExtractNames:
    @pytest.mark.parametrize(
        "ignore_names, expected",
        [
            (None, ["dict-key"]),
            ([], ["dict-key"]),
            (["some-string"], ["dict-key"]),
        ],
    )
    def test_ok(self, translator, ignore_names, expected):
        data = {"dict-key": 0}
        actual = translator.extract_names(data, ignore_names=ignore_names)
        assert actual == expected

    def test_warning_returns_empty_list(self, translator):
        data = {"dict-key": 0}
        with pytest.warns(MappingWarning, match="No names left to translate.") as w:
            actual = translator.extract_names(data, ignore_names=["dict-key"])
        assert actual == []
        assert len(w) == 1
        assert w[0].filename == __file__

    def test_raising_true(self, translator):
        with pytest.raises(MissingNamesError, match=r"Failed to derive names for 'int'-type data."):
            translator.extract_names(1, raising=True)

    def test_raising_false(self, translator):
        actual = translator.extract_names(1, raising=False)
        assert actual is None


def _translate(translator):
    ans = translator.translate({"positive_numbers": [-1, 0, 1, 2], "negative_numbers": [-1, 0]})
    assert ans == {
        "positive_numbers": [
            "<Failed: id=-1>",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
            "2:0x2, positive=True",
        ],
        "negative_numbers": [
            "-1:-0x1, positive=False",
            "0:0x0, positive=True",
        ],
    }


@pytest.mark.parametrize(
    "data,clazz,kwargs",
    [
        (object(), UntranslatableTypeError, {"names": 1}),
        ((1, 2), MissingNamesError, {}),
        ((1, 2), NotInplaceTranslatableError, {"copy": False, "names": "positive_numbers"}),
    ],
)
def test_bad_translatable(translator, data, clazz, kwargs):
    with pytest.raises(clazz):
        translator.translate(data, **kwargs)


def test_from_config():
    translator = UnitTestTranslator.from_config(ROOT.joinpath("config.toml"))
    assert type(translator) is UnitTestTranslator

    actual = translator.config_metadata

    assert actual.main[0].name == "config.toml"
    assert actual.main[1] == "5d4fb2b2588712125ba367d1809bebac6225b4d8e15461a77455347db424df9b"
    assert actual.extra_fetchers == ()

    assert sorted(actual.to_dict()) == ["class", "created", "extra_fetchers", "main", "metaconf", "versions"]
    assert actual.clazz == "tests.test_translator.UnitTestTranslator"
    assert sorted(actual.versions) == ["id-translation", "python"]
    assert actual.metaconf.equivalence.extra_packages == []

    reason_not_equivalent = actual.is_equivalent(actual)
    assert reason_not_equivalent == ""


def test_copy_keeps_the_config_metadata(tmp_path):
    path = tmp_path / "translation.toml"
    path.write_text('[fetching.MemoryFetcher.data]\nanimals = { id = [1], name = ["Tarzan"] }\n', encoding="utf-8")
    translator: RealTranslator[str, str, int] = RealTranslator.from_config(path)

    assert translator.copy().config_metadata is translator.config_metadata
    assert translator.copy(transformers={}).config_metadata is translator.config_metadata


def test_store_and_restore(hex_fetcher, tmp_path):
    translator: UnitTestTranslator = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}")

    data = {
        "positive_numbers": list(range(0, 5)),
        "negative_numbers": list(range(-5, -1)),
    }
    translated_data = translator.translate(data)

    path = tmp_path.joinpath("translator.pkl")
    translator.go_offline(path=path)
    restored = UnitTestTranslator.restore(path=path)

    translated_by_restored = restored.translate(data)
    assert translated_by_restored == translated_data


def test_restore_a_subtype(hex_fetcher, tmp_path):
    path = tmp_path.joinpath("translator.pkl")
    UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}").go_offline({"positive_numbers": [1]}, path=path)

    restored: RealTranslator[str, str, int] = RealTranslator.restore(path)
    assert isinstance(restored, UnitTestTranslator)


def test_restore_rejects_a_foreign_snapshot(hex_fetcher):
    """restore() is handed a path it cannot version-check, so the shape has to be recognised on the way in."""
    translator: UnitTestTranslator = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}")
    translator.go_offline({"positive_numbers": [1]})

    state: dict[str, Any] = dict(vars(translator))
    del state["_tx"]  # The shape a snapshot from before TransformerRegistry unpickles into.
    revived: UnitTestTranslator = UnitTestTranslator.__new__(UnitTestTranslator)

    with pytest.raises(ValueError, match="incompatible version"):
        revived.__setstate__(state)


def test_store_with_explicit_values(hex_fetcher):
    data = {
        "positive_numbers": list(range(0, 5)),
        "negative_numbers": list(range(-5, -1)),
    }
    translator = UnitTestTranslator(
        hex_fetcher, fmt="{hex}", default_fmt="{id} not known", mapper=Mapper(on_unmapped="ignore")
    )

    translator.go_offline(data)
    expected_num_fetches = hex_fetcher.num_fetches
    assert sorted(translator.cache.sources) == sorted(data)
    actual = translator.translate(data)
    assert hex_fetcher.num_fetches == expected_num_fetches
    assert actual == {
        "positive_numbers": list(map(hex, range(0, 5))),
        "negative_numbers": list(map(hex, range(-5, -1))),
    }

    unknown_data = {
        "positive_numbers": [5, 6],
        "negative_numbers": [-100, -6],
    }
    assert translator.translate(unknown_data) == {
        "positive_numbers": ["5 not known", "6 not known"],
        "negative_numbers": ["-100 not known", "-6 not known"],
    }


def test_go_fetch_without_mapped_names_returns_empty_translations():
    translator = UnitTestTranslator(
        MemoryFetcher(data={"source": {1: "one"}}),
        mapper=Mapper(score_function_kwargs={"strict": False}),
    )

    with pytest.warns(TranslationAbortedWarning, match="Translation aborted; none of the derived names"):
        tmap = translator.fetch({"not-source": 1})
    assert tmap.sources == []

    with (
        pytest.warns(TranslationAbortedWarning, match="Translation aborted; none of the derived names"),
        pytest.raises(NoSourcesError, match="Nothing to take offline"),
    ):
        translator.go_offline({"not-source": 1})
    assert translator.online, "raised before the fetcher was closed"


def test_mapping_nothing_to_translate(translator):
    with pytest.warns(TranslationAbortedWarning) as w:
        translator.map({"strange-name": [1, 2, 3]})

    assert len(w) == 1
    assert w[0].filename == __file__
    assert "aborted; none of the derived names" in str(w[0])
    assert "['strange-name']" in str(w[0])


def test_all_name_ignored(translator):
    with pytest.warns(MappingWarning, match="No names left") as w:
        translator.translate(pd.Series(name="name"), ignore_names="name")
    assert len(w) == 1

    assert w[0].filename == __file__
    mapping_warning = str(w[0].message)
    assert "derived names=['name']" in mapping_warning
    assert "ignore_names=['name']" in mapping_warning


def test_explicit_name_ignored(translator):
    with pytest.raises(ValueError) as e:
        translator.map(0, names=[], ignore_names="")
    assert "Explicit names" in str(e)
    assert "cannot be used with ignore_names=" in str(e)


def test_complex_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    default_fmt = "{id} - {hex} - {positive}"
    default_fmt_placeholders = {"default": {"positive": "POSITIVE/NEGATIVE", "hex": "HEX"}}
    t = UnitTestTranslator(
        hex_fetcher, fmt=fmt, default_fmt=default_fmt, default_fmt_placeholders=default_fmt_placeholders
    ).go_offline()

    in_range = t.translate({"positive_numbers": [-1, 0, 1]})
    assert in_range == {
        "positive_numbers": [
            "-1 - HEX - POSITIVE/NEGATIVE",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {
        "positive_numbers": [
            "-5000 - HEX - POSITIVE/NEGATIVE",
            "10000 - HEX - POSITIVE/NEGATIVE",
        ]
    }


def test_id_only_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    default_fmt = "{id} is not known"
    t = UnitTestTranslator(hex_fetcher, fmt=fmt, default_fmt=default_fmt).go_offline()

    in_range = t.translate({"positive_numbers": [-1, 0, 1]})
    assert in_range == {
        "positive_numbers": [
            "-1 is not known",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {
        "positive_numbers": [
            "-5000 is not known",
            "10000 is not known",
        ]
    }


def test_extra_placeholder():
    t = UnitTestTranslator(
        {"people": {"id": [1999], "name": ["Sofia"]}},
        default_fmt="{id}:{right}",
        default_fmt_placeholders=dict(default={"left": "left-value", "right": "right-value"}),
    )
    assert t.translate(1999, "people") == "1999:Sofia"

    assert t.translate(1, names="people") == "1:right-value"

    t = t.copy(default_fmt="{left}, {right}")
    assert t.translate(1, names="people") == "left-value, right-value"

    t = t.copy(default_fmt_placeholders=dict(default={"left": "LEFT", "right": "RIGHT"}))
    assert t.translate(1, names="people") == "LEFT, RIGHT"

    with pytest.raises(TooManyFailedTranslationsError):
        t.translate(1, names="people", max_fails=0)


def test_plain_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    default_fmt = "UNKNOWN"
    t = UnitTestTranslator(hex_fetcher, fmt=fmt, default_fmt=default_fmt).go_offline()

    in_range = t.translate({"positive_numbers": [-1, 0, 1]})
    assert in_range == {
        "positive_numbers": [
            "UNKNOWN",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {"positive_numbers": ["UNKNOWN", "UNKNOWN"]}


def test_no_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    t = UnitTestTranslator(hex_fetcher, fmt=fmt).go_offline()
    in_range = t.translate({"positive_numbers": [-1, 0, 1]})
    assert in_range == {
        "positive_numbers": [
            "<Failed: id=-1>",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {
        "positive_numbers": ["<Failed: id=-5000>", "<Failed: id=10000>"],
    }


def test_imdb_discovery(imdb_translator):
    assert sorted(imdb_translator._fetcher.sources) == ["name_basics", "title_basics"]


def test_copy_with_override(imdb_translator):
    data = {"nconst": [1, 15]}

    assert imdb_translator.translate(data) == {
        "nconst": ["1:Fred Astaire from: 1899, to: 1987", "15:James Dean from: 1931, to: 1955"]
    }

    copy0 = imdb_translator.copy(fmt="Number {id} is {name}")
    assert copy0.translate(data) == {"nconst": ["Number 1 is Fred Astaire", "Number 15 is James Dean"]}

    copy1 = imdb_translator.copy(fmt="{name}")
    assert copy1.translate(data) == {"nconst": ["Fred Astaire", "James Dean"]}


def test_copy_with_transformers(imdb_translator):
    assert imdb_translator._tx._transformers == {}

    copy0 = imdb_translator.copy(transformers={"source": BitmaskTransformer()})

    copy1 = copy0.copy()
    assert copy0._tx._transformers == copy1._tx._transformers
    assert id(copy0._tx._transformers) != id(copy1._tx._transformers)
    assert id(copy0._tx._transformers["source"]) != id(copy1._tx._transformers["source"])


def test_no_names(translator):
    with pytest.raises(MissingNamesError):
        translator.translate(pd.Series(range(3)))


def test_untranslated_fraction_single_name():
    translator = UnitTestTranslator({"source": {"id": [0], "name": ["zero"]}}, default_fmt="{id} not translated")

    translator.translate([0, 1], names="source", max_fails=0.5)

    with pytest.raises(TooManyFailedTranslationsError, match="translate 1/3"):
        translator.translate([0, 0, 1], names="source", max_fails=0.0)

    with pytest.raises(TooManyFailedTranslationsError, match="translate 1/1"):
        translator.translate(1, names="source", max_fails=0.0)


def test_untranslated_fraction_when_a_source_shares_a_name():
    data = {"humans": {"id": [1, 2], "name": ["Ada", "Bob"]}, "animals": {"id": [10], "name": ["Rex"]}}
    translator = UnitTestTranslator(data)
    translatable = {"humans": [10], "owner": [1, 2]}

    actual = translator.translate(translatable, names={"humans": "animals", "owner": "humans"}, max_fails=0.0)
    assert actual == {"humans": ["10:Rex"], "owner": ["1:Ada", "2:Bob"]}


def test_untranslated_fraction_ignores_other_sources():
    data = {"staff": {"id": [1], "name": ["Ada"], "team": ["sales"]}, "dogs": {"id": [1], "name": ["Rex"]}}
    translator = UnitTestTranslator(data)

    assert translator.translate(1, names="staff", fmt="{name} ({team})", max_fails=0.5) == "Ada (sales)"


@pytest.mark.parametrize("max_fails", [0.0, 1.0])
def test_untranslated_ids_with_braces(max_fails, caplog):
    translator = UnitTestTranslator({"source": {"id": ["a"], "name": ["A"]}})

    with caplog.at_level(logging.DEBUG, logger="id_translation"):
        if max_fails:
            translator.translate(["a", "{b}"], names="source", max_fails=max_fails)
        else:
            with pytest.raises(TooManyFailedTranslationsError, match=r"Sample IDs: \['\{b\}'\]"):
                translator.translate(["a", "{b}"], names="source", max_fails=max_fails)

    assert any("Sample IDs: ['{b}']" in r.getMessage() for r in caplog.records)


def test_untranslated_fraction_multiple_names(translator, hex_fetcher):
    translator = UnitTestTranslator(hex_fetcher, enable_uuid_heuristics=True, fmt="{id}:{hex}")
    translatable = {"negative_numbers": [1, 1], "positive_numbers": [0, 1, 2]}

    with pytest.raises(TooManyFailedTranslationsError, match="translate 2/2"):
        translator.translate(translatable, max_fails=0.0)


def test_untranslated_reporting(caplog):
    translator = UnitTestTranslator({"source": {"id": [0, 1, 2, 3, 4]}}, fmt="{id}")
    translator.translate(
        {"none": [-1, -100], "partial": [-1, 1, 2], "all": [0, 1]},
        override_function=lambda *_: "source",
        copy=False,
    )

    for r in caplog.records:
        if r.module != "_verify":
            continue

        assert r.source_of_ids == "source"

        if r.name_of_ids == "none":
            assert r.sample_ids == [-1, -100]
        elif r.name_of_ids == "partial":
            assert r.sample_ids == [-1]
        else:
            raise AssertionError(f"unexpected record: {r}")


def test_reverse(hex_fetcher):
    translator = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]").go_offline()

    translated = {"positive_numbers": ["<Failed: id=-1>", "0:0x0, positive=True", "1:0x1, positive=True"]}
    assert_type(translated, dict[str, list[str]])
    assert translated == translator.translate({"positive_numbers": [-1, 0, 1]}, copy=True)

    actual = translator.translate(translated, reverse=True)
    assert_type(actual, dict[str, list[int]])  # type: ignore[assert-type]  # Overloads are incomplete for reverse=True
    assert actual == {"positive_numbers": ["<Failed: id='<Failed: id=-1>'>", 0, 1]}, "Original format"

    with pytest.raises(TooManyFailedTranslationsError, match=r"Sample IDs: \['<Failed: id=-1>'\]"):
        translator.translate(translated, reverse=True, max_fails=0)


def test_reverse_primitive(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    t = UnitTestTranslator(hex_fetcher, fmt=fmt).go_offline()

    translated = "1:0x1, positive=True"
    actual = t.translate(translated, reverse=True, names="positive_numbers")
    assert_type(actual, int)  # type: ignore[assert-type]  # Can't make this work without overlapping overloads
    assert actual == 1


def test_reverse_uuid_like_translations_verify():
    u = UUID(int=5)
    t: RealTranslator[str, str, UUID] = RealTranslator({"s": {u: "five"}}, enable_uuid_heuristics=True, fmt="{id}")
    forward = t.translate({"s": [u]})
    assert t.translate(forward, reverse=True, max_fails=0.0) == {"s": [u]}


@pytest.mark.parametrize("online", [True, False])
def test_unknown_source_from_names_or_overrides(online):
    data = {"a": {1: "A"}}
    mapper: Mapper[str, str, None] = Mapper(overrides={"y": "nope"})
    translator = RealTranslator[str, str, int](MemoryFetcher(data) if online else data, mapper=mapper)

    with pytest.raises(UserMappingError, match=r"names=\{'x': 'nope'\} maps 'x' to unknown source='nope'") as exc_info:
        translator.translate({"x": 1}, names={"x": "nope"})
    assert exc_info.value.value == "x"

    with pytest.raises(BadOverrideError, match="Mapper overrides map 'y' to unknown source='nope'") as override_info:
        translator.translate({"y": 1}, names="y")
    assert (override_info.value.value, override_info.value.candidate) == ("y", "nope")


class _DownFetcher(MemoryFetcher[str, int]):
    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        raise ConnectionError("down")


def test_override_to_discarded_optional_source():
    # Checked at use, not at discovery: one bad override must not break every translation.
    fetcher = MultiFetcher(MemoryFetcher({"a": {1: "A"}}), _DownFetcher({"b": {1: "B"}}, optional=True))
    mapper: Mapper[str, str, None] = Mapper("equality", overrides={"y": "b"})
    translator = RealTranslator[str, str, int](fetcher, mapper=mapper).initialize_sources()

    assert translator.translate({"a": 1}) == {"a": "1:A"}
    with pytest.raises(BadOverrideError):
        translator.translate({"y": 1})


def test_test_fetcher_serves_unlisted_names_sources():
    translator = RealTranslator[str, str, int]()
    assert translator.translate({"x": 1}, names={"x": "anything"}) == {"x": "1:name-of-1"}
    assert translator.go_offline({"x": 1}, names={"x": "anything"}).sources == ["anything"]


def test_simple_function_overrides(translator):
    actual = translator.translate(1, names="whatever", override_function=lambda *_: "positive_numbers")
    assert actual == "1:0x1, positive=True"

    actual = translator.translate(1, names="positive_numbers", override_function=lambda *_: None)
    assert actual == "1:0x1, positive=True"

    with pytest.raises(UserMappingError):
        translator.translate(1, names="whatever", override_function=lambda *_: "bad")


def test_copy_rejects_fetcher_override(translator):
    with pytest.raises(TypeError, match="FetcherCopyMode"):
        translator.copy(fetcher={"positive_numbers": {"id": [1], "hex": ["0x1"], "positive": [True]}})


def test_offline_copy_keeps_snapshot_cache():
    original: RealTranslator[str, str, int]
    original = RealTranslator(MemoryFetcher({"people": {"id": [1, 2], "name": ["Richard", "Sofia"]}}))
    original.go_offline({"person_id": [1]}, names={"person_id": "people"}, fmt="{name}")

    copy = original.copy()
    assert copy.cache.name_to_source == {"person_id": "people"}
    assert copy.cache["person_id"][1] == "Richard"

    assert original.copy(fmt="{id}-{name}").cache["people"][1] == "1-Richard"


def test_float_ids(translator):
    from id_translation._tasks import TranslationTask
    from id_translation.offline import Format

    translatable = {"positive_numbers": [0.0, 0, 1, 0.1, float("nan"), np.nan, 3, np.nan]}
    task = TranslationTask(translator, translatable, fmt=Format(""), event_key=test_float_ids.__name__)
    ids_to_fetch = task.extract_ids()
    assert len(ids_to_fetch) == 1
    ids = ids_to_fetch["positive_numbers"]
    assert ids == {0, 1, 3}


def test_load_persistent_instance(tmp_path):
    config_path = ROOT.joinpath("dvdrental/translation.toml")  # Uses an in-memory fetcher.

    expected = ["<Failed: id=0>", "1:Action", "2:Animation"]
    translatable: list[int] = [0, 1, 2]
    args = (translatable, "category_id")

    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path)
    assert type(translator) is UnitTestTranslator
    now = translator.now
    assert translator.translate(*args) == expected

    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path)
    assert type(translator) is UnitTestTranslator
    assert translator.now == now
    assert translator.translate(*args) == expected

    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path, max_age="0 days")
    assert type(translator) is UnitTestTranslator
    assert translator.now > now
    assert translator.translate(*args) == expected

    now = translator.now
    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path, max_age=None)
    assert type(translator) is UnitTestTranslator
    assert translator.now == now
    assert translator.translate(*args) == expected

    real_translator: RealTranslator[str, str, int] = RealTranslator.load_persistent_instance(tmp_path, config_path)
    assert type(real_translator) is RealTranslator
    assert real_translator.translate(*args) == expected

    metadata_path = tmp_path / "metadata.json"
    metadata = ConfigMetadataForTest.from_json(metadata_path.read_text())
    metadata.versions["python"] = "-1"
    metadata_path.write_text(metadata.to_json())
    with pytest.raises(
        ConfigurationChangedError,
        match=r"cached instance is not equivalent: Expected python='3\.\d+\.\d+' \(your environment\) but got python='-1'",
    ) as exc_info:
        RealTranslator.load_persistent_instance(tmp_path, config_path, on_config_changed="raise")
    assert exc_info.value.cache_dir == str(tmp_path)
    assert "on_config_changed='recreate'" in exc_info.value.__notes__[0]

    real_translator = RealTranslator.load_persistent_instance(tmp_path, config_path)
    assert type(real_translator) is RealTranslator
    assert real_translator.translate(*args) == expected
    assert not isinstance(real_translator, UnitTestTranslator)


@pytest.mark.parametrize(
    "ids, names, expected_untranslated",
    [
        ([1, -1, 2], "pnp", []),
        ([1, -1, 2], "nnp", [0]),
        ([1, 1, -2], "ppp", [2]),
        ([1, 1, -2], "p", [2]),
    ],
)
def test_repeated_names(translator, ids, names, expected_untranslated):
    names = list(names)

    actual = translator.translate(ids, names)
    assert len(actual) == len(ids)
    for i in expected_untranslated:
        assert actual[i] == f"<Failed: id={ids[i]}>"

    if len(ids) != len(names):
        return

    # DataFrames are unique in that they are dict-like but permit duplicated keys (column labels)
    df = pd.DataFrame([[n] for n in ids]).T
    df.columns = names
    actual = translator.translate(df)
    for i in expected_untranslated:
        assert actual.iloc[0, i] == f"<Failed: id={ids[i]}>"


def test_temporary_translate_fmt(translator, monkeypatch):
    monkeypatch.setattr(RealTranslator, "copy", crash)

    assert translator.translate([0, 1], names="positive_numbers") == ["0:0x0, positive=True", "1:0x1, positive=True"]

    expected_fmt = translator._fmt
    assert translator.translate([0, 1], names="positive_numbers", fmt="{id}:{hex}") == ["0:0x0", "1:0x1"]
    assert translator._fmt == expected_fmt

    assert translator.translate([0, 1], names="positive_numbers") == ["0:0x0, positive=True", "1:0x1, positive=True"]


@pytest.mark.parametrize(
    "names, iterables",
    [
        (["digit"], [["a", "b"], ["1:name-of-1", "2:name-of-2", "3:name-of-3"]]),
        (["letter"], [["a:name-of-a", "b:name-of-b"], [1, 2, 3]]),
        (["letter", "digit"], [["a:name-of-a", "b:name-of-b"], ["1:name-of-1", "2:name-of-2", "3:name-of-3"]]),
        (None, [["a:name-of-a", "b:name-of-b"], ["1:name-of-1", "2:name-of-2", "3:name-of-3"]]),
    ],
)
def test_translate_multi_index(names, iterables):
    from pandas.testing import assert_index_equal

    expected = pd.MultiIndex.from_product(iterables, names=["letter", "digit"])
    actual = pd.MultiIndex.from_product([["a", "b"], [1, 2, 3]], names=["letter", "digit"])

    translator = UnitTestTranslator()
    actual = translator.translate(actual, names=names)
    assert_index_equal(actual, expected)


def test_id_translation_disabled(monkeypatch, caplog):
    from id_translation._translator import ID_TRANSLATION_DISABLED

    translator = UnitTestTranslator()

    monkeypatch.setenv(ID_TRANSLATION_DISABLED, "true")
    with pytest.warns(TranslationDisabledWarning):
        assert translator.translate(1, names="whatever") == 1

    monkeypatch.setenv(ID_TRANSLATION_DISABLED, "TRUE")
    with pytest.warns(TranslationDisabledWarning):
        assert translator.translate(1, names="whatever") == 1

    assert len(caplog.records) == 2
    assert all(ID_TRANSLATION_DISABLED in r.msg for r in caplog.records)

    monkeypatch.setenv(ID_TRANSLATION_DISABLED, "false")
    assert translator.translate(1, names="whatever") == "1:name-of-1"
    monkeypatch.delenv(ID_TRANSLATION_DISABLED)
    assert translator.translate(1, names="whatever") == "1:name-of-1"


def test_id_translation_disabled_honours_warning_flag(monkeypatch):
    from id_translation._translator import ID_TRANSLATION_DISABLED

    monkeypatch.setenv(ID_TRANSLATION_DISABLED, "true")
    script = "from id_translation import Translator; Translator({'s': {1: 'a'}}).translate(1, names='s')"
    args = [sys.executable, "-W", "error", "-c", script]
    result = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    assert "TranslationDisabledWarning" in result.stderr
    assert result.returncode != 0


class TestDictNames:
    translate: Any

    @classmethod
    def setup_class(cls):
        tmp = UnitTestTranslator.from_config(ROOT.joinpath("config.imdb.toml"))
        translator = tmp.copy(
            fmt="{id}:{name}",
            mapper=tmp.mapper.copy(on_unknown_user_override="keep"),
        )
        assert "name_basics" in translator.sources
        cls.translate = translator.translate

    def test_override_info_in_logs(self, caplog):
        expected = {"nconst": ["1:Fred Astaire", "15:James Dean"]}

        with enable_verbose_debug_messages():
            assert self.translate({"nconst": [1, 15]}, names={"nconst": "name_basics"}) == expected
        record = next(record for record in caplog.messages if "names={'nconst': 'name_basics'}" in record)
        assert "override_function=UserArgument" in record

    def test_dict_with_override_function(self):
        with pytest.raises(ValueError, match="Mapping names="):
            assert self.translate("", names={}, override_function=crash)

    def test_mapping_to_unknown_source(self):
        with pytest.raises(UserMappingError, match="maps 'nconst' to unknown source='unknown-source'"):
            self.translate({"nconst": [1, 15]}, names={"nconst": "unknown-source"})

    def test_forbidden_value(self):
        with pytest.raises(ValueError, match="Bad name-to-source mapping: 'nconst' -> None"):
            self.translate("", names={"nconst": None})

    def test_no_names(self):
        with pytest.warns(TranslationAbortedWarning, match="aborted.*override_function=UserArgument"):
            assert self.translate({"nconst": [1, 15]}, names={}) == {"nconst": [1, 15]}


class TestTranslatedNames:
    translator = UnitTestTranslator()

    def test_unused(self):
        with pytest.raises(ValueError, match=r"No names have been translated using this Translator."):
            self.translator.translated_names()

    def test_multiple(self):
        self.translator.translate([1, 2, 3], names=list("abc"))
        assert self.translator.translated_names() == {char: char for char in "abc"}

    def test_single(self):
        self.translator.translate([1, 2, 3], names="a")
        assert self.translator.translated_names() == {"a": "a"}

    @staticmethod
    def type_check():
        from typing import assert_type

        assert_type(UnitTestTranslator().translated_names(), dict[str, str])


def test_fetch(translator):
    from id_translation.dio import resolve_io

    translatable = {"numbers": [-1, 0, 1]}
    name_to_source = {"numbers": "positive_numbers"}
    tmap = translator.fetch(translatable, names=name_to_source)
    assert translator.online

    actual = resolve_io(translatable).insert(translatable, list(translatable), tmap, True)  # type: ignore[arg-type]
    assert actual == translator.translate(translatable, names=name_to_source)


def test_fetch_args(translator):
    with pytest.raises(TooManyFailedTranslationsError):
        translator.fetch({"positive_numbers": [-1]}, max_fails=0)

    assert translator.fetch({"positive_numbers": [-1]}).to_dicts() == {
        "positive_numbers": {"hex": [], "id": [], "positive": []}
    }
    assert translator.fetch({"positive_numbers": [1]}).to_dicts() == {
        "positive_numbers": {"hex": ["0x1"], "id": [1], "positive": [True]}
    }
    assert translator.online


def test_go_offline_args(translator):
    original_fetcher_id = id(translator.fetcher)
    translator = translator.copy()

    assert translator.online
    assert id(translator.fetch) != original_fetcher_id

    with pytest.raises(TooManyFailedTranslationsError):
        translator.go_offline({"positive_numbers": [-1]}, max_fails=0)
    assert translator.online

    translator.go_offline({"positive_numbers": [1]}, max_fails=0)
    assert not translator.online
    assert translator.cache.to_dicts() == {"positive_numbers": {"hex": ["0x1"], "id": [1], "positive": [True]}}


@pytest.mark.parametrize("names", [None, "staff"])
@pytest.mark.parametrize("method", ["fetch", "go_offline"])
def test_fmt_without_translatable(method, names):
    data = {"staff": {"id": [1], "name": ["Ada"], "team": ["sales"]}}
    translator: RealTranslator[str, str, int] = RealTranslator(MemoryFetcher(data, return_all=False), fmt="{id}:{name}")

    tmap = getattr(translator, method)(names=names, fmt="{name} ({team})")

    if method == "go_offline":
        tmap = translator.cache
    assert tmap.to_dicts()["staff"]["team"] == ["sales"]


def test_fetcher_property_raises_when_offline(translator):
    offline = translator.copy().go_offline()

    with pytest.raises(ConnectionStatusError, match=r"Cannot fetch new translations\.") as exc_info:
        _ = offline.fetcher

    assert exc_info.value.__notes__ == ["Hint: Use the Translator.cache-property to access the data."]


def test_cache_property_raises_without_cache(translator):
    fresh = translator.copy()

    with pytest.raises(
        RuntimeError, match=r"No cache available\. Use `Translator\.go_offline` to cache translations\."
    ):
        _ = fresh.cache


def test_go_offline_when_already_offline_raises(translator):
    offline = translator.copy().go_offline()
    assert not offline.online

    with pytest.raises(ConnectionStatusError, match=r"already offline"):
        offline.go_offline()


def test_placeholders_property_uses_cache_when_offline(hex_fetcher):
    t = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]").go_offline()
    assert t.placeholders == {
        "positive_numbers": ["id", "hex", "positive"],
        "negative_numbers": ["id", "hex", "positive"],
    }


def test_map_scores(translator):
    actual = translator.map_scores({"p": 0, "positive_numbers": 1, "foo": 0}).to_pandas().to_numpy().tolist()
    inf = float("inf")
    assert actual == [[inf, -inf], [inf, -inf], [0.0, 0.0]]


@pytest.mark.parametrize("method", ["map", "map_scores"])
def test_map_accepts_name_to_source(translator, method):
    # Iterable[NameType] admits a dict too, so mypy cannot tell if the explicit mapping falls out of the signature.
    annotation = inspect.signature(getattr(RealTranslator, method)).parameters["names"].annotation
    assert annotation == inspect.signature(RealTranslator.translate).parameters["names"].annotation

    result = getattr(translator, method)({"x": 0, "y": 1}, names={"x": "positive_numbers"})
    if method == "map":
        assert result == {"x": "positive_numbers"}
    else:
        assert result.to_pandas().loc["x", "positive_numbers"] == float("inf")


@pytest.mark.parametrize("method", ["translate", "map", "go_offline"])
def test_names_accepts_any_mapping(translator, method):
    names = MappingProxyType({"x": "positive_numbers"})  # Iterable too: must not be read as a list of names.
    data = {"x": [1], "y": [1]}
    if method == "translate":
        assert translator.translate(data, names=names) == {"x": [translator.translate(1, "positive_numbers")], "y": [1]}
    elif method == "map":
        assert translator.map(data, names=names) == {"x": "positive_numbers"}
    else:
        assert translator.copy().go_offline(data, names=names).sources == ["positive_numbers"]


def test_not_cloneable_fetcher_raises_on_deepcopy():
    from copy import deepcopy

    with pytest.raises(TypeError, match="pickle 'module'"):
        deepcopy(NotCloneableFetcher())


def test_fetcher_not_cloneable():
    translator = UnitTestTranslator(fetcher=NotCloneableFetcher())
    fetcher_id = id(translator.fetcher)

    with pytest.warns(TranslationWarning, match="reuse"):
        copy = translator.copy()

    assert type(translator) is UnitTestTranslator
    assert id(copy) != id(translator)
    assert id(copy.fetcher) == fetcher_id


def test_fetcher_not_cloneable_multi_fetcher():
    """The failure must reach the warning above; MultiFetcher used to share the child and log instead."""
    translator = UnitTestTranslator(fetcher=MultiFetcher(NotCloneableFetcher()))

    with pytest.warns(TranslationWarning, match="Cannot clone rank-0 fetcher NotCloneableFetcher"):
        copy = translator.copy()

    assert copy.fetcher is translator.fetcher


def test_fetcher_not_cloneable_copy_mode_raises():
    """Unlike 'auto', 'copy' must not fall back to reusing the original on a failed deepcopy."""
    translator = UnitTestTranslator(fetcher=NotCloneableFetcher())

    with pytest.raises(TypeError, match="pickle 'module'") as exc_info:
        translator.copy(fetcher="copy")

    assert exc_info.value.__notes__ == [
        "Hint: Could not clone tests.conftest.NotCloneableFetcher. Use UnitTestTranslator.copy(fetcher='keep') to reuse it."
    ]


def test_fetcher_not_cloneable_keep_mode_does_not_warn():
    translator = UnitTestTranslator(fetcher=NotCloneableFetcher())

    with warnings.catch_warnings():
        warnings.simplefilter("error", TranslationWarning)
        copy = translator.copy(fetcher="keep")

    assert copy.fetcher is translator.fetcher


def test_translation_map_raises():
    translator: RealTranslator[str, str, int] = RealTranslator(
        {"bits": {"id": [1, 2], "name": ["one", "two"]}}, transformers={"bits": BitmaskTransformer()}
    )

    with pytest.raises(TypeError, match="from a TranslationMap") as exc_info:
        RealTranslator(translator.cache)

    assert exc_info.value.__notes__ == [
        "Hint: Use Translator(translation_map.to_dicts(), ...) instead.",
        "Hint: The map has transformers for sources ['bits']; pass `transformers` too.",
    ]

    with pytest.raises(TypeError, match="from a TranslationMap") as exc_info:
        RealTranslator(RealTranslator[str, str, int]({"a": {1: "one"}}).cache)

    assert len(exc_info.value.__notes__) == 1


def test_inline_data_from_any_mapping():
    translator: RealTranslator[str, str, int] = RealTranslator(MappingProxyType({"a": MappingProxyType({1: "one"})}))
    assert translator.translate({"a": 1}) == {"a": "1:one"}


def test_bad_fetcher_copy_mode(translator):
    with pytest.raises(TypeError, match=r"FetcherCopyMode\['keep', 'copy', 'auto'\]"):
        translator.copy(fetcher="clone")


def test_empty(translator):
    actual = translator.translate({"p": [], "n": [-1]}, max_fails=1.0)
    assert actual == {"p": [], "n": ["-1:-0x1, positive=False"]}
    assert translator.translated_names() == {"n": "negative_numbers", "p": "positive_numbers"}


def test_simple_fetcher_dict():
    canonical_form_data = {"people": {"id": [1999, 1991], "name": ["Sofia", "Richard"]}}

    simple: RealTranslator[str, str, int] = RealTranslator({"people": {1999: "Sofia", 1991: "Richard"}})
    assert simple.cache.to_dicts() == canonical_form_data

    canonical: RealTranslator[str, str, int] = RealTranslator(canonical_form_data)
    assert canonical.cache.to_dicts() == canonical_form_data

    assert simple.translate([1999, 1991], names="people") == canonical.translate([1999, 1991], names="people")


@pytest.mark.parametrize("nan_value", [None, float("nan"), np.nan], ids=["None", "float_nan", "numpy_nan"])
@pytest.mark.parametrize("object_value", ["string", UUID(int=0)], ids=lambda s: type(s).__name__)
def test_nan_with_objects(nan_value, object_value):
    translator = UnitTestTranslator()

    actual = translator.translate([nan_value, object_value], names="source")
    assert actual == [f"{nan_value}:name-of-{nan_value}", f"{object_value}:name-of-{object_value}"]


def test_numpy_bool_ids_in_log_records():
    translator: RealTranslator[str, str, bool] = RealTranslator({"flags": {False: "no"}})
    array: Any = np.array([False, True])  # The overloads do not cover ndarray.

    with pytest.raises(TooManyFailedTranslationsError):  # The record's sample_ids must still be JSON serializable.
        translator.translate(array, names="flags", max_fails=0)


def test_both_wanted_and_actual_placeholder_present_in_format(imdb_translator):
    actual = imdb_translator.translate(1, "name_basics", fmt="{id}:{nconst}:{name}")
    assert actual == "1:1:Fred Astaire"


class TestIoKwargs:
    @pytest.fixture
    def series(self) -> pd.Series:
        return pd.Index([-1, 1]).to_series(name="positive_numbers")

    def test_none(self, series, translator):
        actual = translator.translate(series, fmt="{hex}", io_kwargs=None).to_dict()
        assert actual == {-1: "<Failed: id=-1>", 1: "0x1"}

    def test_io_kwargs(self, series, translator):
        actual = translator.translate(series, fmt="{hex}", io_kwargs={"missing_as_nan": True}).to_dict()
        assert actual == {-1: None if int(pd.__version__.split(".")[0]) < 3 else np.nan, 1: "0x1"}  # pandas 2: None.

    def test_bad_io_kwargs(self, series, translator):
        with pytest.raises(TypeError) as exc_info:
            translator.translate(series, fmt="{hex}", io_kwargs={"missig_as_nan": True})
        assert "Hint: Set ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS=true" in "\n".join(exc_info.value.__notes__)

    def test_bad_io_kwargs_suppressed(self, series, translator, caplog, monkeypatch):
        monkeypatch.setenv("ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS", "true")
        caplog.set_level(logging.WARNING, logger="id_translation.dio")

        actual = translator.translate(series, fmt="{hex}", io_kwargs={"missig_as_nan": True}).to_dict()
        assert actual == {-1: "<Failed: id=-1>", 1: "0x1"}

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.msg == "Ignoring io_kwargs={'missig_as_nan': True} since PandasIO(**io_kwargs) raises TypeError."
        assert record.io_kwargs == ["missig_as_nan"]
        assert record.io_class == "id_translation.dio.integration.pandas.PandasIO"

    def test_without_translatable(self, translator):
        with pytest.raises(ValueError, match="io_kwargs requires a translatable"):
            translator.fetch(io_kwargs={"missing_as_nan": True})


@pytest.mark.parametrize("method", ["fetch", "go_offline"])
def test_max_fails_without_translatable(translator, method):
    with pytest.raises(ValueError, match="max_fails requires a translatable"):
        getattr(translator.copy(), method)(max_fails=0.5)


@pytest.mark.parametrize("method", ["fetch", "go_offline"])
def test_override_function_with_translatable(translator, method):
    translator = translator.copy()
    override_function = Mock(return_value="positive_numbers")

    func = getattr(translator, method)
    func({"whatever": [1]}, override_function=override_function)

    override_function.assert_called()


@pytest.mark.parametrize("multi", [False, True])
def test_online_placeholders_are_read_only(multi):
    fetcher: MemoryFetcher[str, int] = MemoryFetcher({"people": {"id": [1], "name": ["Ada"]}})
    translator: RealTranslator[str, str, int] = RealTranslator(MultiFetcher(fetcher) if multi else fetcher)

    with pytest.raises(TypeError):
        translator.placeholders["people"] = []  # type: ignore[index]
    with pytest.raises(TypeError):
        del translator.placeholders["people"]  # type: ignore[attr-defined]
    assert translator.translate(1, names="people") == "1:Ada", "discovery results must be intact"


def test_extract_names_does_not_discover():
    class DownFetcher(MemoryFetcher[str, int]):
        def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
            raise ConnectionError("down")

    translator: RealTranslator[str, str, int] = RealTranslator(DownFetcher({}))
    assert translator.extract_names({"a": [1]}) == ["a"]  # Names need only the IO: no discovery, so no raise.


@pytest.mark.parametrize(
    "data",
    [
        {"people": []},
        pd.DataFrame({"people": [np.nan]}),
        pd.Series([], dtype=float, name="people"),
        pd.Series([np.nan], name="people"),
    ],
    ids=["empty", "all-null", "empty-series", "all-null-series"],
)
def test_mapped_names_without_ids_return_a_copy(data):
    translator: RealTranslator[str, str, int] = RealTranslator(MemoryFetcher({"people": {"id": [1], "name": ["Ada"]}}))

    actual = translator.translate(data, copy=True)
    assert actual is not data, "a translated copy, as offline; only an abort returns the input itself"
    assert translator.translated_names() == {"people": "people"}


@pytest.mark.parametrize("dropped", [{"people"}, {"people", "pets"}])
def test_fetcher_dropping_a_requested_source_raises(dropped):
    from id_translation.fetching.exceptions import ImplementationError

    class Dropping(MemoryFetcher[str, int]):
        def fetch(self, ids_to_fetch, *args, **kwargs):
            return {k: v for k, v in super().fetch(ids_to_fetch, *args, **kwargs).items() if k not in dropped}

    data = {"people": {"id": [1], "name": ["Ada"]}, "pets": {"id": [1], "name": ["Rex"]}}
    translator: RealTranslator[str, str, int] = RealTranslator(Dropping(data))
    with pytest.raises(ImplementationError, match=r"Dropping\.fetch\(\) returned no translations"):
        translator.translate({"people": [1], "pets": [1]})
