"""Ordered composition of transformers."""

import typing as _t
from collections import abc as _abc

from ..._utils.emit_warning import emit_warning as _emit_warning
from ...types import IdType as _IdType
from ..types import Transformer as _Transformer

TransformersTuple = tuple[_Transformer[_IdType], ...]

_EMPTY_CHAIN = "Transformer chain is empty; pass a transformer, a non-empty sequence, or drop the key."


@_t.final
class TransformerStack(_Transformer[_IdType]):
    """Ordered composition of :class:`~id_translation.transform.types.Transformer` instances.

    All ``Transformer`` methods delegate to each member in the given order. Later members see, and may overwrite,
    changes made by the members before them. Repeating a member emits a warning; every member runs, so it is applied
    multiple times. Members are matched by identity, then by ``__eq__``.

    A stack is hashable only if all of its members are; a member that implements ``__eq__`` without ``__hash__`` is
    unhashable, and hashing a stack containing one raises :class:`TypeError`, as it would for a ``tuple``.

    .. seealso::

       The :meth:`Translator.register_transformer <id_translation.Translator.register_transformer>` method.

    Args:
        *transformers: Transformers to invoke in order. Nested stacks are flattened.

    Raises:
        ValueError: If no members are given; an empty stack is a silent no-op.
    """

    def __init__(self, *transformers: _Transformer[_IdType]) -> None:
        self._transformers = _flatten_members(transformers)

    @property
    def transformers(self) -> TransformersTuple[_IdType]:
        """Member transformers in call order."""
        return self._transformers

    def update_ids(self, ids: set[_IdType], /) -> None:
        for transformer in self._transformers:
            transformer.update_ids(ids)

    def update_translations(self, translations: dict[_IdType, str], /) -> None:
        for transformer in self._transformers:
            transformer.update_translations(translations)

    def try_add_missing_key(self, key: _IdType, /, *, translations: _abc.MutableMapping[_IdType, str]) -> None:
        for transformer in self._transformers:
            transformer.try_add_missing_key(key, translations=translations)

    def __repr__(self) -> str:
        inner = ", ".join(map(repr, self._transformers))
        return f"{type(self).__name__}({inner})"

    def __eq__(self, other: object) -> bool:
        return type(other) is TransformerStack and self._transformers == other._transformers

    def __hash__(self) -> int:
        return hash((TransformerStack, self._transformers))


def _flatten_members(transformers: TransformersTuple[_IdType]) -> TransformersTuple[_IdType]:
    flattened: list[_Transformer[_IdType]] = []

    for transformer in transformers:
        # An existing stack reported its own duplicates when it was built, so only the new pairings are checked --
        # otherwise every `on_existing='append'` would replay the warnings of the stack it appends to.
        members = transformer.transformers if isinstance(transformer, TransformerStack) else (transformer,)

        for member in members:
            if any(_is_duplicate(member, other) for other in flattened):
                _emit_warning(f"Duplicate transformer {member!r} in stack; will run multiple times.")

        flattened.extend(members)

    if not flattened:
        raise ValueError(_EMPTY_CHAIN)  # An empty stack is a silent no-op.

    return (*flattened,)


def _is_duplicate(transformer: _Transformer[_IdType], other: _Transformer[_IdType]) -> bool:
    if transformer is other:
        return True

    # Before `__eq__`: a repeat is the same registration, which two types can never be.
    if type(transformer) is not type(other):
        return False

    try:
        return bool(transformer == other)
    except Exception:
        # Implementations are not required to implement __eq__, and those that do may reject foreign types or return
        # something that isn't a bool (e.g. an array).
        return False


def as_transformer(value: _Transformer[_IdType] | _abc.Sequence[_Transformer[_IdType]]) -> _Transformer[_IdType]:
    """Normalize a single transformer or a chain of them into one transformer.

    Args:
        value: A :class:`~id_translation.transform.types.Transformer`, or a sequence of them to chain in order.

    Returns:
        `value` itself when it is a single transformer or a one-element sequence, otherwise a ``TransformerStack``.

    Raises:
        ValueError: If `value` is an empty sequence.
        TypeError: If `value` is neither a transformer nor a sequence of them, or is a `Transformer` subclass rather
            than an instance of one.
    """
    # Transformer first: an implementation is allowed to be a Sequence too, and must not be read as a chain.
    if _is_transformer(value):
        return value

    # `str` and `bytes` are Sequences, so an accidental string would otherwise chain its elements.
    if isinstance(value, _abc.Sequence) and not isinstance(value, str | bytes | bytearray):
        for i, element in enumerate(value):
            if not _is_transformer(element):
                raise _not_a_transformer(f"Element {i} of the transformer chain", element)

        # An empty sequence falls through to the stack, which owns the emptiness rule.
        return value[0] if len(value) == 1 else TransformerStack(*value)

    raise _not_a_transformer("Transformer", value)


def _is_transformer(value: object) -> _t.TypeGuard[_Transformer[_t.Any]]:
    return not isinstance(value, type) and isinstance(value, _Transformer)


def _not_a_transformer(what: str, value: object) -> TypeError:
    if isinstance(value, type):
        exc = TypeError(f"{what} must be an instance, got the {value.__name__} class.")
        exc.add_note(f"Hint: Pass `{value.__name__}()`.")
        return exc
    return TypeError(f"{what} must implement the Transformer protocol, got {type(value).__name__}.")
