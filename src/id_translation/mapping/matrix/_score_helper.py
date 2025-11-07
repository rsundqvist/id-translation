import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, Self

from ... import logging as _logging
from .. import Cardinality, DirectionalMapping
from ..exceptions import AmbiguousScoreError
from ..types import CandidateType, ValueType
from ._score_matrix import ScoreMatrix

inf = float("inf")


@dataclass(frozen=True)
class Record(Generic[ValueType, CandidateType]):
    """Data concerning a match."""

    value: ValueType
    """A hashable :class:`value <.ValueType>`."""
    candidate: CandidateType
    """A hashable :class:`candidate <.CandidateType>`."""
    score: float
    """Likeness score computed by some scoring function."""

    def __lt__(self, other: Self) -> bool:
        return self.score < other.score

    def __str__(self) -> str:
        return f"{self.value!r} -> '{self.candidate}'; score={self.score:.3f}"


@dataclass(frozen=True)
class Reject(Generic[ValueType, CandidateType]):
    """Data concerning the rejection of a match."""

    record: Record[ValueType, CandidateType]
    """A :class:`Record` to describe."""
    superseding_value: Record[ValueType, CandidateType] | None = None
    """A :class:`Record` that prevents matching of the current value."""
    superseding_candidate: Record[ValueType, CandidateType] | None = None
    """A :class:`Record` that prevents matching of the current candidate."""

    def explain(self, min_score: float, full: bool = False) -> str:
        """Create a string which explains the rejection.

        Args:
            min_score: Minimum score to accept a match.
            full: If ``True`` show full information about superseding matches.

        Returns:
            An explanatory string.
        """
        if self.record.score == -inf:
            if self.superseding_value and self.superseding_value.score == inf:
                extra = f": {self.superseding_value}" if full else ""
                why = f" (superseded by short-circuit or override{extra})"
            elif self.superseding_candidate and self.superseding_candidate.score == inf:
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


