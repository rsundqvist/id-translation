import warnings
from uuid import UUID

import dask.dataframe as dd
import numpy as np
import pytest

from id_translation import Translator
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.dask import DaskIO
from id_translation.types import IdTypes

assert DaskIO.is_registered(), "entrypoint loader failed"
assert DaskIO.get_rank() == 2


@pytest.fixture(autouse=True)
def _opted_in(monkeypatch):
    """Silence the 2.0.0 notice for the tests that are not about it; `TestOptInDeprecation` opts back out."""
    monkeypatch.setattr(DaskIO, "_opted_in", True)


class TestOptInDeprecation:
    """2.0.0 makes DaskIO opt-in; `TODO(2.0.0)` in `dio/integration/dask.py` retires this."""

    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        monkeypatch.setattr(DaskIO, "_opted_in", False)
        monkeypatch.setattr(DaskIO, "_warned", False)

    def test_warns_once_not_per_translation(self, translator, df):
        """`resolve_io` builds a fresh IO per task, so an unguarded warning would fire on every frame."""
        with pytest.warns(FutureWarning, match=r"DaskIO\.register\(\).*2\.0\.0") as record:
            for _ in range(5):
                translator.translate(df)

        assert len(record) == 1, "one notice per process, not one per translated frame"

    def test_silent_after_opting_in(self, translator, df):
        DaskIO.register()

        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            translator.translate(df)


def to_uuid(i: int) -> UUID:
    return UUID(fields=(i, 0, 0, 0, 0, 0))


UNKNOWN = {"uuids": to_uuid(1000), "ints": 1000, "strs": "one thousand!"}
EXPECTED = {
    "uuids": ["00000001:uuid-one", "00000002:uuid-two", "<Failed: id='000003e8-0000-0000-0000-000000000000'>"],
    "ints": ["0:int-zero", "1:int-one", "<Failed: id=1000>"],
    "strs": ["zero!:str-zero", "one!:str-one", "<Failed: id='one thousand!'>"],
}
EXPECTED_CAT = {
    "uuids": ["00000001:uuid-one", "00000002:uuid-two", np.nan],
    "ints": ["0:int-zero", "1:int-one", np.nan],
    "strs": ["zero!:str-zero", "one!:str-one", np.nan],
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
def df(data: dict[str, dict[IdTypes, str]]) -> dd.DataFrame:
    import pandas as pd

    pandas = pd.DataFrame({source: [*id_to_name, UNKNOWN[source]] for source, id_to_name in data.items()})
    return dd.from_pandas(pandas, npartitions=2)  # type: ignore[no-any-return]


def test_dataframe(translator, df):
    actual: dd.DataFrame = translator.translate(df)
    assert isinstance(actual, dd.DataFrame)

    df = actual.compute()
    assert df.dtypes.to_dict() == {"uuids": "str", "ints": "str", "strs": "str"}
    assert actual.compute().to_dict(orient="list") == EXPECTED


def test_dataframe_cat(translator, df):
    actual: dd.DataFrame = translator.translate(df, io_kwargs={"as_category": True})
    assert isinstance(actual, dd.DataFrame)

    df = actual.compute()
    assert df.dtypes.to_dict() == {"uuids": "category", "ints": "category", "strs": "category"}
    assert df.to_dict(orient="list") == EXPECTED_CAT


def test_series(translator, df):
    for _, series in df.items():  # noqa: PERF102
        actual: dd.Series = translator.translate(series)
        assert isinstance(actual, dd.Series)

        pd_series = actual.compute()
        assert pd_series.dtype == "str"
        assert pd_series.to_list() == EXPECTED[series.name]


def test_series_cat(translator, df):
    for _, series in df.items():  # noqa: PERF102
        actual: dd.Series = translator.translate(series, io_kwargs={"as_category": True})
        assert isinstance(actual, dd.Series)

        pd_series = actual.compute()
        assert pd_series.dtype == "category"
        assert pd_series.to_list() == EXPECTED_CAT[series.name]


@pytest.mark.parametrize("cls", [dd.Series, dd.DataFrame])
def test_inplace_raises(translator, df, cls):
    translatable = df[df.columns[0]] if cls is dd.Series else df
    assert isinstance(translatable, cls)

    with pytest.raises(NotInplaceTranslatableError):
        translator.translate(translatable, copy=False)


@pytest.mark.parametrize(
    ("ordered", "expected_categories"),
    [("name", ["a", "b", "c"]), ("id", ["c", "a", "b"])],
)
def test_series_cat_ordered(ordered, expected_categories):
    """The `ordered` keyword must reach the per-partition `PandasIO`, giving every partition the same dtype."""
    import pandas as pd

    translator = Translator[str, str, int]({"s": {1: "c", 2: "a", 10: "b"}}, fmt="{name}")
    series = dd.from_pandas(pd.Series([1, 2, 10], name="s"), npartitions=2)

    actual: dd.Series = translator.translate(series, io_kwargs={"as_category": True, "ordered": ordered})
    pd_series = actual.compute()

    assert pd_series.cat.categories.to_list() == expected_categories
    assert pd_series.to_list() == ["c", "a", "b"]
