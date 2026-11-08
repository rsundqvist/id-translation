from typing import Any

import pytest

from id_translation import Translator
from id_translation.exceptions import NoSourcesError
from id_translation.fetching import MemoryFetcher, MultiFetcher
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import MappingWarning


class DownFetcher(MemoryFetcher[str, int]):
    def _initialize_sources(self, task_id: int) -> dict[str, list[str]]:  # noqa: ARG002
        raise ConnectionError("down")


def _all_down() -> Translator[str, str, int]:
    children: list[Any] = [
        DownFetcher({"a": {"id": [1]}}, optional=True),
        DownFetcher({"b": {"id": [1]}}, optional=True),
    ]
    return Translator(MultiFetcher(*children))


def test_every_optional_fetcher_discarded_raises():
    translator = _all_down()

    with pytest.warns(match="No fetchers"), pytest.raises(NoSourcesError, match="No sources found by") as exc_info:
        translator.initialize_sources()
    assert [n for n in exc_info.value.__notes__ if "Optional fetchers discarded" in n]
    assert [n for n in exc_info.value.__notes__ if "require_sources=False" in n]


def test_require_sources_false_covers_implicit_calls():
    translator = _all_down()

    with pytest.warns(match="No fetchers"):
        translator.initialize_sources(require_sources=False)
    assert translator.sources == []
    translator.initialize_sources()  # Discovery has run; nothing left to check.


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fetcher": "keep"},
        {"fetcher": "copy"},
        {"fetcher": "keep", "transformers": {}},
    ],
)
def test_require_sources_false_survives_copy(kwargs):
    translator = _all_down()
    with pytest.warns(match="No fetchers"):
        translator.initialize_sources(require_sources=False)

    translator.copy(**kwargs).initialize_sources()  # The copy keeps the acceptance, shared fetcher or clone.


def test_require_sources_false_goes_offline_with_an_empty_snapshot():
    translator: Translator[str, str, int] = Translator(MemoryFetcher({}))
    translator.initialize_sources(require_sources=False)

    translator.go_offline()
    assert not translator.online
    assert translator.cache.sources == []


def test_go_offline_with_every_source_skipped_raises_and_stays_online():
    translator: Translator[str, str, int] = Translator(
        MemoryFetcher({"a": {"id": [1], "name": ["x"]}}), mapper=Mapper(score_function_kwargs={"strict": False})
    )

    with pytest.raises(NoSourcesError, match="Nothing to take offline"):
        translator.go_offline(fmt="{id}:{nope}")
    assert translator.online
    assert translator.translate(1, names="a") == "1:x", "the fetcher must still work"


def test_go_offline_with_every_source_ignored_raises():
    translator: Translator[str, str, int] = Translator(MemoryFetcher({"a": {"id": [1], "name": ["x"]}}))

    with (
        pytest.warns(MappingWarning, match="No names left to translate"),
        pytest.raises(NoSourcesError, match="Nothing to take offline") as exc_info,
    ):
        translator.go_offline(ignore_names=lambda _: True)
    assert [n for n in exc_info.value.__notes__ if "No source was selected" in n]
    assert translator.online
