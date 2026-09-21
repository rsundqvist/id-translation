from typing import Any, assert_type

import pandas as pd
import pytest

from id_translation import Translator
from id_translation.dio import (
    ENTRYPOINT_GROUP,
    DataStructureIO,
    _repository,
    _resolve,
    get_resolution_order,
    is_registered,
    pretty_io_name,
    register_io,
    reload_integrations,
    resolve_io,
)
from id_translation.dio.exceptions import UntranslatableTypeError
from id_translation.dio.integration.pandas import PandasIO


@pytest.fixture(autouse=True)
def register_tmp_io(monkeypatch):
    monkeypatch.setattr(_resolve, "_INSTANCE", None)


def test_entrypoint_groups():
    assert ENTRYPOINT_GROUP == "id_translation.dio"
    assert _repository.ENTRYPOINT_GROUP == ENTRYPOINT_GROUP
    assert _resolve.ENTRYPOINT_GROUP == ENTRYPOINT_GROUP  # type: ignore[attr-defined]


def test_get_resolution_order_returns_a_copy():
    with pytest.raises(TypeError):
        get_resolution_order(real=True)  # type: ignore[call-arg]

    assert get_resolution_order() is not _resolve._get_repository()._enabled


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


def _discover(*ios: type[DataStructureIO[Any, Any, Any, Any]]) -> _repository.Repository:
    return _repository.Repository(ios=ios, load_integrations=False, load_defaults=False)


def _make_io(name: str, priority: int) -> type[DataStructureIO[Any, str, str, int]]:
    class TmpIO(DummyIO):
        pass

    TmpIO.__name__ = TmpIO.__qualname__ = name
    TmpIO.priority = priority
    return TmpIO


class TestState:
    """The sign of `priority` sets the initial state of a discovered implementation. After that, the last call wins."""

    @pytest.mark.parametrize("priority", [1, -1])
    def test_initial_state_follows_the_sign(self, monkeypatch, priority):
        monkeypatch.setattr(DummyIO, "priority", priority)
        assert _discover(DummyIO).is_registered(DummyIO) is (priority > 0)

    @pytest.mark.parametrize("priority", [1, -1])
    @pytest.mark.parametrize("calls", ["R", "U", "UR", "RU", "URU", "RUUR"])
    def test_last_call_wins(self, monkeypatch, priority, calls):
        monkeypatch.setattr(DummyIO, "priority", priority)
        repository = _discover(DummyIO)
        for call in calls:
            (repository.register if call == "R" else repository.unregister)(DummyIO)

        assert repository.is_registered(DummyIO) is (calls[-1] == "R")

    @pytest.mark.parametrize("calls", ["", "R", "U"])
    @pytest.mark.parametrize("new_priority", [2, -2])
    def test_changing_priority_does_not_change_the_state(self, monkeypatch, calls, new_priority):
        repository = _discover(DummyIO)
        for call in calls:
            (repository.register if call == "R" else repository.unregister)(DummyIO)
        expected = repository.is_registered(DummyIO)

        monkeypatch.setattr(DummyIO, "priority", new_priority)
        repository.unregister(_make_io("Unrelated", 1))  # Re-ranks.
        assert repository.is_registered(DummyIO) is expected

    @pytest.mark.parametrize(("calls", "reason"), [("", "opt-in"), ("RU", "unregistered")])
    def test_hint_names_the_reason(self, monkeypatch, calls, reason):
        monkeypatch.setattr(DummyIO, "priority", -1)
        repository = _discover(DummyIO)
        for call in calls:
            (repository.register if call == "R" else repository.unregister)(DummyIO)

        with pytest.raises(UntranslatableTypeError) as exc_info:
            repository.resolve_io(Data())

        note = exc_info.value.__notes__[-1]
        assert f"'{pretty_io_name(DummyIO)}' is disabled ({reason}); call DummyIO.register() to enable it." in note


