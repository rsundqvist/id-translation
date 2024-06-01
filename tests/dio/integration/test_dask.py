from uuid import UUID

import dask.dataframe as dd
import pytest
from id_translation import Translator
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.dask import DaskIO
from id_translation.types import IdTypes

DaskIO.register()
assert DaskIO.get_rank() == 0


def to_uuid(i: int) -> UUID:
    return UUID(fields=(i, 0, 0, 0, 0, 0))


UNKNOWN = {"uuids": to_uuid(1000), "ints": 1000, "strs": "one thousand!"}
EXPECTED = {
    "uuids": ["00000001:uuid-one", "00000002:uuid-two", "<Failed: id=UUID('000003e8-0000-0000-0000-000000000000')>"],
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
def df(data: dict[str, dict[IdTypes, str]]) -> dd.DataFrame:
    import pandas as pd

    pandas = pd.DataFrame({source: [*id_to_name, UNKNOWN[source]] for source, id_to_name in data.items()})
    return dd.from_pandas(pandas, npartitions=2)


def test_dataframe(translator, df):
    actual: dd.DataFrame = translator.translate(df)
    assert isinstance(actual, dd.DataFrame)
    assert actual.compute().to_dict(orient="list") == EXPECTED


def test_series(translator, df):
    for _, series in df.items():  # noqa: PERF102
        actual: dd.Series = translator.translate(series)
        assert isinstance(actual, dd.Series)
        assert actual.compute().to_list() == EXPECTED[series.name]


@pytest.mark.parametrize("series", [False, True])
def test_inplace(translator, df, series):
    translatable = df[df.columns[0]] if series else df
    with pytest.raises(NotInplaceTranslatableError):
        translator.translate(translatable, copy=False)
