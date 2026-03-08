from uuid import UUID

import pyarrow as pa  # type: ignore[import-untyped]
import pytest

from id_translation import Translator
from id_translation.dio import load_integrations
from id_translation.dio.exceptions import NotInplaceTranslatableError
from id_translation.dio.integration.pyarrow import ArrowIO
from id_translation.types import IdTypes


def to_uuid(i: int) -> UUID:
    return UUID(fields=(i, 0, 0, 0, 0, 0))


UNKNOWN = {"ints": 1000, "strs": "one thousand!"}
EXPECTED = {
    "ints": ["0:int-zero", "1:int-one", "<Failed: id=1000>"],
    "strs": ["zero!:str-zero", "one!:str-one", "<Failed: id='one thousand!'>"],
}


@pytest.fixture
def data() -> dict[str, dict[IdTypes, str]]:
    return {
        "ints": {0: "int-zero", 1: "int-one"},
        "strs": {"zero!": "str-zero", "one!": "str-one"},
    }


@pytest.fixture
def translator(data: dict[str, dict[IdTypes, str]]) -> Translator[str, str, IdTypes]:
    return Translator[str, str, IdTypes](data, fmt="{id!s:.8}:{name}", enable_uuid_heuristics=True)


@pytest.fixture
def table(data: dict[str, dict[IdTypes, str]]) -> pa.Table:
    return pa.table({source: [*id_to_name, UNKNOWN[source]] for source, id_to_name in data.items()})


@pytest.mark.parametrize("cls", [pa.Table, pa.Array, pa.ChunkedArray])
def test_inplace_raises(translator, table, cls):
    translatable = table if cls is pa.Table else table[table.column_names[0]]
    if cls is pa.Array:
        translatable = translatable.chunk(0)
    assert isinstance(translatable, cls)

    with pytest.raises(NotInplaceTranslatableError):
        translator.translate(translatable, names=["ints"], copy=False)


def test_table(translator, table):
    actual = translator.translate(table)
    assert isinstance(actual, pa.Table)
    assert actual.to_pydict() == EXPECTED


@pytest.mark.parametrize("column", [*UNKNOWN])
def test_chunked_array(translator, table, column):
    actual = translator.translate(table[column])
    assert isinstance(actual, pa.ChunkedArray)
    assert actual.to_pylist() == EXPECTED[column]


@pytest.mark.parametrize("column", [*UNKNOWN])
def test_array(translator, table, column):
    actual = translator.translate(table[column]).chunk(0)
    assert isinstance(actual, pa.Array)
    assert actual.to_pylist() == EXPECTED[column]


@pytest.fixture(autouse=True)
def register():
    assert not ArrowIO.is_registered(), f"{ArrowIO.priority=}"

    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr(ArrowIO, "priority", -ArrowIO.priority)

        ArrowIO.register()
        yield

    load_integrations()
