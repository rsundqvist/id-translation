from math import inf
from typing import Unpack, assert_type
from uuid import UUID

import pytest

import id_translation.translator_typing as tt
from id_translation import Translator
from id_translation.fetching import AbstractFetcher

from .conftest import TypedTranslator, UnionDict, make_translatable
from .validate_func_annotations import validate_func_annotations


def test_map():
    params = tt.MapParams[str, bool, int | UUID](translatable=make_translatable())
    translator = TypedTranslator()

    translator.map(**params)

    def call(**kwargs: Unpack[tt.MapParams[str, bool, int | UUID]]) -> None:
        assert translator.map(**kwargs) == {"people": True, "places": False}

    with pytest.raises(TypeError):
        call()  # type: ignore[call-arg]
    call(translatable=make_translatable())


def test_map_scores():
    params = tt.MapParams[str, bool, int | UUID](translatable=make_translatable())
    translator = TypedTranslator()

    translator.map_scores(**params)

    def call(**kwargs: Unpack[tt.MapParams[str, bool, int | UUID]]) -> None:
        assert translator.map_scores(**kwargs).to_pandas().to_dict() == {
            False: {"people": -inf, "places": inf},
            True: {"people": inf, "places": -inf},
        }

    with pytest.raises(TypeError):
        call()  # type: ignore[call-arg]
    call(translatable=make_translatable())


EXPECTED_TRANSLATION_MAP_TO_DICTS = {
    False: {
        "id": [UUID("00000660-0000-0000-0000-000000000000"), UUID("000004f2-0000-0000-0000-000000000000")],
        "name": ["Göteborg", "Stockholm"],
    },
    True: {
        "id": [1999, 1991],
        "name": ["Sofia", "Richard"],
    },
}


def test_fetch():
    params = tt.FetchParams[str, bool, int | UUID](translatable=make_translatable())
    translator = TypedTranslator()

    assert translator.fetch(**params).to_dicts() == EXPECTED_TRANSLATION_MAP_TO_DICTS

    def call(**kwargs: Unpack[tt.FetchParams[str, bool, int | UUID]]) -> None:
        assert translator.fetch(**kwargs).to_dicts() == EXPECTED_TRANSLATION_MAP_TO_DICTS

    with pytest.raises(TypeError):
        call(copy=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(reverse=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(copy=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(reverse=True)  # type: ignore[call-arg]

    call(translatable=make_translatable())

    assert TypedTranslator().fetch().name_to_source == {}
    assert TypedTranslator().fetch(names={"humans": True}).name_to_source == {"humans": True}


def test_go_offline():
    params = tt.FetchParams[str, bool, int | UUID](translatable=make_translatable())
    assert TypedTranslator().go_offline(**params).cache.to_dicts() == EXPECTED_TRANSLATION_MAP_TO_DICTS

    def call(path: str | None = None, **kwargs: Unpack[tt.FetchParams[str, bool, int | UUID]]) -> None:
        translator = TypedTranslator()
        assert translator.online
        assert translator.go_offline(path=path, **kwargs).cache.to_dicts() == EXPECTED_TRANSLATION_MAP_TO_DICTS
        assert not translator.online

    with pytest.raises(TypeError):
        call(copy=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(reverse=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(copy=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(reverse=True)  # type: ignore[call-arg]

    call(translatable=make_translatable())


def test_translate():
    expected = {"people": ["1999:Sofia", "1991:Richard"], "places": ["00000660:Göteborg", "000004f2:Stockholm"]}

    params = tt.TranslateParams[str, bool, int | UUID]()
    translatable = make_translatable()

    actual = TypedTranslator().translate(translatable, copy=True, **params)
    assert actual == expected
    assert_type(actual, dict[str, list[str]])

    def call(t: UnionDict, **kwargs: Unpack[tt.TranslateParams[str, bool, int | UUID]]) -> None:
        actual = TypedTranslator().translate(t, copy=True, **kwargs)
        assert actual == expected
        assert_type(actual, dict[str, list[str]])

    with pytest.raises(TypeError):
        call(translatable, copy=True)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(translatable, copy=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        call(translatable, path="")  # type: ignore[call-arg]

    call(translatable)


def test_translate_full():
    expected = {"people": ["1999:Sofia", "1991:Richard"], "places": ["00000660:Göteborg", "000004f2:Stockholm"]}

    translatable = make_translatable()
    params = tt.AllTranslateParams[str, bool, int | UUID](translatable=translatable)

    actual = TypedTranslator().translate(**params)  # type: ignore[call-overload]  # TODO Higher-Kinded TypeVars
    assert actual == expected
    # this ignore expected - it's the downside of allowing users to "hide" the type of translatable in a dict.
    assert_type(actual, dict[str, list[str]])  # type: ignore[assert-type]

    with pytest.raises(TypeError):
        empty = tt.AllTranslateParams[str, bool, int | UUID]()  # type: ignore[typeddict-item]
        TypedTranslator().translate(**empty)  # MyPy should NOT complain on this line!

    def call(**kwargs: Unpack[tt.AllTranslateParams[str, bool, int | UUID]]) -> None:
        actual = TypedTranslator().translate(**kwargs)  # type: ignore[call-overload]  # TODO Higher-Kinded TypeVars
        assert actual == expected

        # this ignore expected - it's the downside of allowing users to "hide" the type of translatable in a dict.
        assert_type(actual, dict[str, list[str]])  # type: ignore[assert-type]

    with pytest.raises(TypeError):
        call(translatable=translatable, path="")  # type: ignore[call-arg]

    call(translatable=translatable, copy=True)
    call(translatable=translatable)


def test_copy():
    from id_translation import Translator

    translator = Translator[str, bool, int | UUID]()

    assert translator.enable_uuid_heuristics is False

    params = tt.CopyParams[str, bool, int | UUID](enable_uuid_heuristics=True)
    copy = translator.copy(**params)

    with pytest.raises(TypeError):
        translator.copy(copy=False)  # type: ignore[call-arg]

    assert copy.enable_uuid_heuristics is True
    assert translator.enable_uuid_heuristics is False


def test_docs():
    types = {
        tt.MapParams: [TypedTranslator.map_scores, TypedTranslator.map],
        tt.FetchParams: [TypedTranslator.fetch, TypedTranslator.go_offline],
        tt.AllTranslateParams: [TypedTranslator.translate],
        tt.CopyParams: [TypedTranslator.copy],
    }

    # Test docstring
    template = ":meth:`.Translator.{func.__name__}`"
    for typed_dict, functions in types.items():
        docstring = typed_dict.__doc__
        assert docstring is not None
        for func in functions:  # type: ignore[attr-defined]
            assert template.format(func=func) in docstring


@pytest.mark.parametrize(
    "func,typed_dict",
    [
        (Translator.__init__, tt.CopyParams),
        (Translator.map, tt.MapParams),
        (Translator.map_scores, tt.MapParams),
        (Translator.fetch, tt.FetchParams),
        (Translator.translate, tt.AllTranslateParams),
        (AbstractFetcher.__init__, tt.AbstractFetcherParams),
    ],
    ids=lambda v: v.__qualname__.replace(".", "-"),
)
def test_annotations(func, typed_dict):
    validate_func_annotations(func, typed_dict, fail_fast=False)
