from typing import Any, assert_type

import pytest

from id_translation import Translator
from id_translation.dio import DataStructureIO, _resolve, is_registered, resolve_io
from id_translation.dio.exceptions import UntranslatableTypeError


def test_register_io():
    assert not is_registered(DummyIO)
    DummyIO.register()
    assert resolve_io(Data.test_object).__class__ is DummyIO
    assert resolve_io(1) is not DummyIO

    translator: Translator[str, str, int] = Translator(Data.data)
    actual = translator.translate(Data.test_object)

    # No way to use an Any-bound without breaking overloads (yet)?.
    # The "real" static type is any of the Translatable union types
    assert_type(actual, object)  # type: ignore[assert-type]

    assert actual == Data.expected


class TestNegativePriority:
    def test_explicit_call_warns(self, monkeypatch, caplog):
        assert DummyIO.is_registered() is False

        monkeypatch.setattr(DummyIO, "priority", -1)
        DummyIO.register()
        assert DummyIO.is_registered() is False

        name = _resolve._pretty_io_name(DummyIO)
        assert caplog.messages[-1] == f"Refusing to register '{name}' since priority=-1 < 0."

    def test_update_priority_after_registration(self, monkeypatch):
        DummyIO.register()
        assert DummyIO.is_registered() is True
        monkeypatch.setattr(DummyIO, "priority", -1)
        assert DummyIO.is_registered() is False

        with pytest.raises(UntranslatableTypeError) as exc_info:
            resolve_io(Data())

        note = exc_info.value.__notes__[-1]
        assert "priority < 0" in note
        assert "disabled" in note
        assert _resolve._pretty_io_name(DummyIO) in note


@pytest.fixture(autouse=True)
def register_tmp_io(monkeypatch):
    monkeypatch.setattr(_resolve, "_RESOLUTION_ORDER", [*_resolve._RESOLUTION_ORDER])


class Data:
    test_object = object()
    test_object_name = "I'm a test object!"
    test_object_id = 1
    data = {"source": {"id": [test_object_id], "name": [test_object_name]}}
    expected = f"{test_object_id}:{test_object_name}"


class DummyIO(DataStructureIO[Any, str, str, int]):
    @staticmethod
    def handles_type(arg, *_args, **_kwargs):
        return arg is Data.test_object or arg.__class__ is Data

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
