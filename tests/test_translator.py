import logging
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Any

import numpy as np
import pandas as pd
import pytest
from id_translation import Translator as RealTranslator
from id_translation.dio.exceptions import NotInplaceTranslatableError, UntranslatableTypeError
from id_translation.exceptions import MissingNamesError, TooManyFailedTranslationsError, TranslationDisabledWarning
from id_translation.fetching.exceptions import UnknownSourceError
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import MappingError, MappingWarning, UserMappingError
from id_translation.utils import _config_utils

from .conftest import ROOT

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


@dataclass
class ConfigMetadataForTest(_config_utils.ConfigMetadata):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def __post_init__(self) -> None:
        assert self.clazz in ("id_translation._translator.Translator", "tests.test_translator.Translator")


# __post_init__ doesn't play nice with monkey patching
_config_utils.ConfigMetadata = ConfigMetadataForTest  # type: ignore


@pytest.mark.parametrize("with_id, with_override, store", combinations_with_replacement([False, True], 3))
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

    ans = t.translate(  # type: ignore[call-overload]
        data,
        names=names,
        override_function=override_function if with_override else None,
    )
    assert ans is not None
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


@pytest.mark.parametrize("copy", [False, True])
def test_offline(hex_fetcher, copy):
    translator = UnitTestTranslator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]").go_offline()
    if copy:
        translator = translator.copy()
    _translate(translator)


@pytest.mark.parametrize("copy", [False, True])
def test_online(translator, copy):
    _translate(translator.copy() if copy else translator)


def test_mapping_error(translator):
    with pytest.raises(MappingError):
        translator.map(0, names="unknown")


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
        ((1, 2), NotInplaceTranslatableError, {"inplace": True, "names": "positive_numbers"}),
    ],
)
def test_bad_translatable(translator, data, clazz, kwargs):
    with pytest.raises(clazz):
        translator.translate(data, **kwargs)


def test_from_config():
    UnitTestTranslator.from_config(ROOT.joinpath("config.toml"))


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


def test_store_with_explicit_values(hex_fetcher):
    data = {
        "positive_numbers": list(range(0, 5)),
        "negative_numbers": list(range(-5, -1)),
    }
    translator = UnitTestTranslator(
        hex_fetcher, fmt="{hex}", default_fmt="{id} not known", mapper=Mapper(unmapped_values_action="ignore")
    )

    with pytest.raises(MappingError) as e, pytest.warns(UserWarning) as w:
        translator.go_offline(data, ignore_names=data)
        assert "No names left" in str(w)
        assert "not store" in str(e)

    translator.go_offline(data)
    expected_num_fetches = hex_fetcher.num_fetches
    assert sorted(translator._cached_tmap.sources) == sorted(data)
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


def test_mapping_nothing_to_translate(translator):
    with pytest.warns(MappingWarning) as w:
        translator.map({"strange-name": [1, 2, 3]})
    assert len(w) == 1
    assert "aborted; none of the derived names" in str(w[0])
    assert "['strange-name']" in str(w[0])


def test_all_name_ignored(translator):
    with pytest.warns(MappingWarning, match="No names left") as w:
        translator.translate(pd.Series(name="name"), ignore_names="name")
    assert len(w) == 1

    mapping_warning = str(w[0].message)
    assert "derived names=['name']" in mapping_warning
    assert "ignore_names=['name']" in mapping_warning


def test_explicit_name_ignored(translator):
    with pytest.raises(ValueError) as e:
        translator.map(0, names=[], ignore_names="")
    assert "Required names" in str(e)


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
    assert t.translate(1, names="people") == "1:right-value"

    t = t.copy(default_fmt="{left}, {right}")
    assert t.translate(1, names="people") == "left-value, right-value"

    t = t.copy(default_fmt_placeholders=dict(default={"left": "LEFT", "right": "RIGHT"}))
    assert t.translate(1, names="people") == "LEFT, RIGHT"


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


def test_no_names(translator):
    with pytest.raises(MissingNamesError):
        translator.translate(pd.Series(range(3)))


