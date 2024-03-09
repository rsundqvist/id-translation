from typing import Any
from uuid import UUID

import pandas as pd
from pytest_benchmark.fixture import BenchmarkFixture

from id_translation_benchmark.types import IdFactory, TranslatableT
from id_translation import Translator
from id_translation.types import IdType


def run_benchmark(
    benchmark: BenchmarkFixture,
    *,
    count: int,
    id_type: IdFactory[IdType],
    translatable_type: type[TranslatableT],
) -> None:
    translatable, translator = prepare(count, id_type=id_type, translatable_type=translatable_type)
    benchmark(translator.translate, translatable, names="source")


def prepare(
    count: int,
    *,
    id_type: IdFactory[IdType],
    translatable_type: type[TranslatableT],
) -> tuple[TranslatableT, Translator[IdType, str, str]]:
    """Create translatable data and an appropriate ``Translator`` instance.

    Args:
        count: Size of the data.
        id_type: A callable ``(int)-> IdType``.
        translatable_type: A callable ``(pd.Series) -> TranslatableT``.

    Returns:
        A tuple ``(translatable, translator)``.
    """
    data, translatable = _make_data(count, id_type=id_type, translatable_type=translatable_type)

    fetcher_data = {"source": {"id": list(data.keys()), "name": list(data.values())}}
    translator = Translator(fetcher_data)

    return translatable, translator


def make_expected(
    count: int,
    *,
    id_type: IdFactory[IdType],
    translatable_type: type[TranslatableT],
) -> TranslatableT:
    """Construct correctly translated data.

    Args:
        count: Size of the data.
        id_type: A callable ``(int)-> IdType``.
        translatable_type: A callable ``(pd.Series) -> TranslatableT``.

    Returns:
        Translations using the default translation format.
    """
    _, translatable = _make_data(count, id_type=id_type, translatable_type=translatable_type, translated=True)
    return translatable


def _make_data(
    count: int,
    *,
    id_type: IdFactory[IdType],
    translatable_type: type[TranslatableT],
    translated: bool = False,
) -> tuple[dict[IdType, str], TranslatableT]:
    data: dict[Any, str] = {20: "twenty", 19: "nineteen", 5: "five", 11: "eleven"}
    data = {UUID(int=idx) if id_type is UUID else id_type(idx): name for idx, name in data.items()}

    series = pd.Series(list(data.keys())).sample(
        count,
        ignore_index=True,
        replace=True,
        random_state=20190511,
    )

    if translated:
        series = series.map(lambda idx: f"{idx}:{data[idx]}")

    if translatable_type is dict:
        translatable = series.to_frame(name="source").to_dict(orient="list")
    else:
        translatable = translatable_type(series)

    return data, translatable
