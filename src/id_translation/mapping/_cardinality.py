from enum import Enum
from typing import Union


class Cardinality(Enum):
    """Enumeration type for cardinality relationships.

    Cardinalities are comparable using numerical operators, and can be thought of as comparing "preciseness". The less
    ambiguity there is for a given cardinality, the smaller it is in comparison to the others. The hierarchy is given by
    ``1:1 < 1:N = N:1 < M:N``. Note that ``1:N`` and ``N:1`` are considered equally precise.

    Examples:
        Comparing cardinalities

        >>> from id_translation.mapping import Cardinality
        >>> Cardinality.ManyToOne
        <Cardinality.ManyToOne: 'N:1'>
        >>> Cardinality.OneToOne
        <Cardinality.OneToOne: '1:1'>
        >>> Cardinality.ManyToOne < Cardinality.OneToOne
        False
    """

    _ignore_ = ["ParseType"]  # noqa:  RUF012

    ParseType = Union[str, "Cardinality"]  # Type checking
    """Types that may be interpreted as a ``Cardinality``."""

    OneToOne = "1:1"
    """One-to-one relationship."""
    OneToMany = "1:N"
    """One-to-many relationship."""
    ManyToOne = "N:1"
    """Many-to-one relationship."""
    ManyToMany = "M:N"
    """Many-to-many relationship."""

    @property
    def many_left(self) -> bool:
        """Many-relationship on the left, ``True`` for ``N:1`` and ``M:N``."""
        return self in {Cardinality.ManyToMany, Cardinality.ManyToOne}

    @property
    def many_right(self) -> bool:
        """Many-relationship on the right, ``True`` for ``1:N`` and ``M:N``."""
        return self in {Cardinality.ManyToMany, Cardinality.OneToMany}

    @property
    def one_left(self) -> bool:
        """One-relationship on the left, ``True`` for ``1:1`` and ``1:N``."""
        return not self.many_left

    @property
    def one_right(self) -> bool:
        """One-relationship on the right, ``True`` for ``1:1`` and ``N:1``."""
        return not self.many_right

    @property
    def inverse(self) -> "Cardinality":
        """Inverse cardinality. For symmetric cardinalities, ``self.inverse == self``.

        Returns:
            Inverse cardinality.

        See Also:
            :attr:`symmetric`
        """
        if self == Cardinality.OneToMany:
            return Cardinality.ManyToOne
        if self == Cardinality.ManyToOne:
            return Cardinality.OneToMany

        return self

    @property
    def symmetric(self) -> bool:
        """Symmetry flag. For symmetric cardinalities, ``self.inverse == self``.

        Returns:
            Symmetry flag.

        See Also:
            :attr:`inverse`
        """
        return self in {Cardinality.OneToOne, Cardinality.ManyToMany}

    def __ge__(self, other: "Cardinality") -> bool:
        """Equivalent to :meth:`set.issuperset`."""
        return _is_superset(self, other)

    def __lt__(self, other: "Cardinality") -> bool:
        return not self >= other

    @classmethod
    def from_counts(cls, left_count: int, right_count: int) -> "Cardinality":
        """Derive a `Cardinality` from counts.

        Args:
            left_count: Number of elements on the left-hand side.
            right_count: Number of elements on the right-hand side.

        Returns:
            A :class:`Cardinality`.

        Raises:
            ValueError: For counts < 1.
        """
        return _from_counts(left_count, right_count)

    @classmethod
    def parse(cls, arg: ParseType, strict: bool = False) -> "Cardinality":
        """Convert to cardinality.

        Args:
            arg: Argument to parse.
            strict: If ``True``, `arg` must match exactly when it is given as a string.

        Returns:
            A :class:`Cardinality`.

        Raises:
            ValueError: If the argument could not be converted.
        """
        return arg if isinstance(arg, Cardinality) else _from_generous_string(arg, strict)


Cardinality.ParseType = Union[str, Cardinality]  # type: ignore[assignment]


def _parsing_failure_message(arg: str, strict: bool) -> str:
    options = tuple([c.value for c in Cardinality])
    alternatively = tuple([c.name for c in Cardinality])
    strict_hint = "."
    if strict:
        try:
            strict = False
            Cardinality.parse(arg, strict=strict)
            strict_hint = f". Hint: set {strict=} to allow this input."
        except ValueError:
            pass
    return f"Could not convert {arg=} to Cardinality{strict_hint} Correct input {options=} or {alternatively!r}"


_MATRIX = (
    (Cardinality.ManyToMany, Cardinality.ManyToOne),
    (Cardinality.OneToMany, Cardinality.OneToOne),
)


def _is_superset(c0: Cardinality, c1: Cardinality) -> bool:
    if c0 == c1:
        return True

    c0_i, c0_j = _pos(c0)
    c1_i, c1_j = _pos(c1)
    return c0_i <= c1_i and c0_j <= c1_j


def _pos(cardinality: Cardinality) -> tuple[int, int]:
    for i in range(2):
        for j in range(2):
            if _MATRIX[i][j] == cardinality:
                return i, j
    raise AssertionError("This should be impossible.")


def _from_counts(left_count: int, right_count: int) -> Cardinality:
    if left_count < 1:
        raise ValueError(f"{left_count=} < 1")
    if right_count < 1:
        raise ValueError(f"{right_count=} < 1")

    one_left = left_count == 1
    one_right = right_count == 1

    return _MATRIX[int(one_left)][int(one_right)]


def _from_generous_string(s: str, strict: bool) -> Cardinality:
    if not strict:
        s = s.strip().upper().replace("-", ":", 1).replace("*", "N", 2)
        if s == "N:N":
            s = "M:N"
    for c in Cardinality:
        if s in {c.value, c.name}:
            return c
    raise ValueError(_parsing_failure_message(s, strict))