class TestTies:
    """Equal `abs(priority)`: most recently registered first, then the never registered by qualified name."""

    def test_most_recently_registered_first(self):
        a, b = _make_io("A", 5), _make_io("B", -5)
        repository = _discover()

        repository.register(a)
        repository.register(b)
        assert repository.enabled_ios == [b, a]

        repository.register(a)
        assert repository.enabled_ios == [a, b]

    def test_never_registered_rank_last_by_name(self):
        c, b, a = _make_io("C", 5), _make_io("B", 5), _make_io("A", 5)
        repository = _discover(c, b, a)
        assert repository.enabled_ios == [a, b, c], "discovery order must not matter"

        repository.register(c)
        assert repository.enabled_ios == [c, a, b]

    def test_new_priority_takes_effect_at_the_next_call(self):
        a, b = _make_io("A", 5), _make_io("B", 6)
        repository = _discover(a, b)
        assert repository.enabled_ios == [b, a]

        a.priority = 7
        assert repository.enabled_ios == [b, a]

        repository.unregister(_make_io("Unrelated", 1))
        assert repository.enabled_ios == [a, b]


def test_unregister_removes_a_hand_registered_implementation():
    DummyIO.register()
    assert DummyIO.is_registered() is True

    DummyIO.unregister()
    assert DummyIO.is_registered() is False
    assert DummyIO not in _resolve._get_repository().all_ios
    with pytest.raises(UntranslatableTypeError):
        resolve_io(Data())


def test_unregister_disables_a_built_in():
    PandasIO.unregister()
    assert PandasIO.is_registered() is False
    assert PandasIO in _resolve._get_repository().all_ios, "a discovered implementation is disabled, not forgotten"
    with pytest.raises(UntranslatableTypeError):
        resolve_io(pd.DataFrame())

    PandasIO.register()
    assert PandasIO.get_rank() == 0


def test_reload_integrations_discards_all_calls():
    PandasIO.unregister()
    DummyIO.register()

    reload_integrations()
    assert PandasIO.is_registered() is True
    assert DummyIO.is_registered() is False


class TestOverridingABuiltIn:
    """Replacing a built-in like `PandasIO`: register a competing implementation. The one with the largest
    `abs(priority)` is tried first, unless the built-in is unregistered, in which case priority does not matter.
    """

    @staticmethod
    def _make_custom_pandas_io(priority: int) -> type[DataStructureIO[Any, str, str, int]]:
        class CustomPandasIO(DataStructureIO[Any, str, str, int]):
            priority = 0

            @staticmethod
            def handles_type(arg, *_args, **_kwargs):
                return isinstance(arg, pd.DataFrame)

            @staticmethod
            def names(translatable):
                raise NotImplementedError

            @staticmethod
            def extract(translatable, names):
                raise NotImplementedError

            @staticmethod
            def insert(translatable, names, tmap, copy):
                raise NotImplementedError

        CustomPandasIO.priority = priority
        return CustomPandasIO

    @pytest.mark.parametrize(
        ("priority_delta", "custom_wins"),
        [
            pytest.param(-1, False, id="lower"),
            pytest.param(0, True, id="equal"),
            pytest.param(1, True, id="higher"),
        ],
    )
    def test_register_only(self, priority_delta, custom_wins):
        custom = self._make_custom_pandas_io(PandasIO.priority + priority_delta)
        register_io(custom)

        expected = custom if custom_wins else PandasIO
        assert resolve_io(pd.DataFrame()).__class__ is expected

    @pytest.mark.parametrize("priority_delta", [-1, 0, 1])
    @pytest.mark.parametrize("when", ["before", "after"])
    def test_unregister_is_order_invariant(self, priority_delta, when):
        if when == "before":
            PandasIO.unregister()

        custom = self._make_custom_pandas_io(PandasIO.priority + priority_delta)
        register_io(custom)

        if when == "after":
            PandasIO.unregister()

        assert resolve_io(pd.DataFrame()).__class__ is custom


class _FakeEntryPoint:
    """Duck-typed stand-in for `importlib.metadata.EntryPoint`; avoids resolving a real module."""

    def __init__(self, cls: type) -> None:
        self._cls = cls

    def load(self) -> type:
        return self._cls

    def __repr__(self) -> str:
        return "EntryPoint(name='not-a-dio', value='tests.dio.test_register_io:int', group='id_translation.dio')"


def test_bad_entrypoint_not_a_data_structure_io(monkeypatch):
    monkeypatch.setattr(_repository, "entry_points", lambda group: [_FakeEntryPoint(int)])  # noqa: ARG005

    with pytest.raises(TypeError, match=r"Bad entrypoint=.*: <class 'int'> is not a subtype of DataStructureIO\. "):
        _repository.Repository(load_defaults=False)


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
