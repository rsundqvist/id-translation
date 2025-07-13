from collections.abc import Hashable, Iterable
from math import isfinite
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ..types import CandidateType, ValueType

T = TypeVar("T", bound=Hashable)


if TYPE_CHECKING:
    import pandas

inf = float("inf")


class ScoreMatrix(Generic[ValueType, CandidateType]):
    """A matrix of match scores.

    Args:
        values: Iterable of elements to match to candidates.
        candidates: Iterable of candidates to match with `value`. Duplicate elements will be discarded.
        grid: Initial score matrix. Default is to fill with ``-inf``.

    Raises:
        ValueError: If a bad `grid` is given.
    """

    def __init__(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        *,
        grid: list[list[float]] | None = None,
    ) -> None:
        self._values = _deduplicate(values)
        self._candidates = _deduplicate(candidates)

        if grid is None:
            grid = self._new_grid(-inf)
        else:
            _verify_user_grid(grid, self._values, len(self._candidates))

        self._grid = grid

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._values!r}, {self._candidates!r}, grid={self._grid})"

    def _new_grid(self, value: float) -> list[list[float]]:
        row = [value] * len(self._candidates)
        return [[*row] for _ in range(len(self._values))]

    def __setitem__(self, index: tuple[ValueType | slice, CandidateType | slice], value: float) -> None:
        i, j = index

        if __debug__:
            if isinstance(i, slice) and i != slice(None, None, None):
                msg = f"slice {index=} not supported"
                raise NotImplementedError(msg)
            if isinstance(j, slice) and j != slice(None, None, None):
                msg = f"slice {index=} not supported"
                raise NotImplementedError(msg)

        if isinstance(i, slice):
            if isinstance(j, slice):
                # All rows and columns.
                self._grid = self._new_grid(value)
            else:
                gj = self._candidate_index(j)
                for row in self._grid:
                    row[gj] = value
        else:
            gi = self._value_index(i)
            if isinstance(j, slice):
                self._grid[gi] = [value for _ in range(len(self._candidates))]
            else:
                gj = self._candidate_index(j)
                self._grid[gi][gj] = value

    def _value_index(self, value: ValueType) -> int:
        try:
            return self._values.index(value)
        except ValueError:
            pass

        # Add missing element.
        self._values.append(value)
        self._grid.append([-inf for _ in range(len(self._candidates))])
        return self._values.index(value)

    def _candidate_index(self, candidate: CandidateType) -> int:
        try:
            return self._candidates.index(candidate)
        except ValueError:
            pass

        # Add missing element.
        self._candidates.append(candidate)
        for row in self._grid:
            row.append(-inf)
        return self._candidates.index(candidate)

    @property
    def size(self) -> int:
        """Total number of elements."""
        return len(self._values) * len(self._candidates)

    @property
    def values(self) -> list[ValueType]:
        """Unique values in order."""
        return [*self._values]

    @property
    def candidates(self) -> list[CandidateType]:
        """Unique candidates in order."""
        return [*self._candidates]

    def get_finite_values(self) -> set[ValueType]:
        """Compute all finite values."""
        return {value for value, row in zip(self._values, self._grid, strict=True) if all(map(isfinite, row))}

    def to_pandas(self) -> "pandas.DataFrame":
        """Convert to :class:`pandas.DataFrame`."""
        from pandas import DataFrame, Index  # noqa: PLC0415

        return DataFrame(
            self._grid,
            index=Index(self._values, name="values"),
            columns=Index(self._candidates, name="candidates"),
        )

    def to_dict(self) -> dict[tuple[ValueType, CandidateType], float]:
        """Convert to dict ``{(value, candidate): score}``."""
        rv = {}
        for value, row in zip(self._values, self._grid, strict=True):
            for candidate, score in zip(self._candidates, row, strict=True):
                rv[(value, candidate)] = score

        return rv

    def to_string(self, *, decimals: int = 2) -> str:
        """Format score table."""
        try:
            return self.to_pandas().to_string(float_format=f"%.{decimals}f")  # type: ignore[no-any-return]
        except ImportError:
            return self.to_native_string(decimals=decimals)

    def to_native_string(self, *, decimals: int = 2, lines: bool = True) -> str:
        """Format score table without ``pandas``."""
        column_separator = " ┃ " if lines else " "

        header_row = ["v/c"] + [str(c) for c in self._candidates]
        formatted_scores = [[f"{float(s):.{decimals}f}" for s in scores] for scores in self._grid]
        width = max(*map(len, header_row + [str(i) for i in self._values]), *map(len, formatted_scores))

        rows = []
        for value, scores in zip(self._values, formatted_scores, strict=False):
            row = [f"{value:<{width}}"] + [f"{s:>{width}}" for s in scores]
            rows.append(column_separator.join(row))

        column_headers = [f"{h:<{width}}" for h in header_row]
        header = [column_separator.join(column_headers)]
        if lines:
            horizontal_line = ["━" * len(h) for h in column_headers]
            header.append("━╋━".join(horizontal_line))

        return "\n".join(header + rows)


def _deduplicate(items: Iterable[T]) -> list[T]:
    seen = set()
    unique = []
    for item in items:
        if item in seen:
            continue

        seen.add(item)
        unique.append(item)

    return unique


def _verify_user_grid(grid: list[list[float]], values: list[Any], candidates: int) -> None:
    nvalues = len(values)
    if len(grid) != nvalues:
        msg = f"Bad grid: Number of rows {len(grid)} must match the number of values={nvalues}."
        raise ValueError(msg)

    for i, (value, row) in enumerate(zip(values, grid, strict=True)):
        if len(row) != candidates:
            msg = f"Bad grid[{i}] row ({value=}): Number of columns {len(row)} must match the number of {candidates=}."
            raise ValueError(msg)
