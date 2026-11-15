from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import polars as pl
import pytest

from id_translation import Translator
from id_translation.dio.integration.polars import PolarsIO
from id_translation.types import IdTypes

assert PolarsIO.is_registered(), "entrypoint loader failed"
assert PolarsIO.get_rank() == 1


def to_uuid(i: int) -> UUID:
    return UUID(fields=(i, 0, 0, 0, 0, 0))


UNKNOWN = {"uuids": to_uuid(1000), "ints": 1000, "strs": "one thousand!"}
EXPECTED = {
    "uuids": ["00000001:uuid-one", "00000002:uuid-two", "<Failed: id='000003e8-0000-0000-0000-000000000000'>"],
    "ints": ["0:int-zero", "1:int-one", "<Failed: id=1000>"],
    "strs": ["zero!:str-zero", "one!:str-one", "<Failed: id='one thousand!'>"],
}


@pytest.fixture
def data() -> dict[str, dict[IdTypes, str]]:
    return {
        "uuids": {to_uuid(1): "uuid-one", str(to_uuid(2)): "uuid-two"},
        "ints": {0: "int-zero", 1: "int-one"},
        "strs": {"zero!": "str-zero", "one!": "str-one"},
    }


@pytest.fixture
def translator(data: dict[str, dict[IdTypes, str]]) -> Translator[str, str, IdTypes]:
    return Translator[str, str, IdTypes](data, fmt="{id!s:.8}:{name}", enable_uuid_heuristics=True)


@pytest.fixture
def df(data: dict[str, dict[IdTypes, str]]) -> pl.DataFrame:
    return pl.DataFrame(
        {source: pl.Series(values=[*id_to_name, UNKNOWN[source]]) for source, id_to_name in data.items()}
    )


@pytest.mark.parametrize("copy", [True, False])
def test_dataframe(translator, df, copy):
    actual: pl.DataFrame | None = translator.translate(df, copy=copy)
    if copy:
        assert actual is not None
        assert actual.to_dict(as_series=False) == EXPECTED
    else:
        assert actual is None
        assert df.to_dict(as_series=False) == EXPECTED


@pytest.mark.parametrize("column", [*UNKNOWN])
def test_series(translator, df, column):
    series = df[column]
    actual: pl.Series = translator.translate(series)
    assert actual.to_list() == EXPECTED[series.name]


@pytest.mark.parametrize("ids", [[0, 0, None], [0.0, 0.0, None, float("nan")]])
def test_missing_ids_are_not_counted(translator, ids):
    actual = translator.translate(pl.Series("ints", ids), max_fails=0.0)
    assert actual.to_list() == ["0:int-zero", "0:int-zero", *(f"<Failed: id={idx}>" for idx in ids[2:])]


@pytest.mark.parametrize(
    "missing",
    [
        None,
        float("nan"),
        np.float32("nan"),
        pd.NA,
    ],
)
def test_object_missing_values_are_not_extracted(missing):
    series = pl.Series("x", [0, 0, missing], dtype=pl.Object)
    assert PolarsIO.extract(series, ["x"]) == {"x": ["0"]}


@pytest.mark.parametrize("ids", [[None, None], []])
def test_object_without_ids(ids):
    assert PolarsIO.extract(pl.Series("x", ids, dtype=pl.Object), ["x"]) == {"x": []}


@pytest.mark.parametrize("fast", [False, True])
def test_object_nan_does_not_take_the_nan_string_ids_translation(fast):
    translator = Translator[str, str, IdTypes](fetcher={"x": {"0": "zero", "nan": "nan-row"}}, fmt="{name}")
    series = pl.Series("x", [0, None, float("nan"), "nan"], dtype=pl.Object)
    actual = translator.translate(series, max_fails=0.0, io_kwargs={"fast": fast})
    assert isinstance(actual, pl.Series)
    missing = "" if fast else "<Failed: id=None>"
    assert actual.to_list() == ["zero", missing, missing, "nan-row"]


@pytest.mark.parametrize("uuid_keys", [False, True])
@pytest.mark.parametrize("dtype", [pl.String, pl.Object])
def test_fast_with_uuid_heuristics(uuid_keys, dtype):
    ids = [to_uuid(1), to_uuid(2)]
    data = {"x": {(idx if uuid_keys else str(idx)): f"n{i}" for i, idx in enumerate(ids)}}
    translator = Translator[str, str, IdTypes](data, fmt="{name}", enable_uuid_heuristics=True)
    series = pl.Series("x", ids if dtype == pl.Object else list(map(str, ids)), dtype=dtype)
    actual = translator.translate(series, io_kwargs={"fast": True})
    assert isinstance(actual, pl.Series)
    assert actual.to_list() == ["n0", "n1"]


@pytest.mark.parametrize("dtype", [pl.String, pl.Object])
def test_fast_with_uuid_keys_without_heuristics(dtype):
    ids = [to_uuid(1), to_uuid(2)]
    translator = Translator[str, str, IdTypes]({"x": {idx: f"n{i}" for i, idx in enumerate(ids)}}, fmt="{name}")
    series = pl.Series("x", ids if dtype == pl.Object else list(map(str, ids)), dtype=dtype)
    # Unknown as in non-fast mode, where a str ID does not match a UUID key without heuristics; replace_strict() raised.
    actual = translator.translate(series, io_kwargs={"fast": True})
    assert isinstance(actual, pl.Series)
    assert actual.to_list() == ["", ""]