def test_untranslated_fraction_single_name():
    translator = UnitTestTranslator({"source": {"id": [0], "name": ["zero"]}}, default_fmt="{id} not translated")

    translator.translate([0, 1], names="source", maximal_untranslated_fraction=0.5)

    with pytest.raises(TooManyFailedTranslationsError, match="translate 1/3"):
        translator.translate([0, 0, 1], names="source", maximal_untranslated_fraction=0.0)

    with pytest.raises(TooManyFailedTranslationsError, match="translate 1/1"):
        translator.translate(1, names="source", maximal_untranslated_fraction=0.0)


def test_untranslated_fraction_multiple_names(translator, hex_fetcher):
    translator = UnitTestTranslator(hex_fetcher, enable_uuid_heuristics=True, fmt="{id}:{hex}")
    translatable = {"negative_numbers": [1, 1], "positive_numbers": [0, 1, 2]}

    with pytest.raises(TooManyFailedTranslationsError, match="translate 2/2"):
        translator.translate(translatable, maximal_untranslated_fraction=0.0)


def test_untranslated_reporting(caplog):
    translator = UnitTestTranslator({"source": {"id": [0, 1, 2, 3, 4]}}, fmt="{id}")
    translator.translate(
        {"none": [-1, -100], "partial": [-1, 1, 2], "all": [0, 1]},
        override_function=lambda *_: "source",
        inplace=True,
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
    fmt = "{id}:{hex}[, positive={positive}]"
    t = UnitTestTranslator(hex_fetcher, fmt=fmt).go_offline()

    translated = {
        "positive_numbers": [
            "<Failed: id=-1>",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }
    assert translated == t.translate({"positive_numbers": [-1, 0, 1]}, inplace=False)

    actual = t.translate(translated, reverse=True)  # type: ignore[arg-type]
    assert {"positive_numbers": [None, 0, 1]} == actual, "Original format"

    translated = {"positive_numbers": ["-0x1", "0x0", "0x1"]}
    tc = t.copy(fmt="{hex}")
    actual = tc.translate(translated, reverse=True)  # type: ignore[arg-type]
    assert {"positive_numbers": [None, 0, 1]} == actual, "New format"


def test_simple_function_overrides(translator):
    actual = translator.translate(1, names="whatever", override_function=lambda *_: "positive_numbers")
    assert actual == "1:0x1, positive=True"

    actual = translator.translate(1, names="positive_numbers", override_function=lambda *_: None)
    assert actual == "1:0x1, positive=True"

    with pytest.raises(UserMappingError):
        translator.translate(1, names="whatever", override_function=lambda *_: "bad")


def test_override_fetcher(translator):
    old_fetcher = translator.fetcher
    assert translator.translate(1, names="positive_numbers") == "1:0x1, positive=True"
    expected = old_fetcher.num_fetches

    translator = translator.copy(fetcher={"positive_numbers": {"id": [1], "hex": ["0x1"], "positive": [True]}})
    assert translator.translate(1, names="positive_numbers") == "1:0x1, positive=True"
    assert expected == old_fetcher.num_fetches


def test_float_ids(translator):
    from id_translation._tasks import TranslationTask
    from id_translation.offline import Format

    translatable = {"positive_numbers": [0.0, 0, 1, 0.1, float("nan"), np.nan, 3, np.nan]}
    task = TranslationTask(translator, translatable, fmt=Format(""))
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
    assert isinstance(translator, UnitTestTranslator)
    now = translator.now
    assert translator.translate(*args) == expected

    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path)
    assert isinstance(translator, UnitTestTranslator)
    assert translator.now == now
    assert translator.translate(*args) == expected

    translator = UnitTestTranslator.load_persistent_instance(tmp_path, config_path, max_age="-1d")
    assert isinstance(translator, UnitTestTranslator)
    assert translator.now > now
    assert translator.translate(*args) == expected

    real_translator: RealTranslator[str, str, int] = RealTranslator.load_persistent_instance(tmp_path, config_path)
    assert isinstance(real_translator, RealTranslator)
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


class TestDictNames:
    translate: Any

    @classmethod
    def setup_class(cls):
        tmp = UnitTestTranslator.from_config(ROOT.joinpath("config.imdb.toml"))
        translator = tmp.copy(
            fmt="{id}:{name}",
            mapper=tmp.mapper.copy(unknown_user_override_action="ignore"),
        )
        assert "name_basics" in translator.sources
        cls.translate = translator.translate

    def test_override_info_in_logs(self, caplog):
        expected = {"nconst": ["1:Fred Astaire", "15:James Dean"]}
        assert self.translate({"nconst": [1, 15]}, names={"nconst": "name_basics"}) == expected
        record = next(record for record in caplog.messages if "names={'nconst': 'name_basics'}" in record)
        assert "override_function=UserArgument" in record

    def test_dict_with_override_function(self):
        with pytest.raises(ValueError, match="Dict-type names="):
            assert self.translate("", names={}, override_function=crash)

    def test_mapping_to_unknown_source(self, caplog):
        with pytest.raises(UnknownSourceError, match="'unknown-source"):
            self.translate({"nconst": [1, 15]}, names={"nconst": "unknown-source"})
        record = next(record for record in caplog.messages if "names={'nconst': 'unknown-source'}" in record)
        assert "override_function=UserArgument" in record

    def test_forbidden_value(self):
        with pytest.raises(ValueError, match="Bad name-to-source mapping: 'nconst' -> None"):
            self.translate("", names={"nconst": None})

    def test_no_names(self):
        with pytest.warns(MappingWarning, match="aborted.*override_function=UserArgument"):
            assert self.translate({"nconst": [1, 15]}, names={}) == {"nconst": [1, 15]}


@pytest.mark.parametrize("with_source", [False, True])
class TestTranslatedNames:
    translator = UnitTestTranslator()

    def test_unused(self, with_source):
        with pytest.raises(ValueError, match="No names have been translated using this Translator."):
            self.translator.translated_names(with_source)

    def test_multiple(self, with_source):
        self.translator.translate([1, 2, 3], names=list("abc"))

        actual = self.translator.translated_names(with_source)
        if with_source:
            assert isinstance(actual, dict)
            assert actual == {char: char for char in "abc"}
        else:
            assert isinstance(actual, list)
            assert sorted(actual) == list("abc")

    def test_single(self, with_source):
        self.translator.translate([1, 2, 3], names="a")
        expected = {char: char for char in "a"}
        assert self.translator.translated_names(with_source) == expected if with_source else list(expected)

    @staticmethod
    def type_check():
        from typing import assert_type

        without_source = UnitTestTranslator().translated_names()
        assert_type(without_source, list[str])
        without_source = UnitTestTranslator().translated_names(False)
        assert_type(without_source, list[str])

        with_source = UnitTestTranslator().translated_names(True)
        assert_type(with_source, dict[str, str])


def test_fetch(translator):
    from id_translation.dio import resolve_io

    translatable = {"numbers": [-1, 0, 1]}
    name_to_source = {"numbers": "positive_numbers"}
    tmap = translator.fetch(translatable, names=name_to_source)
    assert translator.online

    actual = resolve_io(translatable).insert(translatable, list(translatable), tmap, True)
    assert actual == translator.translate(translatable, names=name_to_source)


def test_map_scores(translator):
    actual = translator.map_scores({"p": 0, "positive_numbers": 1, "foo": 0}).to_numpy().tolist()
    inf = float("inf")
    assert actual == [[inf, -inf], [inf, -inf], [0.0, 0.0]]


def test_fetcher_clone_type_error():
    from id_translation.fetching import SqlFetcher

    translator = UnitTestTranslator(fetcher=SqlFetcher("sqlite:///"))
    fetcher_id = id(translator.fetcher)

    with pytest.warns(UserWarning, match="reuse"):
        copy = translator.copy()

    assert isinstance(translator, UnitTestTranslator)
    assert id(copy) != id(translator)
    assert id(copy.fetcher) == fetcher_id


def test_empty(translator):
    actual = translator.translate({"p": [], "n": [-1]}, maximal_untranslated_fraction=1.0)
    assert actual == {"p": [], "n": ["-1:-0x1, positive=False"]}
    assert translator.translated_names(with_source=True) == {"n": "negative_numbers", "p": "positive_numbers"}


def test_simple_fetcher_dict():
    canonical_form_data = {"people": {"id": [1999, 1991], "name": ["Sofia", "Richard"]}}

    simple: RealTranslator[str, str, int] = RealTranslator({"people": {1999: "Sofia", 1991: "Richard"}})
    assert simple.cache.to_dicts() == canonical_form_data

    canonical: RealTranslator[str, str, int] = RealTranslator(canonical_form_data)
    assert canonical.cache.to_dicts() == canonical_form_data

    assert simple.translate([1999, 1991], names="people") == canonical.translate([1999, 1991], names="people")
