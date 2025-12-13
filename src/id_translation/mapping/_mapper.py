import logging
import warnings
from collections.abc import Iterable
from math import isinf
from time import perf_counter
from typing import Any, Generic, Self

from rics.collections.dicts import InheritedKeysDict
from rics.misc import get_by_full_name, tname
from rics.strings import format_perf_counter as fmt_perf
from rics.types import LiteralHelper

from .. import logging as _logging
from . import filter_functions as ff
from . import score_functions as sf
from ._cardinality import Cardinality
from ._directional_mapping import DirectionalMapping
from ._heuristic_score import HeuristicScore
from .exceptions import (
    BadFilterError,
    MappingError,
    UnmappedValuesError,
    UnmappedValuesWarning,
    UserMappingError,
    UserMappingWarning,
)
from .types import (
    CandidateType,
    CardinalityType,
    ContextType,
    FilterFunction,
    OnUnknownUserOverride,
    OnUnmapped,
    ScoreFunction,
    UserOverrideFunction,
    ValueType,
)

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=UserWarning)
    from .matrix import ScoreHelper, ScoreMatrix

inf = float("inf")
FilterFunctionArgItem = tuple[str | FilterFunction[ValueType, CandidateType, ContextType], dict[str, Any]]
FilterFunctionWithKwargs = tuple[FilterFunction[ValueType, CandidateType, ContextType], dict[str, Any]]


