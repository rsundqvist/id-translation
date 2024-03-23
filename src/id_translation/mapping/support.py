"""Functions and classes used by the :class:`.Mapper` for handling score matrices.

.. warning::

   This module is considered an implementation detail, and may change without notice.
"""

import logging
import warnings
from collections import defaultdict as _defaultdict
from collections.abc import Iterable as _Iterable
from contextlib import contextmanager as _contextmanager
from dataclasses import dataclass as _dataclass
from typing import Generic as _Generic
from typing import Optional

import numpy as np
import pandas as pd

from ._cardinality import Cardinality as _Cardinality
from ._directional_mapping import DirectionalMapping as _DirectionalMapping
from .exceptions import AmbiguousScoreError as _AmbiguousScoreError
from .types import CandidateType, ValueType

warnings.warn(
    "This module is considered an implementation detail, and may change without notice.", UserWarning, stacklevel=2
)
_MATCH_SCORES_LOGGER = logging.getLogger(__package__).getChild("MatchScores")


@_contextmanager
def enable_verbose_debug_messages():  # type: ignore  # noqa
    """Temporarily enable verbose DEBUG-level logger messages.

    Returns a context manager. Calling the function without the ``with`` statement does nothing.

    >>> from id_translation.mapping import Mapper, support
    >>> with support.enable_verbose_debug_messages():
    ...     Mapper().apply("ab", candidates="abc")
    """
    from . import _VERBOSE_LOGGER, _mapper, filter_functions, heuristic_functions, score_functions

    before = filter_functions.VERBOSE, heuristic_functions.VERBOSE, score_functions.VERBOSE, _VERBOSE_LOGGER.disabled
    enable = (True, True, True, False)
    try:
        (
            filter_functions.VERBOSE,
            heuristic_functions.VERBOSE,
            score_functions.VERBOSE,
            _VERBOSE_LOGGER.disabled,
        ) = enable
        _mapper.FORCE_VERBOSE = True
        yield
    finally:
        (
            filter_functions.VERBOSE,
            heuristic_functions.VERBOSE,
            score_functions.VERBOSE,
            _VERBOSE_LOGGER.disabled,
        ) = before
        _mapper.FORCE_VERBOSE = False


