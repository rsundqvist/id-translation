import logging
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Any, List, Optional

import numpy as np
import pandas as pd
import pytest
from rics.mapping import Mapper
from rics.mapping.exceptions import MappingError, MappingWarning, UserMappingError

from id_translation import Translator as RealTranslator, _config_utils
from id_translation.dio.exceptions import NotInplaceTranslatableError, UntranslatableTypeError
from id_translation.exceptions import ConfigurationError, TooManyFailedTranslationsError
from id_translation.ttypes import IdType

from .conftest import ROOT

LOGGER = logging.getLogger("TestTranslator")


@contextmanager
def verification_context(purpose):
    LOGGER.info(f"{f' Start: {purpose} ':=^80}")
    yield
    LOGGER.info(f"{f' Stop: {purpose} ':=^80}")


class Translator(RealTranslator[str, str, IdType]):
    """Test implementation that performs additional verification."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.now = pd.Timestamp.now()

    def _map_inner(self, translatable, names, ignore_names, override_function, parent):
        if parent is None:
            with verification_context("Verify score computations"):
                """Ensure that map_scores returns correct values."""
                names_to_translate = self._resolve_names(translatable, names, ignore_names)
                mapper_scores = self.mapper.compute_scores(names_to_translate, self.sources, None, override_function)
                translator_scores = self.map_scores(translatable, names, ignore_names, override_function)
                assert mapper_scores.equals(translator_scores), "Mapper/Translator score mismatch."

        return super()._map_inner(translatable, names, ignore_names, override_function, parent)


@dataclass(frozen=True)
class ConfigMetadataForTest(_config_utils.ConfigMetadata):
    def __post_init__(self) -> None:
        assert self.path.is_absolute(), f"Got non-absolute main configuration path='{self.path}'."
        for path in self.extra_fetchers:
            assert path.is_absolute(), f"Got non-absolute auxiliary fetcher configuration path='{path}'."

        assert isinstance(self.clazz, str), f"Got clazz={self.clazz}, expected string."
        assert self.clazz in ("id_translation._translator.Translator", "tests.test_translator.Translator")


# __post_init__ doesn't play nice with monkey patching
_config_utils.ConfigMetadata = ConfigMetadataForTest  # type: ignore


@pytest.mark.parametrize("with_id, with_override, store", combinations_with_replacement([False, True], 3))
def test_dummy_translation_doesnt_crash(with_id, with_override, store):
    with pytest.warns(UserWarning):
        t = Translator(fmt="{id}:{first}:{second}:{third}")

    names = list(map("placeholder{}".format, range(3)))
    data = np.random.randint(0, 100, (3, 10))

    def override_function(name: str, *_: Any) -> Optional[str]:
        return names[0] if name == "id" else None

    if with_id:
        names[0] = "id"
    if store:
        t.store(data, names=names)

    ans = t.translate(data, names=names, override_function=override_function if with_override else None)
    assert ans is not None
    assert ans.shape == (3, 10)


def test_translate_without_id(hex_fetcher):
    without_id = "{hex}, positive={positive}"
    ans = Translator(hex_fetcher, fmt=without_id).translate({"positive_numbers": list(range(-1, 2))})
    assert ans == {
        "positive_numbers": [
            "-0x1, positive=False",
            "0x0, positive=True",
            "0x1, positive=True",
        ]
    }


@pytest.mark.parametrize("copy", [False, True])
def test_can_pickle(translator, copy):
    from rics.utility.misc import serializable

    assert serializable(translator.copy() if copy else translator)


@pytest.mark.parametrize("copy", [False, True])
def test_offline(hex_fetcher, copy):
    translator = Translator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]").store()
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
    ans = translator.translate({"positive_numbers": list(range(-3, 3))})
    assert ans == {
        "positive_numbers": [
            "-3:-0x3, positive=False",
            "-2:-0x2, positive=False",
            "-1:-0x1, positive=False",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
            "2:0x2, positive=True",
        ]
    }


@pytest.mark.parametrize(
    "data,clazz,kwargs",
    [
        (object(), UntranslatableTypeError, {"names": 1}),
        ((1, 2), AttributeError, {}),
        ((1, 2), NotInplaceTranslatableError, {"inplace": True, "names": "positive_numbers"}),
    ],
)
def test_bad_translatable(translator, data, clazz, kwargs):
    with pytest.raises(clazz):
        translator.translate(data, **kwargs)


def test_from_config():
    Translator.from_config(ROOT.joinpath("config.toml"))


def test_missing_config():
    with pytest.raises(ConfigurationError):
        Translator.from_config(ROOT.joinpath("bad-config.toml"))


def test_store_and_restore(hex_fetcher, tmp_path):
    translator: Translator[int] = Translator(hex_fetcher, fmt="{id}:{hex}")

    data = {
        "positive_numbers": list(range(0, 5)),
        "negative_numbers": list(range(-5, -1)),
    }
    translated_data = translator.translate(data)

    path = tmp_path.joinpath("translator.pkl")
    translator.store(path=path)
    restored = Translator.restore(path=path)

    translated_by_restored = restored.translate(data)
    assert translated_by_restored == translated_data


def test_store_with_explicit_values(hex_fetcher):
    data = {
        "positive_numbers": list(range(0, 5)),
        "negative_numbers": list(range(-5, -1)),
    }
    translator = Translator(
        hex_fetcher, fmt="{hex}", default_fmt="{id} not known", mapper=Mapper(unmapped_values_action="ignore")
    )

    with pytest.raises(MappingError) as e, pytest.warns(UserWarning) as w:
        translator.store(data, ignore_names=data, delete_fetcher=False)
        assert "No names left" in str(w)
        assert "not store" in str(e)

    translator.store(data)
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


@pytest.mark.parametrize(
    "reject_predicate, expected",
    [
        (lambda s: not s.endswith("id"), ["ends_with_id", "also_ends_with_id"]),
        (lambda s: "numeric" in s, ["ends_with_id", "also_ends_with_id"]),
        (None, ["ends_with_id", "is_numeric", "also_ends_with_id", "also_numeric"]),
    ],
)
def test_reject_predicates(translator, reject_predicate, expected):
    data = {
        "ends_with_id": [1, 2, 3],
        "is_numeric": [3.5, 0.8, 1.1],
        "also_ends_with_id": [1, 2, 3],
        "also_numeric": [3.5, 0.8, 1.1],
    }
    names_to_translate = translator._resolve_names(data, names=data, ignored_names=reject_predicate)

    assert names_to_translate == expected


def test_mapping_nothing_to_translate(translator):
    with pytest.warns(MappingWarning) as w:
        translator.map({"strange-name": [1, 2, 3]})
    assert len(w) == 1
    assert "aborted; none of the derived names" in str(w[0])
    assert "['strange-name']" in str(w[0])


def test_all_name_ignored(translator):
    with pytest.warns(MappingWarning) as w:
        translator.map({"name": []}, ignore_names="name")
    assert len(w) == 2
    assert "No names left" in str(w[0])
    assert "aborted; none of the derived names" in str(w[1])
    assert "['name']" in str(w[1])
    assert "ignore_names='name'" in str(w[1])


def test_explicit_name_ignored(translator):
    with pytest.raises(MappingError) as e:
        translator.map(0, names=["ignored_name", "positive_numbers"], ignore_names="ignored_name")
    assert "Required names" in str(e)


def test_complex_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    default_fmt = "{id} - {hex} - {positive}"
    default_fmt_placeholders = {"default": {"positive": "POSITIVE/NEGATIVE", "hex": "HEX"}}
    t = Translator(
        hex_fetcher, fmt=fmt, default_fmt=default_fmt, default_fmt_placeholders=default_fmt_placeholders
    ).store()

    in_range = t.translate({"positive_numbers": list(range(-1, 2))})
    assert in_range == {
        "positive_numbers": [
            "-1:-0x1, positive=False",
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
    t = Translator(hex_fetcher, fmt=fmt, default_fmt=default_fmt).store()

    in_range = t.translate({"positive_numbers": list(range(-1, 2))})
    assert in_range == {
        "positive_numbers": [
            "-1:-0x1, positive=False",
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
    t = Translator(
        {"people": {"id": [1999], "name": ["Sofia"]}},
        default_fmt="{id}:{right}",
        default_fmt_placeholders=dict(default={"left": "left-value", "right": "right-value"}),
    )
    assert "1:right-value" == t.translate(1, names="people")

    t = t.copy(default_fmt="{left}, {right}")  # type: ignore[assignment]
    assert "left-value, right-value" == t.translate(1, names="people")

    t = t.copy(default_fmt_placeholders=dict(default={"left": "LEFT", "right": "RIGHT"}))  # type: ignore[assignment]
    assert "LEFT, RIGHT" == t.translate(1, names="people")


def test_plain_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    default_fmt = "UNKNOWN"
    t = Translator(hex_fetcher, fmt=fmt, default_fmt=default_fmt).store()

    in_range = t.translate({"positive_numbers": list(range(-1, 2))})
    assert in_range == {
        "positive_numbers": [
            "-1:-0x1, positive=False",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {"positive_numbers": ["UNKNOWN", "UNKNOWN"]}


def test_no_default(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    t = Translator(hex_fetcher, fmt=fmt).store()
    in_range = t.translate({"positive_numbers": list(range(-1, 2))})
    assert in_range == {
        "positive_numbers": [
            "-1:-0x1, positive=False",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }

    out_of_range = t.translate({"positive_numbers": [-5000, 10000]})
    assert out_of_range == {
        "positive_numbers": [None, None],
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
    with pytest.raises(AttributeError):
        translator.translate(pd.Series(range(3)))


def test_untranslated_fraction():
    translator = Translator({"source": {"id": [0], "name": ["zero"]}}, default_fmt="{id} not translated")

    translator.translate([0, 1], names="source", maximal_untranslated_fraction=0.5)

    with pytest.raises(TooManyFailedTranslationsError):
        translator.translate([0, 0, 1], names="source", maximal_untranslated_fraction=0.0)

    with pytest.raises(TooManyFailedTranslationsError):
        translator.translate(1, names="source", maximal_untranslated_fraction=0.0)


def test_reverse(hex_fetcher):
    fmt = "{id}:{hex}[, positive={positive}]"
    t = Translator(hex_fetcher, fmt=fmt).store()

    expected = {"positive_numbers": list(range(-1, 2))}
    translated = {
        "positive_numbers": [
            "-1:-0x1, positive=False",
            "0:0x0, positive=True",
            "1:0x1, positive=True",
        ]
    }
    assert translated == t.translate(expected, inplace=False)

    actual = t.translate(translated, reverse=True)
    assert expected == actual, "Original format"

    translated = {"positive_numbers": ["-0x1", "0x0", "0x1"]}
    tc = t.copy(fmt="{hex}")
    actual = tc.translate(translated, reverse=True)
    assert expected == actual, "New format"


def test_simple_function_overrides(translator):
    actual = translator.translate(1, names="whatever", override_function=lambda *args: "positive_numbers")
    assert actual == "1:0x1, positive=True"

    actual = translator.translate(1, names="positive_numbers", override_function=lambda *args: None)
    assert actual == "1:0x1, positive=True"

    with pytest.raises(UserMappingError):
        translator.translate(1, names="whatever", override_function=lambda *args: "bad")


def test_complex_function_overrides(translator):
    with pytest.raises(NotImplementedError) as e:
        translator.translate(1, names="whatever", override_function=lambda *args: {})

    assert "https://github.com/rsundqvist/rics/issues/64" in str(e.value)


def test_override_fetcher(translator):
    old_fetcher = translator.fetcher
    assert "1:0x1, positive=True" == translator.translate(1, names="positive_numbers")
    expected = old_fetcher.num_fetches

    translator = translator.copy(fetcher={"positive_numbers": {"id": [1], "hex": ["0x1"], "positive": [True]}})
    assert "1:0x1, positive=True" == translator.translate(1, names="positive_numbers")
    assert expected == old_fetcher.num_fetches


def test_translate_attribute():
    with pytest.warns(UserWarning):
        translate = Translator().translate
    df = pd.DataFrame(range(3))
    df.index.name = "index-name"

    translate(df, attribute="index")

    assert df.index.tolist() == translate(list(range(3)), names=df.index.name)


def test_inherited_name(translator):
    assert translator._allow_name_inheritance
    s = pd.Series([1, 1, 2, 2, 2, 3, 4], name="positive_numbers")

    translator.translate(s, attribute="index")

    s.name = None
    with pytest.raises(AttributeError):
        translator.translate(s, attribute="index")


def test_float_ids(translator):
    from rics.mapping import DirectionalMapping

    from id_translation.dio import resolve_io

    translatable = [0.0, 0, 1, 0.1, float("nan"), np.nan, 3, np.nan]
    ids_to_fetch = translator._get_ids_to_fetch(
        DirectionalMapping(left_to_right={"whatever": ("whatever",)}),
        translatable,
        resolve_io(translatable),
    )
    assert len(ids_to_fetch) == 1
    assert ids_to_fetch[0].ids == {0, 1, 3}


def test_load_persistent_instance(tmp_path):
    path = ROOT.joinpath("dvdrental/translation.toml")  # Uses an in-memory fetcher.
    fetchers = [ROOT.joinpath("config.imdb.toml")]

    expected = [None, "1:Action", "2:Animation"]
    translatable: List[int] = [0, 1, 2]
    args = (translatable, "category_id")

    with pytest.warns(UserWarning, match="EXPERIMENTAL"):
        translator = Translator.load_persistent_instance(path, fetchers, tmp_path, clazz=Translator)
        now = translator.now  # type: ignore[attr-defined]
        assert translator.translate(*args) == expected

        translator = Translator.load_persistent_instance(path, fetchers, tmp_path, clazz=Translator)
        assert translator.now == now  # type: ignore[attr-defined]
        assert translator.translate(*args) == expected

        translator = Translator.load_persistent_instance(path, fetchers, tmp_path, clazz=Translator, max_age="-1d")
        assert translator.now > now  # type: ignore[attr-defined]
        assert translator.translate(*args) == expected

        real_translator: RealTranslator[str, str, int] = RealTranslator.load_persistent_instance(
            path, fetchers, tmp_path
        )
        assert real_translator.translate(*args) == expected
        assert not isinstance(real_translator, Translator)
