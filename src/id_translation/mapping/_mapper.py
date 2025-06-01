import logging
import warnings
from collections.abc import Iterable
from time import perf_counter
from typing import Any, Generic, Self

import numpy as np
import pandas as pd
from rics.collections.dicts import InheritedKeysDict
from rics.misc import get_by_full_name, tname
from rics.strings import format_perf_counter as fmt_perf
from rics.types import LiteralHelper

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
        on_unmapped: Action to take if mapping fails for any values.
        on_unknown_user_override: Action to take if an :attr:`~id_translation.mapping.types.UserOverrideFunction`
            returns an unknown candidate. Unknown candidates, i.e. candidates not in the input `candidates` collection,
            will not be used unless `'allow'` is chosen.
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
        on_unmapped: OnUnmapped = "ignore",
        on_unknown_user_override: OnUnknownUserOverride = "raise",
        cardinality: CardinalityType | None = Cardinality.ManyToOne,
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
        self._on_unmapped = OU_HELPER.check(on_unmapped)
        self._on_unknown_user_override = OUUO_HELPER.check(on_unknown_user_override)
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
                is handled is determined by the :attr:`on_unknown_user_override` property.
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

        candidates = list(candidates)
        values = list(values)
        if not (values and candidates):
            self.logger.debug("Aborting since values=%r and candidates=%r in context=%r.", values, candidates, context)
            return DirectionalMapping(left_to_right={}, _verify=False, cardinality=self.cardinality)

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
            cardinality = "automatic" if self.cardinality is None else self.cardinality.name

            l2r = dm.left_to_right
            matches = " Matches:\n" + "\n".join(
                f"    {v!r} -> {repr(l2r[v]) if v in l2r else '<no matches>'}" for v in values
            )

            verbose_logger.debug(
                f"Mapping with {cardinality=} completed for {values}x{candidates} in {fmt_perf(start)}."
                f"{matches}\nMatched {len(dm.left)}/{len(values)} values with {len(dm.right)} different candidates."
            )

        return dm

    def _report_unmapped(self, msg: str) -> None:
        if self.on_unmapped == "raise":
            msg += "\nHint: Set on_unmapped='warn' or on_unmapped='ignore' to allow unmapped values."
            self.logger.error(msg)
            raise UnmappedValuesError(msg)
        elif self.on_unmapped == "warn":
            self.logger.warning(msg)
            msg += (
                "\nHint: Set "
                "on_unmapped='ignore' to hide this warning, or "
                f"on_unmapped='raise' to raise an {UnmappedValuesError.__name__}."
            )
            warnings.warn(msg, UnmappedValuesWarning, stacklevel=3)
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
                is handled is determined by the :attr:`on_unknown_user_override` property.
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

            scores_for_value: Iterable[float]
            if value in filtered_candidates:
                scores_for_value = [(np.inf if value == c else -np.inf) for c in filtered_candidates]  # Identity match
            else:
                if verbose_logger.isEnabledFor(logging.DEBUG):
                    verbose_logger.debug(f"Compute match scores for {value=}.")
                scores_for_value = self._score(value, filtered_candidates, context, **self._score_kwargs, **kwargs)

            for score, candidate in zip(scores_for_value, filtered_candidates, strict=True):
                scores.loc[value, candidate] = score

        if verbose_logger.isEnabledFor(logging.DEBUG):
            verbose_logger.debug(
                f"Computed {len(scores.index)}x{len(scores.columns)} "
                f"match scores in {fmt_perf(start)}:\n{scores.to_string()}"
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
            if user_override not in candidates and self.on_unknown_user_override != "keep":
                msg = (
                    f"The user-defined override function {func} returned an unknown candidate={user_override!r} for"
                    f" {value=}.\nHint: Set on_unknown_user_override='keep' to use this value anyway."
                )
                if self.on_unknown_user_override == "raise":
                    self.logger.error(msg)
                    raise UserMappingError(msg, value, candidates)
                elif self.on_unknown_user_override == "warn":
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
            "verbose_logging": self.verbose_logging,
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
                self._verbose == other._verbose,
            )
        )


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
