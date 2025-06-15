from uuid import UUID

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
    actual: None | pl.DataFrame = translator.translate(df, copy=copy)
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
