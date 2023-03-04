from functools import partialmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pytest
from rics.mapping import Mapper

from id_translation import Translator
from id_translation.fetching import AbstractFetcher, support
from id_translation.fetching.exceptions import UnknownIdError
from id_translation.fetching.types import FetchInstruction
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations

ROOT: Path = Path(__file__).parent

Mapper.__init__ = partialmethod(Mapper.__init__, verbose_logging=True)  # type: ignore[assignment]


class HexFetcher(AbstractFetcher[str, int]):
    def __init__(self) -> None:
        super().__init__()
        self.num_fetches = 0

    def fetch_translations(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str]:
        self.num_fetches += 1

        placeholders = support.select_placeholders(instr, ["id", "hex", "positive"])

        return PlaceholderTranslations(
            instr.source,
            tuple(placeholders),
            tuple(self._run(placeholders, instr.ids)),
        )

    @staticmethod
    def _run(placeholders: List[str], ids: Optional[Iterable[int]]) -> Iterable[Tuple[Any, ...]]:
        ids = tuple(range(-10, 10) if ids is None else ids)
        if max(ids) > 9 or min(ids) < -10:
            raise UnknownIdError()

        funcs = {
            "hex": hex,
            "id": lambda x: x,
            "positive": lambda x: x >= 0,
        }

        for idx in ids:
            yield tuple(funcs[p](idx) for p in placeholders)

    @property
    def sources(self) -> List[str]:
        return ["positive_numbers", "negative_numbers"]

    @property
    def placeholders(self) -> Dict[str, List[str]]:
        placeholders = ["id", "hex", "positive"]
        return {
            "positive_numbers": placeholders,
            "negative_numbers": placeholders,
        }


@pytest.fixture(scope="session")
def hex_fetcher() -> HexFetcher:
    return HexFetcher()


@pytest.fixture(scope="session")
def translator(hex_fetcher: HexFetcher) -> Translator[str, str, int]:
    return Translator(hex_fetcher, fmt="{id}:{hex}[, positive={positive}]")


@pytest.fixture(scope="session")
def imdb_translator() -> Translator[str, str, str]:
    return Translator.from_config(ROOT.joinpath("config.imdb.toml"))


@pytest.fixture(scope="module")
def translation_map() -> TranslationMap[str, str, str]:
    imdb_translator: Translator[str, str, str] = Translator.from_config(ROOT.joinpath("config.imdb.toml"))
    imdb_translator = imdb_translator.store(
        {"firstTitle": [], "nconst": []}  # Make sure 'firstTitle' and 'nconst' are mapped
    )
    return imdb_translator.cache
