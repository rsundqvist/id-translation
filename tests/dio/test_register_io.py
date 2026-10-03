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
from id_translation.dio.exceptions import DataStructureIOError, UntranslatableTypeError
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

    get_resolution_order().clear()
    assert get_resolution_order()


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


def _replay(
    repository: _repository.Repository, calls: str, io_class: type[DataStructureIO[Any, Any, Any, Any]]
) -> None:
    """Replay a "R"/"U" string as `register()`/`unregister()` calls, in order."""
    funcs = {"R": repository.register, "U": repository.unregister}
    for call in calls:
        func = funcs[call]
        func(io_class)


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
        _replay(repository, calls, DummyIO)

        assert repository.is_registered(DummyIO) is (calls[-1] == "R")

    @pytest.mark.parametrize("calls", ["", "R", "U"])
    @pytest.mark.parametrize("new_priority", [2, -2])
    def test_changing_priority_does_not_change_the_state(self, monkeypatch, calls, new_priority):
        repository = _discover(DummyIO)
        _replay(repository, calls, DummyIO)
        expected = DummyIO in repository.disabled_ios  # Unlike is_registered(), doesn't raise on a changed priority.

        monkeypatch.setattr(DummyIO, "priority", new_priority)
        repository.unregister(_make_io("Unrelated", 1))
        assert (DummyIO in repository.disabled_ios) is expected

    @pytest.mark.parametrize(("calls", "reason"), [("", "opt-in"), ("RU", "unregistered")])
    def test_hint_names_the_reason(self, monkeypatch, calls, reason):
        monkeypatch.setattr(DummyIO, "priority", -1)
        repository = _discover(DummyIO)
        _replay(repository, calls, DummyIO)

        with pytest.raises(UntranslatableTypeError) as exc_info:
            repository.resolve_io(Data())

        note = exc_info.value.__notes__[-1]
        assert f"disabled ({reason}); call {pretty_io_name(DummyIO)}.register() to enable it." in note


