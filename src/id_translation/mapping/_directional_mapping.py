from collections.abc import Hashable, Iterable, Mapping
from typing import Any, Generic, TypeVar

from rics.misc import tname

from ._cardinality import Cardinality
from .exceptions import CardinalityError
from .types import HL, HR, LeftToRight, RightToLeft

HAnySide = TypeVar("HAnySide", bound=Hashable)
MatchTupleAnySide = TypeVar("MatchTupleAnySide", bound=Hashable)  # TODO: Higher-Kinded TypeVars


class DirectionalMapping(Generic[HL, HR]):
    """A two-way mapping between hashable elements.

    Args:
        cardinality: Explicit cardinality. Derive if ``None``.
        left_to_right: A left-to-right mapping of elements.
        right_to_left: A right-to-left mapping of elements.
        _verify: If ``False``, input checks are disabled. Intended for internal use.

    Raises:
        ValueError: If both of `left_to_right` and `right_to_left` are ``None``.
        ValueError: If verification of two-sided input fails, and ``verify=True``.
        CardinalityError: If explicit `cardinality` < :attr:`cardinality`, and ``verify=True``.
    """

    def __init__(
        self,
        cardinality: Cardinality.ParseType = None,
        left_to_right: Mapping[HL, Iterable[HR]] | None = None,
        right_to_left: Mapping[HR, Iterable[HL]] | None = None,
        _verify: bool = True,
    ) -> None:
        self._left_to_right: dict[HL, tuple[HR, ...]] = self._to_other(left_to_right, right_to_left)
        self._right_to_left: dict[HR, tuple[HL, ...]] = self._to_other(right_to_left, left_to_right)

        if left_to_right is not None and right_to_left is not None and _verify:
            self._verify(expected=DirectionalMapping(cardinality, left_to_right=left_to_right, _verify=False))

        self._cardinality = self._handle_cardinality(cardinality, self._left_to_right, self._right_to_left, _verify)

    @property
    def cardinality(self) -> Cardinality:
        """Cardinality with which this mapping was created.

        Returns:
            Cardinality with which this mapping was created.
        """
        return self._cardinality

    @property
    def left(self) -> tuple[HL, ...]:
        """Left-side elements in the mapping."""
        return tuple(self._left_to_right)

    @property
    def right(self) -> tuple[HR, ...]:
        """Right-side elements in the mapping."""
        return tuple(self._right_to_left)

    @property
    def left_to_right(self) -> LeftToRight[HL, HR]:
        """Left-to-right element mappings."""
        return self._left_to_right

    @property
    def right_to_left(self) -> RightToLeft[HR, HL]:
        """Right-to-left element mappings."""
        return self._right_to_left

    @property
    def reverse(self) -> "DirectionalMapping[HR, HL]":
        """Reverse the mapping by swapping the sides.

        Returns:
            A copy with data identical to the calling instance, but with sides inversed compared to the caller.
        """
        return DirectionalMapping(
            self.cardinality.inverse,
            left_to_right=self._right_to_left.copy(),
            right_to_left=self._left_to_right.copy(),
            _verify=False,
        )

    def flatten(self) -> dict[HL, HR]:
        """Return a flattened version of self as a dict.

        Returns:
            A dict ``{left: right}``.

        Raises:
            CardinalityError: If cardinality is not :attr:`~.Cardinality.OneToOne` or :attr:`~.Cardinality.ManyToOne`.
        """
        if not self._cardinality.one_right:  # pragma: no cover
            raise CardinalityError(f"Must have one of {(Cardinality.OneToOne, Cardinality.ManyToOne)} to flatten.")

        return {left: right[0] for left, right in self._left_to_right.items()}

    def select_left(self, elements: Iterable[HL], exclude: bool = False) -> "DirectionalMapping[HL, HR]":
        """Perform a selection on left-side elements.

        Args:
            elements: Elements to select.
            exclude: If ``True``, return everything **except** the given elements.

        Returns:
            A new Mapping for the selection.

        Raises:
            KeyError: If any of the chosen elements do not exist and ``exclude=False``.
        """
        return DirectionalMapping(None, left_to_right=_select(elements, self._left_to_right, exclude))

    def select_right(self, elements: Iterable[HR], exclude: bool = False) -> "DirectionalMapping[HL, HR]":
        """Perform a selection on right-side elements.

        Args:
            elements: Elements to select.
            exclude: If ``True``, return everything **except** the given elements.

        Returns:
            A new instance for the selection.

        Raises:
            KeyError: If any of the chosen elements do not exist and ``exclude=False``.
        """
        return DirectionalMapping(None, right_to_left=_select(elements, self._right_to_left, exclude))

    @classmethod
    def _to_other(
        cls,
        primary_side: Mapping[Any, Iterable[Any]] | None = None,
        backup_side: Mapping[Any, Iterable[Any]] | None = None,
    ) -> dict[Any, Any]:
        if primary_side is not None:
            return primary_side  # type: ignore[return-value]

        if backup_side is None:
            raise ValueError("At least one side must be given")

        from collections import defaultdict

        other_side = defaultdict(list)
        for k, matches_for_k in backup_side.items():
            for m in matches_for_k:
                other_side[m].append(k)
        return {k: tuple(set(m)) for k, m in other_side.items()}

    def _verify(self, expected: "DirectionalMapping[HL, HR]") -> None:
        self._verify_side(self.left, expected.left, "Left")
        self._verify_side(self.right, expected.right, "Right")

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, DirectionalMapping):
            return False

        return (
            self._left_to_right == other._left_to_right
            and self._right_to_left == other._right_to_left
            and self._cardinality == other._cardinality
        )

    def __repr__(self) -> str:
        n_left = len(self._left_to_right)
        n_right = len(self._right_to_left)
        return f"{tname(self)}({n_left} left | {n_right} right, type={self.cardinality.name})"

    def __bool__(self) -> bool:
        return bool(self._left_to_right or self._right_to_left)

    @classmethod
    def _handle_cardinality(
        cls,
        expected: Cardinality.ParseType | None,
        left: LeftToRight[HL, HR],
        right: RightToLeft[HR, HL],
        verify: bool,
    ) -> Cardinality:
        if not (left and right):
            if expected is None:
                return Cardinality.ManyToMany
            else:
                return Cardinality.parse(expected)

        actual = Cardinality.from_counts(
            left_count=max(map(len, right.values())), right_count=max(map(len, left.values()))
        )

        if expected is None:
            return actual
        else:
            expected = Cardinality.parse(expected)

        if verify and actual > expected:
            raise CardinalityError(
                f"Cannot cast explicit given type {expected} to actual type {actual} " f"for ({left=} | {right=})",
            )

        return expected

    @classmethod
    def _verify_side(cls, actual: MatchTupleAnySide, expected: MatchTupleAnySide, name: str) -> None:
        if actual != expected:
            raise ValueError(f"{name}-side mismatch: Got {actual} but expected {expected}.")


def _select(elements: Iterable[HAnySide], items: dict[HL, tuple[HR, ...]], exclude: bool) -> dict[HL, tuple[HR, ...]]:
    if not exclude:
        missing_elements = set(elements).difference(items)
        if missing_elements:
            raise KeyError(f"Unknown keys {missing_elements} in {items}.")

    s = set(elements)
    chosen_elements = filter(lambda e: e not in s, items) if exclude else filter(s.__contains__, items)
    return {e: items[e] for e in chosen_elements}