@pytest.mark.parametrize(
    "data, ids, expected",
    [
        ({to_uuid(1): "u", "a": "A"}, ["a", str(to_uuid(1))], ["A", ""]),  # UUID first: dropped up front.
        ({"a": "A", to_uuid(1): "u"}, ["a", str(to_uuid(1))], ["A", ""]),  # Dropped on retry.
        ({1: "one", to_uuid(1): "u"}, [1, 2], ["one", ""]),  # Retry after a different polars error.
    ],
    ids=["uuid-first", "str-first", "int-first"],
)
@pytest.mark.parametrize("kind", [pl.Series, pl.DataFrame])
def test_fast_drops_uuid_keys_and_keeps_the_rest(data, ids, expected, kind):
    translator = Translator[str, str, IdTypes]({"x": data}, fmt="{name}")
    series = pl.Series("x", ids)
    actual = translator.translate(series if kind is pl.Series else series.to_frame(), io_kwargs={"fast": True})
    assert isinstance(actual, kind)
    assert (actual if isinstance(actual, pl.Series) else actual["x"]).to_list() == expected


@pytest.mark.parametrize("keys", [{"a": "A"}, {1: "one"}])
def test_fast_all_null(keys):
    translator = Translator[str, str, IdTypes]({"x": keys}, fmt="{name}")
    actual = translator.translate(pl.Series("x", [None, None]), io_kwargs={"fast": True})
    assert isinstance(actual, pl.Series)
    assert actual.to_list() == ["", ""]


@pytest.mark.parametrize(
    "data",
    [
        {to_uuid(0): "other", str(to_uuid(1)): "exact", to_uuid(1): "cast"},  # The old code returned 'cast'.
        {to_uuid(1): "cast", str(to_uuid(1)): "exact"},
        {str(to_uuid(1)): "exact", to_uuid(1): "cast"},
    ],
    ids=["uuid-exact-cast", "cast-exact", "exact-cast"],
)
def test_fast_exact_key_wins_over_cast_uuid(data):
    translator = Translator[str, str, IdTypes]({"x": data}, fmt="{name}", enable_uuid_heuristics=True)
    uuid = str(to_uuid(1))
    assert translator.translate(uuid, names="x") == "exact"
    for fast in (False, True):
        actual = translator.translate(pl.Series("x", [uuid]), io_kwargs={"fast": fast})
        assert isinstance(actual, pl.Series)
        assert actual.to_list() == ["exact"], f"{fast=}"


def test_fast_reraises_a_type_error_without_uuid_keys(monkeypatch):
    calls = []
    replace_strict = pl.Series.replace_strict

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return replace_strict(*args, **kwargs)

    monkeypatch.setattr(pl.Series, "replace_strict", counting)

    translator = Translator[str, str, IdTypes]({"x": {1: "one", "a": "A"}}, fmt="{name}")
    with pytest.raises(TypeError):
        translator.translate(pl.Series("x", [1]), io_kwargs={"fast": True})
    assert len(calls) == 1, "retried without UUID keys to drop"


def test_dataframe_fast(translator):
    translator = Translator[str, str, IdTypes](
        fetcher={
            "uuids": {str(to_uuid(1)): "uuid-one", str(to_uuid(2)): "uuid-two"},
            "ints": {0: "int-zero", 1: "int-one"},
            "strs": {"zero!": "str-zero", "one!": "str-one"},
        },
        fmt="{id!s:.8}:{name}",
    )

    data: dict[str, list[object]] = {
        "uuids": [str(to_uuid(1)), str(to_uuid(2)), str(to_uuid(1000))],
        "ints": [0, 1, 1000],
        "strs": ["zero!", "one!", "one thousand!"],
    }
    df = pl.from_dict(data)

    actual: pl.DataFrame = translator.translate(df, copy=True, io_kwargs={"fast": True})
    assert isinstance(actual, pl.DataFrame)
    assert actual.to_dict(as_series=False) == {
        "uuids": ["00000001:uuid-one", "00000002:uuid-two", ""],
        "ints": ["0:int-zero", "1:int-one", ""],
        "strs": ["zero!:str-zero", "one!:str-one", ""],
    }


@pytest.mark.parametrize("online", [False, True])
def test_explicit_name_missing_from_the_data_raises(data, online):
    from id_translation.exceptions import MissingNamesError
    from id_translation.fetching import MemoryFetcher

    fetcher: MemoryFetcher[str, IdTypes] = MemoryFetcher({"ints": {"id": [0, 1], "name": ["int-zero", "int-one"]}})
    translator = Translator[str, str, IdTypes](fetcher if online else data, fmt="{id!s:.8}:{name}")
    with pytest.raises(MissingNamesError, match="nope") as exc_info:
        translator.translate(
            pl.DataFrame({"ints": [0, 1]}), names=["ints", "nope"], override_function=lambda *_: "ints"
        )
    assert exc_info.value.missing == ("nope",)


def test_all_missing_ids(translator):
    assert translator.translate(pl.Series("ints", [None], dtype=pl.Int64), max_fails=0.0).to_list() == [
        "<Failed: id=None>"
    ]