_RERANK_HINT = "Call {}.register() to apply the new priority, or unregister() to disable it."
_NEGATED_HINT = "A negative priority does not disable a registered implementation; call {}.unregister()."


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

    @pytest.mark.parametrize("new_priority", [7, -5], ids=["reranked", "negated"])
    def test_changing_priority_raises_until_registered_again(self, new_priority):
        a, b = _make_io("A", 5), _make_io("B", 6)
        repository = _discover(a, b)
        assert repository.enabled_ios == [b, a]

        a.priority = new_priority
        repository.unregister(_make_io("Unrelated", 1))  # Must not apply the change silently.
        with pytest.raises(DataStructureIOError, match=rf"A\.priority changed from 5 to {new_priority}"):
            repository.enabled_ios  # noqa: B018
        with pytest.raises(DataStructureIOError, match=rf"A\.priority changed from 5 to {new_priority}"):
            repository.resolve_io(1)

        repository.register(a)
        assert repository.enabled_ios == ([a, b] if abs(new_priority) > 6 else [b, a])

    @pytest.mark.parametrize(
        ("old_priority", "new_priority", "hint"),
        [
            (5, 7, _RERANK_HINT),
            (-5, -7, _RERANK_HINT),  # Opt-in, so negative while registered.
            (-5, 7, _RERANK_HINT),
            (5, -5, _NEGATED_HINT),
            (0, -1, _NEGATED_HINT),
        ],
    )
    def test_hint_for_a_changed_priority(self, old_priority, new_priority, hint):
        a = _make_io("A", old_priority)
        repository = _discover()
        repository.register(a)

        a.priority = new_priority
        with pytest.raises(DataStructureIOError, match=rf"changed from {old_priority} to {new_priority}") as exc_info:
            repository.resolve_io(1)
        assert exc_info.value.__notes__[-1] == f"Hint: {hint.format(pretty_io_name(a))}"

    def test_every_changed_priority_is_named(self):
        a, b, c = _make_io("A", 5), _make_io("B", 6), _make_io("C", 7)
        repository = _discover(a, b, c)

        a.priority, c.priority = 1, 2
        with pytest.raises(DataStructureIOError, match=r"^C\.priority changed from 7 to 2") as exc_info:
            repository.resolve_io(1)
        assert str(exc_info.value).endswith(" Also changed: A.")
        assert exc_info.value.__notes__[-1] == f"Hint: {_RERANK_HINT.format(pretty_io_name(c))}"

    @pytest.mark.parametrize(
        ("new_a", "new_b", "hints"),
        [
            (8, -5, [_RERANK_HINT, "Call unregister() on B instead."]),
            (-7, 6, [_NEGATED_HINT, "Call register() on B instead."]),
        ],
    )
    def test_mixed_changes_name_the_other_call(self, new_a, new_b, hints):
        a, b = _make_io("A", 7), _make_io("B", 5)
        repository = _discover(a, b)

        a.priority, b.priority = new_a, new_b
        with pytest.raises(DataStructureIOError, match=r"^A\.priority changed") as exc_info:
            repository.resolve_io(1)
        assert str(exc_info.value).endswith(" Also changed: B.")
        assert exc_info.value.__notes__[-2:] == [f"Hint: {h.format(pretty_io_name(a))}" for h in hints]

    def test_mixed_changes_across_registered_and_disabled(self):
        a, b = _make_io("A", 5), _make_io("B", -7)
        repository = _discover(a, b)

        a.priority, b.priority = -5, 7  # The 1.x ways to disable and to enable.
        with pytest.raises(DataStructureIOError, match=r"^A\.priority changed from 5 to -5") as exc_info:
            repository.resolve_io(1)
        assert str(exc_info.value).endswith(" Also changed: B.")
        assert exc_info.value.__notes__[-2:] == [
            f"Hint: {_NEGATED_HINT.format(pretty_io_name(a))}",
            "Hint: Call register() on B instead.",
        ]

    @pytest.mark.parametrize("fix", ["register", "unregister"])
    @pytest.mark.parametrize("new_priority", [7, 0])
    @pytest.mark.parametrize("calls", ["", "RU"], ids=["opt-in", "unregistered"])
    def test_making_a_disabled_priority_non_negative_raises(self, calls, new_priority, fix):
        a, b = _make_io("A", -7), _make_io("B", 5)
        repository = _discover(a, b)
        _replay(repository, calls, a)

        a.priority = new_priority  # The 1.x way to enable.
        with pytest.raises(DataStructureIOError, match=rf"^A\.priority changed from -7 to {new_priority} ") as exc_info:
            repository.resolve_io(1)
        expected = (
            "A non-negative priority does not enable a disabled implementation; call {}.register() to enable it, or"
            " unregister() to keep it disabled."
        )
        assert exc_info.value.__notes__[-1] == f"Hint: {expected.format(pretty_io_name(a))}"

        getattr(repository, fix)(a)
        if fix == "register":
            assert repository.enabled_ios == ([a, b] if new_priority > 5 else [b, a]), "enabled at the new priority"
        else:
            assert repository.enabled_ios == [b], "still disabled"

    @pytest.mark.parametrize(
        ("old_priority", "new_priority", "calls"),
        [(-7, -9, ""), (7, 9, "U"), (7, -7, "U")],
        ids=["opt-in", "unregistered", "unregistered-negated"],
    )
    def test_other_changes_to_a_disabled_priority_are_read_at_register(self, old_priority, new_priority, calls):
        a = _make_io("A", old_priority)
        repository = _discover(a)
        _replay(repository, calls, a)

        a.priority = new_priority
        assert repository.enabled_ios == []
        repository.register(a)
        assert repository.enabled_ios == [a]

    def test_changing_an_inherited_priority_names_the_owner(self):
        base = _make_io("Base", 5)
        child = type("Child", (base,), {})
        repository = _discover(child)

        base.priority = 6
        with pytest.raises(DataStructureIOError, match=r"^Child\.priority changed from 5 to 6.*inherited from Base\."):
            repository.resolve_io(1)


@pytest.mark.parametrize("read", ["get_rank", "is_registered"])
def test_read_raises_on_a_changed_priority(monkeypatch, read):
    DummyIO.register()
    monkeypatch.setattr(DummyIO, "priority", DummyIO.priority + 1)
    with pytest.raises(DataStructureIOError, match=r"^DummyIO\.priority changed"):
        getattr(DummyIO, read)()


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
