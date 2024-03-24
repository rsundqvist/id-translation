import logging
import warnings
from collections.abc import Iterable
from time import perf_counter
from typing import Any, Generic

import numpy as np
import pandas as pd
from rics.action_level import ActionLevel
from rics.collections.dicts import InheritedKeysDict
from rics.misc import get_by_full_name, tname
from rics.performance import format_perf_counter

from . import exceptions
from . import filter_functions as mf
from . import score_functions as sf
from ._cardinality import Cardinality
from ._directional_mapping import DirectionalMapping
from .exceptions import (
    MappingError,
    UnmappedValuesError,
    UnmappedValuesWarning,
    UserMappingError,
    UserMappingWarning,
)
from .types import CandidateType, ContextType, FilterFunction, ScoreFunction, UserOverrideFunction, ValueType

with warnings.catch_warnings():
    warnings.simplefilter("ignore", category=UserWarning)
    from .support import MatchScores, enable_verbose_debug_messages

FORCE_VERBOSE: bool = False  # Magic variable used by the verbose context


class Mapper(Generic[ValueType, CandidateType, ContextType]):
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
        unmapped_values_action: Action to take if mapping fails for any values.
        unknown_user_override_action: Action to take if a :attr:`id_translation.mapping.types.UserOverrideFunction`
            returns an unknown candidate. Unknown candidates, i.e. candidates not in the input `candidates` collection,
            will not be used unless `'ignore'` is chosen. As such, `'ignore'` should rather be interpreted as `'allow'`.
        cardinality: Desired cardinality for mapped values. Derive for each matching if ``None``.
        verbose_logging: If ``True``, enable verbose logging for the :meth:`apply` function. Has no effect when the log
            level is above ``logging.DEBUG``.
    """

    def __init__(
        self,
        score_function: str | ScoreFunction[ValueType, CandidateType, ContextType] = "disabled",
        score_function_kwargs: dict[str, Any] | None = None,
        filter_functions: Iterable[
            tuple[str | FilterFunction[ValueType, CandidateType, ContextType], dict[str, Any]]
        ] = (),
        min_score: float = 0.90,
        overrides: dict[ValueType, CandidateType]
        | InheritedKeysDict[ContextType, ValueType, CandidateType]
        | None = None,
        unmapped_values_action: ActionLevel.ParseType = ActionLevel.IGNORE,
        unknown_user_override_action: ActionLevel.ParseType = ActionLevel.RAISE,
        cardinality: Cardinality.ParseType | None = Cardinality.ManyToOne,
        verbose_logging: bool = False,
    ) -> None:
        if min_score <= 0 or np.isinf(min_score):
            raise ValueError(f"Got {min_score=}. The score limit should be a finite positive value.")

        self._score = get_by_full_name(score_function, sf) if isinstance(score_function, str) else score_function
        self._score_kwargs = score_function_kwargs or {}
        self._min_score = min_score
        self._overrides: InheritedKeysDict[ContextType, ValueType, CandidateType] | dict[ValueType, CandidateType] = (
            overrides if isinstance(overrides, InheritedKeysDict) else (overrides or {})
        )
        self._unmapped_action: ActionLevel = ActionLevel.verify(unmapped_values_action)
        self._bad_candidate_action: ActionLevel = ActionLevel.verify(unknown_user_override_action)
        self._cardinality = None if cardinality is None else Cardinality.parse(cardinality, strict=True)
        self._filters: list[tuple[FilterFunction[ValueType, CandidateType, ContextType], dict[str, Any]]] = [
            ((get_by_full_name(func, mf) if isinstance(func, str) else func), kwargs)
            for func, kwargs in filter_functions
        ]
        self._verbose = verbose_logging
        self._logger = logging.getLogger(__package__).getChild("Mapper")  # This will almost always be overwritten

    def apply(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        context: ContextType = None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] = None,
        **kwargs: Any,
    ) -> DirectionalMapping[ValueType, CandidateType]:
        """Map values to candidates.

        Args:
            values: Iterable of elements to match to candidates.
            candidates: Iterable of candidates to match with `value`. Duplicate elements will be discarded.
            context: Context in which mapping is being done.
            override_function: A callable that takes inputs ``(value, candidates, context)`` that returns either
                ``None`` (let the regular mapping logic decide) or one of the `candidates`. How non-candidates returned
                is handled is determined by the :attr:`unknown_user_override_action` property.
            **kwargs: Runtime keyword arguments for score and filter functions. May be used to add information which is
                not known when the ``Mapper`` is initialized.

        Returns:
            A :class:`.DirectionalMapping` on the form ``{value: [matched_candidates..]}``. May be turned into a
            plain dict ``{value: candidate}`` by using the :meth:`.DirectionalMapping.flatten` function (only if
            :attr:`.DirectionalMapping.cardinality` is of type :attr:`.Cardinality.one_right`).

        Raises:
            MappingError: If any values failed to match and ``unmapped_values_action='raise'``.
            BadFilterError: If a filter returns candidates that are not a subset of the original candidates.
            UserMappingError: If `override_function` returns an unknown candidate and
                ``unknown_user_override_action != 'ignore'``
            MappingError: If passing ``context=None`` (the default) when using context-sensitive overrides (type
                :class:`rics.collections.dicts.InheritedKeysDict`).
        """
        start = perf_counter()

        if self.verbose_logging:
            with enable_verbose_debug_messages():
                scores = self.compute_scores(values, candidates, context, override_function, **kwargs)
        else:
            scores = self.compute_scores(values, candidates, context, override_function, **kwargs)  # pragma: no cover

        dm: DirectionalMapping[ValueType, CandidateType] = self.to_directional_mapping(scores)

        unmapped = set(scores.index[~np.isinf(scores).all(axis=1)]).difference(dm.left)
        if unmapped:
            extra = f" in {context=}" if context else ""
            candidates = set(scores)
            self._report_unmapped(f"Could not map {unmapped}{extra} to any of {candidates=}.")

        verbose_logger = self._get_verbose_logger()
        if verbose_logger.isEnabledFor(logging.DEBUG):
            values = list(scores.index)
            candidates = list(scores.columns)
            cardinality = "automatic" if self.cardinality is None else self.cardinality.name

            l2r = dm.left_to_right
            matches = " Matches:\n" + "\n".join(
                f"    {v!r} -> {repr(l2r[v]) if v in l2r else '<no matches>'}" for v in values
            )

            verbose_logger.debug(
                f"Mapping with {cardinality=} completed for {values}x{candidates} in {format_perf_counter(start)}."
                f"{matches}\nMatched {len(dm.left)}/{len(values)} values with {len(dm.right)} different candidates."
            )

        return dm

    def _report_unmapped(self, msg: str) -> None:
        if self.unmapped_values_action is ActionLevel.RAISE:
            msg += (
                "\nHint: Set "
                f"unmapped_values_action='{ActionLevel.WARN.value}' or "
                f"unmapped_values_action='{ActionLevel.IGNORE.value}' "
                "to allow unmapped values."
            )
            self.logger.error(msg)
            raise UnmappedValuesError(msg)
        elif self.unmapped_values_action is ActionLevel.WARN:
            self.logger.warning(msg)
            msg += (
                "\nHint: Set "
                f"unmapped_values_action='{ActionLevel.IGNORE.value}' to hide this warning, or"
                f"unmapped_values_action='{ActionLevel.RAISE.value}' to raise an UnmappedValuesError."
            )
            warnings.warn(msg, UnmappedValuesWarning, stacklevel=2)
        else:
            self._get_verbose_logger().debug(msg)

    def compute_scores(
        self,
        values: Iterable[ValueType],
        candidates: Iterable[CandidateType],
        context: ContextType = None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Compute likeness scores.

        Args:
            values: Iterable of elements to match to candidates.
            candidates: Iterable of candidates to match with `value`. Duplicate elements will be discarded.
            context: Context in which mapping is being done.
            override_function: A callable that takes inputs ``(value, candidates, context)`` that returns either
                ``None`` (let the regular mapping logic decide) or one of the `candidates`. How non-candidates returned
                is handled is determined by the :attr:`unknown_user_override_action` property.
            **kwargs: Runtime keyword arguments for score and filter functions. May be used to add information which is
                not known when the ``Mapper`` is initialized.

        Returns:
            A ``DataFrame`` of value-candidate match scores, with ``DataFrame.index=values`` and
            ``DataFrame.columns=candidates``.

        Raises:
            BadFilterError: If a filter returns candidates that are not a subset of the original candidates.
            UserMappingError: If `override_function` returns an unknown candidate and
                ``unknown_user_override_action != 'ignore'``
        """
        start = perf_counter()

        candidates = list(candidates)
        values = list(values)
        scores = pd.DataFrame(
            data=-np.inf,
            columns=pd.Index(candidates, name="candidates").drop_duplicates(),
            index=pd.Index(values, name="values").drop_duplicates(),
            dtype=float,
        )

        extra = f" in {context=}" if context else ""

        if scores.empty:
            if self.logger.isEnabledFor(logging.DEBUG):
                end = "" if (values or candidates) else ", but got neither"
                self.logger.warning(
                    f"Abort mapping{extra} of {values}x{candidates}. Both values and candidates must be given{end}."
                )
            return scores

        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(f"Begin computing match scores{extra} for {values}x{candidates} using {self._score}.")

        unmapped_values = self._handle_overrides(scores, context, override_function)

        verbose_logger = self._get_verbose_logger()
        for value in unmapped_values:
            filtered_candidates = self._apply_filters(value, candidates, context, kwargs)
            if not filtered_candidates:
                continue

            if value in filtered_candidates:
                scores_for_value = [(np.inf if value == c else -np.inf) for c in filtered_candidates]  # Identity match
            else:
                if verbose_logger.isEnabledFor(logging.DEBUG):
                    verbose_logger.debug(f"Compute match scores for {value=}.")
                scores_for_value = self._score(value, filtered_candidates, context, **self._score_kwargs, **kwargs)

            for score, candidate in zip(scores_for_value, filtered_candidates):
                scores.loc[value, candidate] = score

        if verbose_logger.isEnabledFor(logging.DEBUG):
            verbose_logger.debug(
                f"Computed {len(scores.index)}x{len(scores.columns)} "
                f"match scores in {format_perf_counter(start)}:\n{scores.to_string()}"
            )
        return scores

    def to_directional_mapping(
        self,
        scores: pd.DataFrame,
    ) -> DirectionalMapping[ValueType, CandidateType]:
        """Create a ``DirectionalMapping`` from match scores.

        Args:
            scores: A score matrix, where ``scores.index`` are values and ``score.columns`` are treated as the
                candidates.

        Returns:
            A ``DirectionalMapping``.

        See Also:
            :meth:`.MatchScores.to_directional_mapping`
        """
        return MatchScores(scores, self._min_score, self._get_verbose_logger()).to_directional_mapping(self.cardinality)

    def _get_verbose_logger(self) -> logging.Logger:
        logger = self.logger.getChild("verbose")
        logger.disabled = not (FORCE_VERBOSE or self.verbose_logging)
        return logger

    @property
    def cardinality(self) -> Cardinality | None:
        """Return upper cardinality bound during mapping."""
        return self._cardinality

    @property
    def unmapped_values_action(self) -> ActionLevel:
        """Return the action to take if mapping fails for any values."""
        return self._unmapped_action

    @property
    def unknown_user_override_action(self) -> ActionLevel:
        """Return the action to take if an override function returns an unknown candidate.

        Unknown candidates, i.e. candidates not in the input `candidates` collection, will not be used unless `'ignore'`
        is chosen. As such, `'ignore'` should rather be interpreted as `'allow'`.

        Returns:
            Action to take if a user-defined override function returns an unknown candidate.
        """
        return self._bad_candidate_action

    @property
    def verbose_logging(self) -> bool:
        """Return ``True`` if verbose debug-level messages are enabled."""
        return self._verbose

    @property
    def logger(self) -> logging.Logger:
        """Return the ``Logger`` that is used by this instance."""
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _handle_overrides(
        self,
        scores: pd.DataFrame,
        context: ContextType | None,
        override_function: UserOverrideFunction[ValueType, CandidateType, ContextType] | None,
    ) -> list[ValueType]:
        applied: dict[ValueType, CandidateType] = {}

        def apply(v: ValueType, oc: CandidateType) -> None:
            scores.loc[v, :] = -np.inf
            scores.loc[v, oc] = np.inf
            unmapped_values.remove(v)
            applied[v] = oc

        unmapped_values = list(scores.index)

        if override_function:
            for value, override_candidate in self._get_function_overrides(
                override_function, scores.index, scores.columns, context
            ):
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        f"Using override {value!r} -> {override_candidate!r} returned by {override_function=}."
                    )
                apply(value, override_candidate)

        for value, override_candidate in self._get_static_overrides(unmapped_values, context).items():
            apply(value, override_candidate)

        if self.logger.isEnabledFor(logging.DEBUG) and (self._overrides or override_function is not None):
            num_overrides = len(self._overrides) + int(override_function is not None)
            result = f"and found {len(applied)} matches={applied} in" if applied else "but none were a match for"
            done = "All values mapped by overrides. " if (not unmapped_values and applied) else ""
            self.logger.debug(
                f"{done}Applied {num_overrides} overrides, {result} the given values={list(scores.index)}."
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
    ) -> list[tuple[ValueType, CandidateType]]:
        candidates = set(candidates)

        ans = []
        for value in values:
            user_override = func(value, candidates, context)
            if user_override is None:
                continue
            if self.unknown_user_override_action is not ActionLevel.IGNORE and user_override not in candidates:
                msg = (
                    f"The user-defined override function {func} returned an unknown candidate={user_override!r} for"
                    f" {value=}."
                    "\nHint: If this is intended behaviour, set unknown_user_override_action='ignore' to allow."
                )
                if self.unknown_user_override_action is ActionLevel.RAISE:
                    self.logger.error(msg)
                    raise UserMappingError(msg, value, candidates)
                elif self.unknown_user_override_action is ActionLevel.WARN:
                    msg += " The override has been ignored."
                    self.logger.warning(msg)
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
    ) -> set[CandidateType]:
        candidates = list(candidates)
        filtered_candidates = set(candidates)

        for filter_function, function_kwargs in self._filters:
            filtered_candidates = filter_function(value, filtered_candidates, context, **function_kwargs, **kwargs)

            not_in_original_candidates = filtered_candidates.difference(candidates)
            if not_in_original_candidates:
                raise exceptions.BadFilterError(
                    f"Filter {tname(filter_function)}({value}, candidates, **{kwargs}) created new"
                    f"candidates: {not_in_original_candidates}"
                )

            if not filtered_candidates:
                break

        if self.verbose_logging and self.logger.isEnabledFor(logging.DEBUG) and len(self._filters):
            diff = set(candidates).difference(filtered_candidates)
            removed = f"removing candidates={diff}" if diff else "but did not remove any candidates"
            done = "All candidates removed by filtering. " if not filtered_candidates else ""
            self.logger.debug(f"{done}Applied {len(self._filters)} filters for {value=}, {removed}.")

        return filtered_candidates

    def __repr__(self) -> str:
        score = self._score
        return f"{tname(self)}({score=} >= {self._min_score}, {len(self._filters)} filters)"

    def copy(self, **overrides: Any) -> "Mapper[ValueType, CandidateType, ContextType]":
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
            "unmapped_values_action": self.unmapped_values_action,
            "unknown_user_override_action": self.unknown_user_override_action,
            "cardinality": self.cardinality,
            "verbose_logging": self.verbose_logging,
            **overrides,
        }

        if "score_function_kwargs" not in kwargs:
            kwargs["score_function_kwargs"] = self._score_kwargs.copy()

        if "filter_functions" not in kwargs:
            kwargs["filter_functions"] = [(func, func_kwargs.copy()) for func, func_kwargs in self._filters]

        if "overrides" not in kwargs:
            kwargs["overrides"] = self._overrides.copy()

        return Mapper(**kwargs)

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
                self._unmapped_action == other._unmapped_action,
                self._bad_candidate_action == other._bad_candidate_action,
                self._cardinality == other._cardinality,
                self._verbose == other._verbose,
            )
        )