class Mapper(Generic[ValueType, CandidateType, ContextType]):  # noqa: PLW1641
    """Optimal value-candidate matching.

    For an introduction to mapping, see the :ref:`mapping-primer` page.

    Args:
        score_function: A callable which accepts a value `k` and an ordered collection of candidates `c`, returning a
            score ``s_i`` for each candidate `c_i` in `c`. Default: ``s_i = float(k == c_i)``. Higher=better match.
        score_function_kwargs: Keyword arguments for `score_function`.
        filter_functions: Function-kwargs pairs of filters to apply before scoring.
        min_score: Minimum score `s_i`, as given by ``score(k, c_i)``, to consider `k` a match for `c_i`.
        overrides: If a dict, assumed to be 1:1 mappings (`value` to `candidate`) which override the scoring logic. If
            :class:`rics.collections.dicts.InheritedKeysDict`, the context passed to :meth:`apply` is used to retrieve
            specific overrides.
        on_unmapped: Action to take if mapping fails for any values.
        on_unknown_user_override: Action to take if an :attr:`~id_translation.mapping.types.UserOverrideFunction`
            returns an unknown candidate. Unknown candidates, i.e. candidates not in the input `candidates` collection,
            will not be used unless `'allow'` is chosen.
        cardinality: Desired cardinality for mapped values. Derive for each matching if ``None``.
    """

    def __init__(
        self,
        score_function: str | ScoreFunction[ValueType, CandidateType, ContextType] = "disabled",
        score_function_kwargs: dict[str, Any] | None = None,
        filter_functions: Iterable[FilterFunctionArgItem[ValueType, CandidateType, ContextType]] = (),
        min_score: float = 0.90,
        overrides: dict[ValueType, CandidateType]
        | InheritedKeysDict[ContextType, ValueType, CandidateType]
        | None = None,
        on_unmapped: OnUnmapped = "ignore",
        on_unknown_user_override: OnUnknownUserOverride = "raise",
        cardinality: CardinalityType | None = Cardinality.ManyToOne,
    ) -> None:
        if min_score <= 0 or isinf(min_score):
            raise ValueError(f"Got {min_score=}. The score limit should be a finite positive value.")

        self._score = get_by_full_name(score_function, sf) if isinstance(score_function, str) else score_function
        self._score_kwargs = score_function_kwargs or {}
        self._min_score = min_score
        self._overrides: InheritedKeysDict[ContextType, ValueType, CandidateType] | dict[ValueType, CandidateType] = (
            overrides if isinstance(overrides, InheritedKeysDict) else (overrides or {})
        )
        self._on_unmapped = OU_HELPER.check(on_unmapped)
        self._on_unknown_user_override = OUUO_HELPER.check(on_unknown_user_override)
        self._cardinality = None if cardinality is None else Cardinality.parse(cardinality, strict=True)

        self._filters = self._initialize_filter_functions(filter_functions)
        self._logger = logging.getLogger(__package__).getChild("Mapper")  # This will almost always be overwritten

    def apply(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        context: ContextType | None = None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] | None = None,
        *,
        task_id: int | None = None,
        **kwargs: Any,
    ) -> DirectionalMapping[ValueType, CandidateType]:
        """Map values to candidates.

        Args:
            values: Iterable of elements to match to candidates.
            candidates: Iterable of candidates to match with `value`. Duplicate elements will be discarded.
            context: Context in which mapping is being done.
            override_function: A callable that takes inputs ``(value, candidates, context)`` that returns either
                ``None`` (let the regular mapping logic decide) or one of the `candidates`. How non-candidates returned
                is handled is determined by the :attr:`on_unknown_user_override` property.
            task_id: Used for logging.
            **kwargs: Runtime keyword arguments for score and filter functions. May be used to add information which is
                not known when the ``Mapper`` is initialized.

        Returns:
            A :class:`.DirectionalMapping` on the form ``{value: [matched_candidates..]}``. May be turned into a
            plain dict ``{value: candidate}`` by using the :meth:`.DirectionalMapping.flatten` function (only if
            :attr:`.DirectionalMapping.cardinality` is of type :attr:`.Cardinality.one_right`).

        Raises:
            MappingError: If any values failed to match and ``on_unmapped='raise'``.
            BadFilterError: If a filter returns candidates that are not a subset of the original candidates.
            UserMappingError: If `override_function` returns an unknown candidate and
                ``on_unknown_user_override != 'allow'``
            MappingError: If passing ``context=None`` (the default) when using context-sensitive overrides (type
                :class:`rics.collections.dicts.InheritedKeysDict`).
        """
        start = perf_counter()

        logger = self.logger

        candidates = list(candidates)
        values = list(values)
        if not (values and candidates):
            logger.debug(
                "Aborting since values=%r and candidates=%r in context=%r.",
                values,
                candidates,
                context,
                extra={"task_id": task_id},
            )
            return DirectionalMapping(left_to_right={}, _verify=False, cardinality=self.cardinality)

        scores = self.compute_scores(values, candidates, context, override_function, task_id=task_id, **kwargs)

        dm: DirectionalMapping[ValueType, CandidateType] = self.to_directional_mapping(scores, task_id=task_id)

        unmapped = scores.get_finite_values().difference(dm.left)
        if unmapped:
            extra = f" in {context=}" if context else ""
            candidates = set(scores.candidates)  # Includes candidates added by override logic.
            self._report_unmapped(f"Could not map {unmapped}{extra} to any of {candidates=}.", task_id=task_id)

        logger = self.logger
        if _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG):
            cardinality = "automatic" if self.cardinality is None else self.cardinality.name

            l2r = dm.left_to_right
            matches = " Matches:\n" + "\n".join(
                f"    {v!r} -> {repr(l2r[v]) if v in l2r else '<no matches>'}" for v in values
            )

            logger.debug(
                f"Mapping with {cardinality=} completed for {values}x{candidates} in {fmt_perf(start)}."
                f"{matches}\nMatched {len(dm.left)}/{len(values)} values with {len(dm.right)} different candidates.",
                extra={"task_id": task_id},
            )

        return dm

    def _report_unmapped(self, msg: str, task_id: int | None) -> None:
        logger = self.logger

        if self.on_unmapped == "raise":
            msg += "\nHint: Set on_unmapped='warn' or on_unmapped='ignore' to allow unmapped values."
            logger.error(msg, extra={"task_id": task_id})
            raise UnmappedValuesError(msg)
        elif self.on_unmapped == "warn":
            logger.warning(msg, extra={"task_id": task_id})
            msg += (
                "\nHint: Set on_unmapped='ignore' to hide this warning, or "
                f"on_unmapped='raise' to raise an {UnmappedValuesError.__name__}."
            )
            warnings.warn(msg, UnmappedValuesWarning, stacklevel=3)
        elif _logging.ENABLE_VERBOSE_LOGGING:
            logger.debug(msg, extra={"task_id": task_id})

    def compute_scores(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        context: ContextType | None = None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] | None = None,
        task_id: int | None = None,
        **kwargs: Any,
    ) -> ScoreMatrix[ValueType, CandidateType]:
        """Compute likeness scores.

        Args:
            values: Iterable of elements to match to candidates.
            candidates: Iterable of candidates to match with `value`. Duplicate elements will be discarded.
            context: Context in which mapping is being done.
            override_function: A callable that takes inputs ``(value, candidates, context)`` that returns either
                ``None`` (let the regular mapping logic decide) or one of the `candidates`. How non-candidates returned
                is handled is determined by the :attr:`on_unknown_user_override` property.
            task_id: Used for logging.
            **kwargs: Runtime keyword arguments for score and filter functions. May be used to add information which is
                not known when the ``Mapper`` is initialized.

        Returns:
            A ``DataFrame`` of value-candidate match scores, with ``DataFrame.index=values`` and
            ``DataFrame.columns=candidates``.

        Raises:
            BadFilterError: If a filter returns candidates that are not a subset of the original candidates.
            UserMappingError: If `override_function` returns an unknown candidate and
                ``on_unknown_user_override != 'allow'``
        """
        start = perf_counter()

        scores = ScoreMatrix(values, candidates)
        values = scores.values
        candidates = scores.candidates

        extra = f" in {context=}" if context else ""

        logger = self.logger
        logger_enabled = _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG)
        if scores.size == 0:
            if logger_enabled:
                end = "" if (values or candidates) else ", but got neither"
                logger.warning(
                    f"Abort mapping{extra} of {values}x{candidates}. Both values and candidates must be given{end}."
                )
            return scores

        score_fn = self._score
        if isinstance(score_fn, HeuristicScore):
            self._score_kwargs["task_id"] = task_id

        if logger_enabled:
            logger.debug(
                f"Begin computing match scores{extra} for {values}x{candidates} using {score_fn}.",
                extra={"task_id": task_id},
            )

        unmapped_values = self._handle_overrides(scores, context, override_function, task_id)

        logger_enabled = _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG)
        for value in unmapped_values:
            filtered_candidates = self._apply_filters(value, candidates, context, kwargs, task_id)
            if not filtered_candidates:
                continue

            scores_for_value: Iterable[float]
            if value in filtered_candidates:
                scores_for_value = [(inf if value == c else -inf) for c in filtered_candidates]  # Identity match
            else:
                if logger_enabled:
                    logger.debug(f"Compute match scores for {value=}.", extra={"task_id": task_id})
                scores_for_value = score_fn(value, filtered_candidates, context, **self._score_kwargs, **kwargs)

            for score, candidate in zip(scores_for_value, filtered_candidates, strict=True):
                scores[value, candidate] = score

        if (len(scores.values) > 1 or _logging.ENABLE_VERBOSE_LOGGING) and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                f"Computed {len(scores.values)}x{len(scores.candidates)} "
                f"match scores in {context=} in {fmt_perf(start)}:\n{scores.to_string()}",
                extra={"task_id": task_id},
            )
        return scores

    def to_directional_mapping(
        self,
        scores: ScoreMatrix[ValueType, CandidateType],
        *,
        task_id: int | None = None,
    ) -> DirectionalMapping[ValueType, CandidateType]:
        """Create a ``DirectionalMapping`` from match scores.

        Args:
            scores: A score matrix, where ``scores.index`` are values and ``score.columns`` are treated as the
                candidates.
            task_id: Used for logging.

        Returns:
            A ``DirectionalMapping``.

        See Also:
            :meth:`.ScoreHelper.to_directional_mapping`
        """
        helper = ScoreHelper(scores, self._min_score, self._logger, task_id=task_id)
        return helper.to_directional_mapping(self.cardinality)

    @property
    def cardinality(self) -> Cardinality | None:
        """Return upper cardinality bound during mapping."""
        return self._cardinality

    @property
    def on_unmapped(self) -> OnUnmapped:
        """Return the action to take if mapping fails for any values."""
        return self._on_unmapped

    @property
    def on_unknown_user_override(self) -> OnUnknownUserOverride:
        """Return the action to take if an override function returns an unknown candidate.

        Returns:
            Action to take if a user-defined override function returns an unknown candidate.
        """
        return self._on_unknown_user_override

    @property
    def logger(self) -> logging.Logger:
        """Return the ``Logger`` that is used by this instance."""
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _handle_overrides(
        self,
        scores: ScoreMatrix[ValueType, CandidateType],
        context: ContextType | None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] | None,
        task_id: int | None,
    ) -> list[ValueType]:
        applied: dict[ValueType, CandidateType] = {}

        def apply(v: ValueType, oc: CandidateType) -> None:
            scores[v, :] = -inf
            scores[v, oc] = inf
            unmapped_values.remove(v)
            applied[v] = oc

        unmapped_values = scores.values

        logger = self.logger
        logger_enabled = _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG)
        if override_function:
            for value, override_candidate in self._get_function_overrides(
                override_function,
                scores.values,
                scores.candidates,
                context,
                task_id,
            ):
                if logger_enabled:
                    logger.debug(
                        f"Using override {value!r} -> {override_candidate!r} returned by {override_function=}.",
                        extra={"task_id": task_id},
                    )
                apply(value, override_candidate)

        for value, override_candidate in self._get_static_overrides(unmapped_values, context).items():
            apply(value, override_candidate)

        if logger_enabled and (self._overrides or override_function is not None):
            num_overrides = len(self._overrides) + int(override_function is not None)
            result = f"and found {len(applied)} matches={applied} in" if applied else "but none were a match for"
            done = "All values mapped by overrides. " if (not unmapped_values and applied) else ""
            logger.debug(
                f"{done}Applied {num_overrides} overrides, {result} the given values={scores.values}.",
                extra={"task_id": task_id},
            )

        return unmapped_values

    def _get_static_overrides(
        self,
        values: Iterable[ValueType],
        context: ContextType | None,
    ) -> dict[ValueType, CandidateType]:
        if not self._overrides:
            return {}

        if isinstance(self._overrides, InheritedKeysDict):
            if context is None:
                raise MappingError("Must pass a context in context-sensitive mode.")
            overrides = self._overrides.get(context, {})
        else:
            overrides = self._overrides

        return {value: overrides[value] for value in overrides if value in values}

    def _get_function_overrides(
        self,
        func: UserOverrideFunction[ValueType, CandidateType, ContextType],
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        context: ContextType | None,
        task_id: int | None,
    ) -> list[tuple[ValueType, CandidateType]]:
        candidates = set(candidates)

        logger = self.logger

        ans = []
        for value in values:
            user_override = func(value, candidates, context)
            if user_override is None:
                continue

            if user_override not in candidates and self.on_unknown_user_override != "keep":
                msg = f"The user-defined override function {func} returned an unknown candidate={user_override!r} for {value=}."
                note = "Hint: Set on_unknown_user_override='keep' to use this value anyway."
                if self.on_unknown_user_override == "raise":
                    logger.error(msg, extra={"task_id": task_id})
                    exc = UserMappingError(msg, value, candidates)
                    exc.add_note(note)
                    raise exc

                assert self.on_unknown_user_override == "warn", f"bad {self.on_unknown_user_override=}"  # noqa: S101
                logger.warning(msg, extra={"task_id": task_id})

                msg += f"\n{note}"
                warnings.warn(msg, UserMappingWarning, stacklevel=2)

                continue

            ans.append((value, user_override))

        return ans

    def _apply_filters(
        self,
        value: ValueType,
        candidates: Iterable[CandidateType],
        context: ContextType | None,
        kwargs: dict[str, Any],
        task_id: int | None,
    ) -> set[CandidateType]:
        candidates = list(candidates)
        filtered_candidates = set(candidates)

        for filter_function, function_kwargs in self._filters:
            if "task_id" in function_kwargs:
                function_kwargs["task_id"] = task_id
            filtered_candidates = filter_function(value, filtered_candidates, context, **function_kwargs, **kwargs)

            not_in_original_candidates = filtered_candidates.difference(candidates)
            if not_in_original_candidates:
                raise BadFilterError(
                    f"Filter {tname(filter_function)}({value}, candidates, **{kwargs}) created new"
                    f"candidates: {not_in_original_candidates}"
                )

            if not filtered_candidates:
                break

        logger = self.logger
        logger_enabled = _logging.ENABLE_VERBOSE_LOGGING and logger.isEnabledFor(logging.DEBUG)
        if logger_enabled and len(self._filters):
            diff = set(candidates).difference(filtered_candidates)
            removed = f"removing candidates={diff}" if diff else "but did not remove any candidates"
            done = "All candidates removed by filtering. " if not filtered_candidates else ""
            logger.debug(
                f"{done}Applied {len(self._filters)} filters for {value=}, {removed}.",
                extra={"task_id": task_id},
            )

        return filtered_candidates

    def __repr__(self) -> str:
        score = self._score
        return f"{tname(self)}({score=} >= {self._min_score}, {len(self._filters)} filters)"

    def copy(self, **overrides: Any) -> Self:
        """Make a copy of this ``Mapper``.

        Args:
            overrides: Keyword arguments to use when instantiating the copy. Options that aren't given will be taken
                from the current instance. See the :class:`Mapper` class documentation for possible choices.

        Returns:
            A copy of this ``Mapper`` with `overrides` applied.
        """
        kwargs: dict[str, Any] = {
            "score_function": self._score,
            "min_score": self._min_score,
            "on_unmapped": self.on_unmapped,
            "on_unknown_user_override": self.on_unknown_user_override,
            "cardinality": self.cardinality,
            **overrides,
        }

        if "score_function_kwargs" not in kwargs:
            kwargs["score_function_kwargs"] = self._score_kwargs.copy()

        if "filter_functions" not in kwargs:
            kwargs["filter_functions"] = [(func, func_kwargs.copy()) for func, func_kwargs in self._filters]

        if "overrides" not in kwargs:
            kwargs["overrides"] = self._overrides.copy()

        cls = type(self)
        return cls(**kwargs)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Mapper):
            return False

        return all(
            (
                self._score == other._score,
                self._score_kwargs == other._score_kwargs,
                self._filters == other._filters,
                self._min_score == other._min_score,
                self._overrides == other._overrides,
                self._on_unmapped == other._on_unmapped,
                self._on_unknown_user_override == other._on_unknown_user_override,
                self._cardinality == other._cardinality,
            )
        )

    @classmethod
    def _initialize_filter_functions(
        cls,
        filter_functions: Iterable[FilterFunctionArgItem[ValueType, CandidateType, ContextType]],
    ) -> list[FilterFunctionWithKwargs[ValueType, CandidateType, ContextType]]:
        rv = []
        for func_or_str, kwargs in filter_functions:
            func = get_by_full_name(func_or_str, ff) if isinstance(func_or_str, str) else func_or_str

            if "task_id" in getattr(func, "__annotations__", {}):
                kwargs.setdefault("task_id", None)

            rv.append((func, kwargs))
        return rv


OU_HELPER: LiteralHelper[OnUnmapped] = LiteralHelper(
    OnUnmapped,
    default_name="on_unmapped",
    type_name="OnUnmapped",
)
OUUO_HELPER: LiteralHelper[OnUnknownUserOverride] = LiteralHelper(
    OnUnknownUserOverride,
    default_name="on_unknown_user_override",
    type_name="OnUnknownUserOverride",
)
