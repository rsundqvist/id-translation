import warnings
from collections.abc import MutableMapping

import pytest

from id_translation.transform import TransformerStack
from id_translation.transform.types import Transformer


class Recorder(Transformer[int]):
    def __init__(self, tag: str, calls: list[tuple[str, str]]) -> None:
        self.tag = tag
        self.calls = calls

    def update_ids(self, ids: set[int], /) -> None:
        self.calls.append((self.tag, "update_ids"))
        ids.add(len(ids))

    def update_translations(self, translations: dict[int, str], /) -> None:
        self.calls.append((self.tag, "update_translations"))
        for key in translations:
            translations[key] += f"|{self.tag}"

    def try_add_missing_key(self, key: int, /, *, translations: MutableMapping[int, str]) -> None:
        self.calls.append((self.tag, "try_add_missing_key"))
        translations[key] = self.tag


@pytest.fixture
def calls() -> list[tuple[str, str]]:
    return []


@pytest.fixture
def stack(calls: list[tuple[str, str]]) -> TransformerStack[int]:
    return TransformerStack(Recorder("first", calls), Recorder("second", calls))


def test_is_transformer(stack):
    assert isinstance(stack, Transformer)


def test_update_ids_call_order(stack, calls):
    ids = {0}
    stack.update_ids(ids)

    assert calls == [("first", "update_ids"), ("second", "update_ids")]
    assert ids == {0, 1, 2}, "second member should see IDs added by the first"


def test_update_translations_last_writer_wins(stack, calls):
    translations = {0: "zero"}
    stack.update_translations(translations)

    assert calls == [("first", "update_translations"), ("second", "update_translations")]
    assert translations == {0: "zero|first|second"}


def test_try_add_missing_key_last_writer_wins(stack, calls):
    translations: dict[int, str] = {}
    stack.try_add_missing_key(0, translations=translations)

    assert calls == [("first", "try_add_missing_key"), ("second", "try_add_missing_key")]
    assert translations == {0: "second"}


def test_flattens_nested_stacks(calls):
    first = Recorder("first", calls)
    second = Recorder("second", calls)
    third = Recorder("third", calls)

    stack = TransformerStack(TransformerStack(first, second), third)
    assert stack.transformers == (first, second, third)


def test_eq(calls):
    transformers = Recorder("first", calls), Recorder("second", calls)
    assert TransformerStack(*transformers) == TransformerStack(*transformers)
    assert TransformerStack(*transformers) != TransformerStack(*reversed(transformers))


def test_empty_stack_raises():
    """An empty stack is a silent no-op; the sequence path rejects the same thing, so this must too."""
    with pytest.raises(ValueError, match="Transformer chain is empty"):
        TransformerStack()


class TestDuplicateMembers:
    def test_same_instance(self, calls):
        recorder = Recorder("duplicate", calls)
        with pytest.warns(UserWarning, match="Duplicate transformer"):
            TransformerStack(recorder, recorder)

    def test_equal_instances(self):
        from id_translation.transform import BitmaskTransformer

        first, second = BitmaskTransformer(), BitmaskTransformer()
        assert first == second, "precondition: BitmaskTransformer compares by value"

        with pytest.warns(UserWarning, match="Duplicate transformer"):
            TransformerStack(first, second)

    def test_unequal_instances_do_not_warn(self):
        from id_translation.transform import BitmaskTransformer

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            TransformerStack(BitmaskTransformer(), BitmaskTransformer(joiner=" + "))

    def test_append_does_not_replay(self, calls):
        """A stack reported its own duplicates when it was built; appending must only check the new pairings."""
        duplicated = Recorder("duplicate", calls)
        with pytest.warns(UserWarning, match="Duplicate transformer"):
            stack = TransformerStack(duplicated, duplicated)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            stack = TransformerStack(stack, Recorder("new", calls))
            TransformerStack(stack, Recorder("newer", calls))

    def test_append_of_an_actual_duplicate_still_warns(self, calls):
        duplicated = Recorder("duplicate", calls)
        stack = TransformerStack(duplicated, Recorder("other", calls))

        with pytest.warns(UserWarning, match="Duplicate transformer"):
            TransformerStack(stack, duplicated)

    def test_equal_state_without_eq_does_not_warn(self, calls):
        """Without an ``__eq__``, only identity makes a repeat; equally-configured instances are distinct members."""
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            TransformerStack(Recorder("same", calls), Recorder("same", calls))

    def test_unequal_state_without_eq_does_not_warn(self, calls):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            TransformerStack(Recorder("first", calls), Recorder("second", calls))

    @pytest.mark.parametrize("error", [TypeError("cannot compare"), ValueError("truth value is ambiguous")])
    def test_broken_eq_falls_back_to_identity(self, calls, error):
        """Members are not required to implement __eq__ sanely; identity is all we can rely on for these."""

        class BadEq(Recorder):
            def __eq__(self, other: object) -> bool:
                raise error

            __hash__ = None  # type: ignore[assignment]

        first, second = BadEq("first", calls), BadEq("second", calls)

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            TransformerStack(first, second)

        with pytest.warns(UserWarning, match="Duplicate transformer"):
            TransformerStack(first, first)


class TestHashing:
    def test_hashable_members(self, calls):
        first, second = Recorder("first", calls), Recorder("second", calls)
        assert hash(TransformerStack(first, second)) == hash(TransformerStack(first, second))

    def test_unhashable_member(self, calls):
        """Members are not required to be hashable, and the stack cannot be more hashable than its contents."""

        class Unhashable(Recorder):
            def __eq__(self, other: object) -> bool:
                return self is other

            __hash__ = None  # type: ignore[assignment]

        with pytest.raises(TypeError, match="unhashable"):
            hash(TransformerStack(Unhashable("first", calls), Recorder("second", calls)))


def test_is_final():
    """Composing behavior needs no inheritance -- Transformer is a Protocol."""
    assert getattr(TransformerStack, "__final__", False) is True