class ScoreHelper(Generic[ValueType, CandidateType]):
    """High-level selection operations.

    Args:
        matrix: A :class:`.ScoreMatrix` instance.
        min_score: Minimum score to make a `value -> candidate` match.
        logger: Explicit ``Logger`` instance to use.
        task_id: Used for logging.
    """

    def __init__(
        self,
        matrix: ScoreMatrix[ValueType, CandidateType],
        min_score: float,
        logger: logging.Logger | None = None,
        *,
        task_id: int | None = None,
    ) -> None:
        self._min_score = min_score
        self._matrix = matrix
        self._logger = logging.getLogger(__name__) if logger is None else logger
        self._task_id = task_id

    @property
    def logger(self) -> logging.Logger:
        """Return the ``Logger`` that is used by this instance."""
        return self._logger

    def to_directional_mapping(
        self,
        cardinality: Cardinality | None = None,
    ) -> DirectionalMapping[ValueType, CandidateType]:
        """Create a ``DirectionalMapping`` with a given target ``Cardinality``.

        Args:
            cardinality: Explicit cardinality to set, see :attr:`~.DirectionalMapping.cardinality`. If ``None``, use the
                actual cardinality when selecting all matches with scores :attr:`at or above <above>` the minimum.

        Returns:
            A ``DirectionalMapping``.
        """
        matches: list[Record[ValueType, CandidateType]]
        rejections: list[Reject[ValueType, CandidateType]]
        matches, rejections = self._match(cardinality)
        min_score = self._min_score

        logger = self.logger
        logging_disabled = not (_logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG))

        left_to_right: dict[ValueType, list[CandidateType]] = {}
        for record in list(matches):
            left_to_right.setdefault(record.value, []).append(record.candidate)

            if logging_disabled:
                continue

            supersedes: list[Reject[ValueType, CandidateType]] = []
            if rejections:
                supersedes.extend(
                    rr
                    for rr in rejections
                    if record in (rr.superseding_value, rr.superseding_candidate) and rr.record.score >= min_score
                )

            reason = "(short-circuit or override)" if record.score == inf else f">= {min_score}"
            msg = f"Accepted: {record} {reason}."

            if supersedes:
                s = "\n".join("    " + rr.explain(min_score) for rr in supersedes)
                msg += f" This match supersedes {len(supersedes)} other matches:\n{s}"
            logger.debug(msg, extra={"task_id": self._task_id})

        values = set(self._matrix.values)
        if rejections and not logging_disabled:
            unmapped_values = values.difference(left_to_right)
            for value in unmapped_values:
                value_reasons = "\n".join(
                    "    " + reject.explain(min_score, full=True)
                    for reject in rejections
                    if reject.record.value == value
                )
                logger.debug(
                    f"Could not map {value=}. Rejected matches:\n{value_reasons}",
                    extra={"task_id": self._task_id},
                )

        return DirectionalMapping(
            cardinality=cardinality,
            left_to_right={value: tuple(left_to_right[value]) for value in values.intersection(left_to_right)},
            _verify=False,
        )

    def _match(
        self,
        cardinality: Cardinality | None = None,
    ) -> tuple[list[Record[ValueType, CandidateType]], list[Reject[ValueType, CandidateType]]]:
        rejections: list[Reject[ValueType, CandidateType]] | None = None
        records: list[Record[ValueType, CandidateType]] = self.above()

        if _logging.ENABLE_VERBOSE_LOGGING and self.logger.isEnabledFor(logging.DEBUG):
            rejections = []
            records.extend(self.below())

        records.sort(reverse=True)

        if cardinality is Cardinality.OneToOne:
            matches = self._select_one_to_one(records, rejections)
        elif cardinality is Cardinality.OneToMany:
            matches = self._select_one_to_many(records, rejections)
        elif cardinality is Cardinality.ManyToOne:
            matches = self._select_many_to_one(records, rejections)
        else:
            matches = self._select_many_to_many(records, rejections)

        return list(matches), rejections or []

    def above(self) -> list[Record[ValueType, CandidateType]]:
        """Records with scores `above` the threshold."""
        d = self._matrix.to_dict()
        d = {k: v for k, v in d.items() if v >= self._min_score}
        return self._from_dict(d)

    def below(self) -> list[Record[ValueType, CandidateType]]:
        """Records with scores `below` the threshold."""
        d = self._matrix.to_dict()
        d = {k: v for k, v in d.items() if v < self._min_score}
        return self._from_dict(d)

    @classmethod
    def _from_dict(cls, d: dict[tuple[ValueType, CandidateType], float]) -> list[Record[ValueType, CandidateType]]:
        return [Record(value, candidate, score) for (value, candidate), score in d.items()]

    def _raise_if_ambiguous(
        self,
        record: Record,  # type: ignore[type-arg]
        matches: dict,  # type: ignore[type-arg]
        kind: str,
        cardinality: Cardinality,
    ) -> None:
        if record.score == inf:
            # Overrides are allowed to be infinite; the first one will be chosen. It's up to the user to manage them.
            return

        key = record.value if kind == "value" else record.candidate
        if key not in matches:
            return

        old_match = matches[key]
        if old_match.score == inf:
            # Overrides are allowed to be infinite; the first one will be chosen. It's up to the user to manage them.
            return

        if record.score == old_match.score:
            raise AmbiguousScoreError(
                kind=kind,
                key=key,
                match0=record,
                match1=old_match,
                cardinality=cardinality.name,
                scores=self._matrix.to_string(),
            )

    def _select_one_to_one(
        self,
        records: Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> Iterable[Record[ValueType, CandidateType]]:
        mvs: dict[ValueType, Record[ValueType, CandidateType]] = {}
        mcs: dict[CandidateType, Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mcs, "candidate", Cardinality.OneToOne)
            self._raise_if_ambiguous(record, mvs, "value", Cardinality.OneToOne)

            if record.score < self._min_score or record.value in mvs or record.candidate in mcs:
                if rejections is not None:
                    rejections.append(
                        Reject(
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
        records: Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> Iterable[Record[ValueType, CandidateType]]:
        mcs: dict[CandidateType, Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mcs, "candidate", Cardinality.OneToMany)

            if record.score < self._min_score or record.candidate in mcs:
                if rejections is not None:
                    rejections.append(Reject(record, superseding_candidate=mcs.get(record.candidate)))
                continue
            mcs[record.candidate] = record
            yield record

    def _select_many_to_one(
        self,
        records: Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> Iterable[Record[ValueType, CandidateType]]:
        mvs: dict[ValueType, Record[ValueType, CandidateType]] = {}

        for record in records:
            self._raise_if_ambiguous(record, mvs, "value", cardinality=Cardinality.ManyToOne)

            if record.score < self._min_score or record.value in mvs:
                if rejections is not None:
                    rejections.append(Reject(record, superseding_value=mvs.get(record.value)))
                continue
            mvs[record.value] = record
            yield record

    def _select_many_to_many(
        self,
        records: Iterable[Record[ValueType, CandidateType]],
        rejections: list[Reject[ValueType, CandidateType]] | None = None,
    ) -> Iterable[Record[ValueType, CandidateType]]:
        for record in records:
            if record.score < self._min_score:
                if rejections is not None:
                    rejections.append(Reject(record))
                continue
            yield record
