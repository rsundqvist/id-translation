import json
import logging
from functools import partialmethod
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import UUID

import numpy as np
import pytest

from id_translation import Translator
from id_translation.fetching import AbstractFetcher
from id_translation.fetching.exceptions import UnknownIdError
from id_translation.fetching.types import FetchInstruction
from id_translation.mapping import Mapper
from id_translation.offline import TranslationMap
from id_translation.offline.types import PlaceholderTranslations

ROOT: Path = Path(__file__).parent

Mapper.__init__ = partialmethod(Mapper.__init__, verbose_logging=True)  # type: ignore[assignment]


class CheckSerializeToJson(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        d = record.__dict__.copy()
        d.pop("exc_info", None)
        json.dumps(d, cls=JsonEncoder)


class JsonEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()

        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)


logging.root.addHandler(CheckSerializeToJson())


class HexFetcher(AbstractFetcher[str, int]):
    def __init__(self) -> None:
        super().__init__()
        self.num_fetches = 0

    def fetch_translations(self, instr: FetchInstruction[str, int]) -> PlaceholderTranslations[str]:
        self.num_fetches += 1

        assert instr.source in self.sources

        known_placeholders = ["id", "hex", "positive"]
        placeholders = [p for p in instr.placeholders if p in known_placeholders]

        return PlaceholderTranslations(
            instr.source,
            tuple(placeholders),
            tuple(self._run(placeholders, instr.ids, instr.source)),
        )

    @staticmethod
    def _run(placeholders: List[str], ids: Optional[Iterable[int]], source: str) -> Iterable[Tuple[Any, ...]]:
        ids = tuple(range(-10, 10) if ids is None else ids)
        if max(ids) > 9 or min(ids) < -10:
            raise UnknownIdError()

        funcs = {
            "hex": hex,
            "id": lambda x: x,
            "positive": lambda x: x >= 0,
        }

        for idx in ids:
            if idx < 0 and source == "positive_numbers":
                continue
            if idx > 0 and source == "negative_numbers":
                continue

            yield tuple(funcs[p](idx) for p in placeholders)

    def _initialize_sources(self, task_id: int) -> Dict[str, List[str]]:
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
    mapper: Mapper[str, str, None] = Mapper("equality", overrides={"p": "positive_numbers", "n": "negative_numbers"})
    return Translator(hex_fetcher, mapper=mapper, fmt="{id}:{hex}[, positive={positive}]")


@pytest.fixture(scope="session")
def imdb_translator() -> Translator[str, str, str]:
    return Translator.from_config(ROOT.joinpath("config.imdb.toml"))


@pytest.fixture(scope="module")
def translation_map() -> TranslationMap[str, str, str]:
    imdb_translator: Translator[str, str, str] = Translator.from_config(ROOT.joinpath("config.imdb.toml"))
    return imdb_translator.go_offline(names=["firstTitle", "nconst"]).cache