class MatchScores:
    """High-level selection operations.

    Args:
        scores: A score matrix, where ``scores.index`` are values and ``score.columns`` are treated as the candidates.
        min_score: Minimum score to consider make a `value -> candidate` match.
        logger: Explicit ``Logger`` instance to use.
    """

    def __init__(self, scores: pd.DataFrame, min_score: float, logger: logging.Logger | None = None) -> None:
        self._min_score = min_score
        self._matrix = scores
        self._logger = _MATCH_SCORES_LOGGER if logger is None else logger

    @property
    def logger(self) -> logging.Logger:
        """Return the ``Logger`` that is used by this instance."""
        return self._logger

    def to_directional_mapping(self, cardinality: _Cardinality = None) -> _DirectionalMapping[ValueType, CandidateType]:
        """Create a ``DirectionalMapping`` with a given target ``Cardinality``.

        Args:
            cardinality: Explicit cardinality to set, see :attr:`~.DirectionalMapping.cardinality`. If ``None``, use the
                actual cardinality when selecting all matches with scores :attr:`get_above` the minimum.

        Returns:
            A ``DirectionalMapping``.
        """
        matches: list[MatchScores.Record[ValueType, CandidateType]]
        rejections: list[MatchScores.Reject[ValueType, CandidateType]]
        matches, rejections = self._match(cardinality)

        left_to_right = _defaultdict(list)
        for record in list(matches):
            supersedes: list[MatchScores.Reject[ValueType, CandidateType]] = []
            if self.logger.isEnabledFor(logging.DEBUG) and rejections:
                for rr in rejections:
                    if record in (rr.superseding_value, rr.superseding_candidate):
                        supersedes.append(rr)  # noqa: PERF401

            if self.logger.isEnabledFor(logging.DEBUG):
                reason = "(short-circuit or override)" if record.score == np.inf else f">= {self._min_score}"
                self.logger.debug(f"Accepted: {record} {reason}.")

            if supersedes:
                s = "\n".join("    " + rr.explain(self._min_score) for rr in supersedes)
                self.logger.debug(f"This match supersedes {len(supersedes)} other matches:\n{s}")

            left_to_right[record.value].append(record.candidate)

        if rejections and self.logger.isEnabledFor(logging.DEBUG):
            unmapped_values = set(self._matrix.index.difference(left_to_right))
            for value in unmapped_values:
                lst = []
                for rr in filter(lambda r: r.record.value == value, rejections):
                    lst.append(f"    {rr.explain(self._min_score, full=True)}")  # noqa: PERF401
                value_reasons = "\n".join(lst)
                self.logger.debug(f"Could not map {value=}:\n{value_reasons}")

        return _DirectionalMapping(
            cardinality=cardinality,
            left_to_right={
                value: tuple(left_to_right[value]) for value in self._matrix.index if value in left_to_right
            },
            _verify=False,
        )

    def _match(
        self, cardinality: _Cardinality = None
    ) -> tuple[list["MatchScores.Record[ValueType, CandidateType]"], list["Reject[ValueType, CandidateType]"]]:
        rejections: list[MatchScores.Reject[ValueType, CandidateType]] | None = None
        records: list["MatchScores.Record[ValueType, CandidateType]"] = self.get_above()

        if self.logger.isEnabledFor(logging.DEBUG):
            rejections = []
            records.extend(self.get_below())

        if cardinality is _Cardinality.OneToOne:
            matches = self._select_one_to_one(records, rejections)
        elif cardinality is _Cardinality.OneToMany:
            matches = self._select_one_to_many(records, rejections)
        elif cardinality is _Cardinality.ManyToOne:
            matches = self._select_many_to_one(records, rejections)
        else:
            matches = self._select_many_to_many(records, rejections)

        return list(matches), rejections or []

    def _get_sorted(self) -> pd.Series:
        sorted_scores: pd.Series = self._matrix.stack()  # noqa: PD013
        sorted_scores = sorted_scores.sort_values(ascending=False, kind="stable")
        return sorted_scores

    def get_above(self) -> list["MatchScores.Record[ValueType, CandidateType]"]:
        """Get all records with scores `above` the threshold."""
        s = self._get_sorted()
        return self._from_series(s[s >= self._min_score])

    def get_below(self) -> list["MatchScores.Record[ValueType, CandidateType]"]:
        """Get all records with scores `below` the threshold."""
        s = self._get_sorted()
        return self._from_series(s[s < self._min_score])

    @_dataclass(frozen=True)
    class Record(_Generic[ValueType, CandidateType]):
        """Data concerning a match."""

        value: ValueType
        """A hashable value."""
        candidate: CandidateType
        """A hashable candidate."""
        score: float
        """Likeness score computed by some scoring function."""

        def __str__(self) -> str:
            return f"{self.value!r} -> '{self.candidate}'; score={self.score:.3f}"

    @classmethod
    def _from_series(cls, s: pd.Series) -> list[Record[ValueType, CandidateType]]:
        return [MatchScores.Record(value, candidate, score) for (value, candidate), score in s.items()]

    @_dataclass(frozen=True)
    class Reject(_Generic[ValueType, CandidateType]):
        """Data concerning the rejection of a match."""

        record: "MatchScores.Record[ValueType, CandidateType]"
        superseding_value: Optional["MatchScores.Record[ValueType, CandidateType]"] = None
        superseding_candidate: Optional["MatchScores.Record[ValueType, CandidateType]"] = None

        def explain(self, min_score: float, full: bool = False) -> str:
            """Create a string which explains the rejection.

            Args:
                min_score: Minimum score to accept a match.
                full: If ``True`` show full information about superseding matches.

            Returns:
                An explanatory string.
            """
            if self.record.score == -np.inf:
                if self.superseding_value and self.superseding_value.score == np.inf:
                    extra = f": {self.superseding_value}" if full else ""
                    why = f" (superseded by short-circuit or override{extra})"
                elif self.superseding_candidate and self.superseding_candidate.score == np.inf:
                    extra = f": {self.superseding_candidate}" if full else ""
                    why = f" (superseded by short-circuit or override{extra}"
                else:
                    why = " (filtered)"
            elif self.record.score < min_score:
                why = f" < {min_score} (below threshold)"
            else:
                ands = []
                if self.superseding_value:
                    extra = f": {self.superseding_value}" if full else ""
                    ands.append(f"value={self.superseding_value.value!r}{extra}")
                if self.superseding_candidate:
                    extra = f": {self.superseding_candidate}" if full else ""
                    ands.append(f"candidate={self.superseding_candidate.candidate!r}{extra}")
                why = f" (superseded on {' and '.join(ands)})"

            return f"{self.record}{why}."

    def _raise_if_ambiguous(
        self,
        record: Record,  # type: ignore[type-arg]
        matches: dict,  # type: ignore[type-arg]
        kind: str,
        cardinality: _Cardinality,
    ) -> None:
        if record.score == np.inf:
            # Overrides are allowed to be infinite; the first one will be chosen. It's up to the user to manage them.
            return

        key = record.value if kind == "value" else record.candidate
        if key not in matches:
            return

        old_match = matches[key]
        if record.score == old_match.score:
            raise _AmbiguousScoreError(
                kind=kind,
                key=key,
                match0=record,
                match1=old_match,
                cardinality=cardinality.name,
                scores=self._matrix.to_string(),
            )

    def _select_one_to_one(
        self,
        records: _Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> _Iterable[Record[ValueType, CandidateType]]:
        mvs: dict[ValueType, MatchScores.Record[ValueType, CandidateType]] = {}
        mcs: dict[CandidateType, MatchScores.Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mcs, "candidate", _Cardinality.OneToOne)
            self._raise_if_ambiguous(record, mvs, "value", _Cardinality.OneToOne)

            if record.score < self._min_score or record.value in mvs or record.candidate in mcs:
                if rejections is not None:
                    rejections.append(
                        MatchScores.Reject(
                            record,
                            superseding_value=mvs.get(record.value),
                            superseding_candidate=mcs.get(record.candidate),
                        )
                    )
                continue
            mvs[record.value] = record
            mcs[record.candidate] = record
            yield record

    def _select_one_to_many(
        self,
        records: _Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> _Iterable[Record[ValueType, CandidateType]]:
        mcs: dict[CandidateType, MatchScores.Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mcs, "candidate", _Cardinality.OneToMany)

            if record.score < self._min_score or record.candidate in mcs:
                if rejections is not None:
                    rejections.append(MatchScores.Reject(record, superseding_candidate=mcs.get(record.candidate)))
                continue
            mcs[record.candidate] = record
            yield record

    def _select_many_to_one(
        self,
        records: _Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> _Iterable[Record[ValueType, CandidateType]]:
        mvs: dict[ValueType, MatchScores.Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mvs, "value", cardinality=_Cardinality.ManyToOne)

            if record.score < self._min_score or record.value in mvs:
                if rejections is not None:
                    rejections.append(MatchScores.Reject(record, superseding_value=mvs.get(record.value)))
                continue
            mvs[record.value] = record
            yield record

    def _select_many_to_many(
        self,
        records: _Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> _Iterable[Record[ValueType, CandidateType]]:
        for record in records:
            if record.score < self._min_score:
                if rejections is not None:
                    rejections.append(MatchScores.Reject(record))
                continue
            yield record
