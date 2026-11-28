from collections.abc import Hashable, Iterable
from math import isfinite
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .types import CandidateType, ValueType

T = TypeVar("T", bound=Hashable)


if TYPE_CHECKING:
    import pandas

inf = float("inf")


class ScoreMatrix(Generic[ValueType, CandidateType]):
    """A matrix of match scores.

    Args:
        values: Elements to match to candidates. Duplicates are discarded.
        candidates: Candidates for the `values`. Duplicates are discarded.
        grid: Initial scores, one row per unique value and one column per unique candidate. Default is to fill with
            ``-inf``.

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
            grid = [[*row] for row in grid]

        self._grid = grid

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._values!r}, {self._candidates!r}, grid={self._grid})"

    def _new_grid(self, value: float) -> list[list[float]]:
        row = [value] * len(self._candidates)
        return [[*row] for _ in range(len(self._values))]

    def _set(self, value: ValueType, candidate: CandidateType, score: float) -> None:
        # Adds a missing value or candidate: an override may name a candidate outside the matrix.
        self._grid[self._value_index(value)][self._candidate_index(candidate)] = score

    def _set_row(self, value: ValueType, score: float) -> None:
        self._grid[self._value_index(value)] = [score] * len(self._candidates)

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
        """The total number of scores."""
        return len(self._values) * len(self._candidates)

    @property
    def values(self) -> list[ValueType]:
        """A ``list`` of the unique values."""
        return [*self._values]

    @property
    def candidates(self) -> list[CandidateType]:
        """A ``list`` of the unique candidates."""
        return [*self._candidates]

    def _finite_values(self) -> set[ValueType]:
        return {value for value, row in zip(self._values, self._grid, strict=True) if any(map(isfinite, row))}

    def to_pandas(self) -> "pandas.DataFrame":
        """Convert to :class:`pandas.DataFrame`."""
        from pandas import DataFrame, Index  # noqa: PLC0415

        # Tuple labels (e.g. MultiIndex column names) stay labels; a MultiIndex would reject the scalar `name`.
        return DataFrame(
            self._grid,
            index=Index(self._values, name="values", tupleize_cols=False),
            columns=Index(self._candidates, name="candidates", tupleize_cols=False),
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
            return self._to_native_string(decimals=decimals)

    def _to_native_string(self, *, decimals: int = 2, lines: bool = True) -> str:
        column_separator = " ┃ " if lines else " "

        header_row = ["v/c"] + [str(c) for c in self._candidates]
        value_labels = [str(v) for v in self._values]
        formatted_scores = [[f"{float(s):.{decimals}f}" for s in scores] for scores in self._grid]

        all_scores = [s for scores in formatted_scores for s in scores]
        width = max(len(cell) for cell in header_row + value_labels + all_scores)

        rows = []
        for label, scores in zip(value_labels, formatted_scores, strict=False):
            row = [f"{label:<{width}}"] + [f"{s:>{width}}" for s in scores]
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
