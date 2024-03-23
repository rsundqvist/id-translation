import pytest
from id_translation import Translator
from id_translation.dio import DataStructureIO, register_io, resolve_io


def test_register_io():
    assert resolve_io(Data.test_object) is DummyIO
    assert resolve_io(1) is not DummyIO

    translator: Translator[str, str, int] = Translator(Data.data)  # type: ignore[arg-type]
    actual = translator.translate(Data.test_object)  # type: ignore[call-overload]

    assert actual == Data.expected


@pytest.fixture(autouse=True)
def register_tmp_io():
    from id_translation.dio import _resolve

    register_io(DummyIO)
    yield
    _resolve.RESOLUTION_ORDER.remove(DummyIO)


class Data:
    test_object = object()
    test_object_name = "I'm a test object!"
    test_object_id = 1
    data = {"source": {"id": [test_object_id], "name": [test_object_name]}}
    expected = f"{test_object_id}:{test_object_name}"


class DummyIO(DataStructureIO):
    @staticmethod
    def handles_type(arg, *_args, **_kwargs):
        return arg is Data.test_object

    @staticmethod
    def names(translatable):
        assert translatable is Data.test_object
        return ["source"]

    @staticmethod
    def extract(translatable, names):
        assert translatable is Data.test_object
        assert names == ["source"]
        return {names[0]: [Data.test_object_id]}

    @staticmethod
    def insert(translatable, names, tmap, copy):
        assert copy
        assert translatable is Data.test_object
        assert names == ["source"]
        return tmap[names[0]][Data.test_object_id]
