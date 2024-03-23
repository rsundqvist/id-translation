import logging
from collections.abc import Iterable
from typing import Any, Generic

from rics.misc import get_by_full_name, tname

from . import filter_functions, heuristic_functions, score_functions
from .types import CandidateType, ContextType, HeuristicsTypes, ScoreFunction, ValueType

LOGGER = logging.getLogger(__package__).getChild("verbose").getChild("HeuristicScore")


class HeuristicScore(Generic[ValueType, CandidateType, ContextType]):
    """Callable wrapper for computing heuristic scores.

    Instances are callable. Signature is given by :attr:`~id_translation.mapping.types.ScoreFunction`.

    Short-circuiting:
        A mechanism for forced matching. Score is set to `+∞` for short-circuited candidates, and `-∞` for the rest.
        No further matching will be performed after this point, so ensure that all desired candidates are returned by
        chosen filters.

    Procedure:
        1. Trigger ``short-circuiting`` if there is an exact value-candidate match.
        2. All `heuristics` are applied and scores are computed.
        3. If no ``short-circuiting`` is triggered in step 2, yield max score for each candidate.

    Args:
        score_function: A :attr:`~id_translation.mapping.types.ScoreFunction` to wrap.
        heuristics: Iterable of heuristics or tuples ``(heuristic, kwargs)`` to apply to the ``(value, candidates)``
            inputs of `score_function`.

    Heuristic types:
        * An :const:`~id_translation.mapping.types.AliasFunction`, which accepts and returns a tuple
          (value, candidates) to be evaluated.
        * A :const:`~id_translation.mapping.types.FilterFunction`, which accepts a tuple (value, candidates) and
          returns a subset of `candidates`. If any candidates are returned, ``short-circuiting`` is triggered.

    Notes:
        * Heuristic function input order = application order.
        * You may add ``mutate=True`` to the heuristics kwargs to forward to the modifications made by that function.
    """

    def __init__(
        self,
        score_function: str | ScoreFunction[ValueType, CandidateType, ContextType],
        heuristics: Iterable[
            (
                str
                | HeuristicsTypes[ValueType, CandidateType, ContextType]
                | tuple[str | HeuristicsTypes[ValueType, CandidateType, ContextType], dict[str, Any]]
            )
        ],
    ) -> None:
        self._score: ScoreFunction[ValueType, CandidateType, ContextType] = (
            get_by_full_name(score_function, score_functions) if isinstance(score_function, str) else score_function
        )
        self._heuristics: list[tuple[HeuristicsTypes[ValueType, CandidateType, ContextType], dict[str, Any]]] = []

        for h in heuristics:
            func, kwargs = h if isinstance(h, tuple) else (h, {})
            self.add_heuristic(func, kwargs)

    @property
    def score_function(self) -> ScoreFunction[ValueType, CandidateType, ContextType]:
        """Return the underlying likeness score function."""
        return self._score

    def add_heuristic(
        self,
        heuristic: str | HeuristicsTypes[ValueType, CandidateType, ContextType],
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Add a new heuristic."""
        new_heuristic = (_resolve_heuristic(heuristic), kwargs or {})
        self._heuristics.append(new_heuristic)

    def __repr__(self) -> str:
        score_function = self._score
        heuristics = self._heuristics
        return f"{tname(self)}({score_function=}, {heuristics=})"

    def __call__(
        self, value: ValueType, candidates: Iterable[CandidateType], context: ContextType | None, **kwargs: Any
    ) -> Iterable[float]:
        """Apply `score_function` with heuristics and short-circuiting."""
        candidates = list(candidates)

        base_score = list(self.score_function(value, candidates, context, **kwargs))  # Unmodified score
        best = list(base_score)

        log_aliases = heuristic_functions.VERBOSE and LOGGER.isEnabledFor(logging.DEBUG)

        positional_penalty = 0.0  # A small value that rewards alias functions based on their position.
        h_value = value
        h_candidates = list(candidates)
        for func, func_kwargs in self._heuristics:
            func_kwargs = func_kwargs.copy()  # noqa: PLW2901
            mutate = func_kwargs.pop("mutate", False)
            res = func(h_value, h_candidates, context, **func_kwargs)
            if isinstance(res, tuple):  # Alias function -- res is a modified (value, candidates) tuple
                res_value, res_candidates = res[0], list(res[1])
                res_scores = list(self._score(res_value, res_candidates, context, **kwargs))
                for i, heuristic_score in enumerate(res_scores):
                    heuristic_score -= positional_penalty  # noqa: PLW2901
                    best[i] = max(best[i], heuristic_score)

                if log_aliases:
                    mutating = "mutating" if mutate else "non-mutating"

                    res_value_repr = f"{res_value!r}" if (h_value != res_value) else "*"
                    res_candidates_repr = f"{res_candidates!r}" if (h_candidates != res_candidates) else "*"

                    res_score_repr = [round(s, 3) for s in res_scores]
                    LOGGER.debug(
                        f"Called {mutating} alias function {_stringify((func, func_kwargs))} in {context=}:\n    "
                        f"({h_value!r}, {h_candidates!r}) -> ({res_value_repr}, {res_candidates_repr})."
                        f"\n    Positional penalty={positional_penalty:.3f}. Scores before penalty: {res_score_repr}."
                    )
                else:
                    pass  # pragma: no cover

                if mutate:
                    h_value, h_candidates = res_value, res_candidates

                positional_penalty += 0.005
            elif res:  # Filter function, triggers short-circuiting
                if mutate:
                    raise TypeError(f"Filter function {_stringify((func, func_kwargs))} cannot use {mutate=}.")

                if heuristic_functions.VERBOSE and LOGGER.isEnabledFor(logging.DEBUG):
                    base_args = ", ".join([repr(h_value), repr(h_candidates), f"{context=}"])
                    extra_args = ", ".join(f"{k}={v!r}" for k, v in func_kwargs.items())
                    info = f"{tname(func)}({', '.join([base_args, extra_args])})"
                    LOGGER.debug(f"Short-circuit {value=} -> candidates={res!r}, triggered by {info}.")
                yield from (float("inf") if c in res else -float("inf") for c in h_candidates)
                return

        if heuristic_functions.VERBOSE and LOGGER.isEnabledFor(logging.DEBUG):
            changes = [
                f"{cand!r}: {score:.2f} -> {heuristic_score:.2f} ({heuristic_score - score:+.2f})"
                for cand, score, heuristic_score in zip(candidates, base_score, best)
            ]
            LOGGER.debug(f"Heuristics scores for {value=}: [{', '.join(changes)}]")

        yield from best

    def __str__(self) -> str:
        score_function = tname(self.score_function, prefix_classname=True)
        return f"{tname(self)}([{' | '.join(map(_stringify, self._heuristics))}] -> {score_function})"


def _stringify(*args: Any) -> str:
    f, kwargs = args[0] if len(args) == 1 else args
    kwlist = (f"{k}={v!r}" for k, v in kwargs.items())
    return f"{tname(f)}({', '.join(kwlist)})"


def _resolve_heuristic(
    func_or_name: str | HeuristicsTypes[ValueType, CandidateType, ContextType],
) -> HeuristicsTypes[ValueType, CandidateType, ContextType]:
    if isinstance(func_or_name, str):
        for m in filter_functions, heuristic_functions:
            try:
                return get_by_full_name(func_or_name, m)  # type: ignore[no-any-return]
            except AttributeError:  # noqa: PERF203
                pass

        raise NameError(func_or_name)
    else:
        return func_or_name
