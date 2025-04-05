from typing import Any

from rics.collections.dicts import InheritedKeysDict

from id_translation import exceptions
from id_translation.mapping import HeuristicScore, Mapper


def default_mapper_factory(config: dict[str, Any], for_fetcher: bool) -> Mapper[Any, Any, Any] | None:
    """Create a :class:`.Mapper` from config."""
    if "score_function" in config and isinstance(config["score_function"], dict):
        score_function = config.pop("score_function")

        if len(score_function) > 1:  # pragma: no cover
            raise exceptions.ConfigurationError(
                f"At most one score function may be specified, but got: {sorted(score_function)}"
            )

        score_function, score_function_kwargs = next(iter(score_function.items()))
        config["score_function"] = score_function
        config["score_function_kwargs"] = score_function_kwargs

    if "score_function_heuristics" in config:
        if "score_function" not in config:  # pragma: no cover
            section = "fetching" if for_fetcher else "translation"
            raise exceptions.ConfigurationError(
                f"Section [{section}.mapper.score_function_heuristics] requires an explicit score function."
            )

        heuristics = [
            (heuristic_config.pop("function"), heuristic_config)
            for heuristic_config in config.pop("score_function_heuristics")
        ]
        score_function = config["score_function"]

        if isinstance(score_function, HeuristicScore):  # pragma: no cover
            for h, kwargs in heuristics:
                score_function.add_heuristic(h, kwargs)
        else:
            config["score_function"] = HeuristicScore(score_function, heuristics)

    if "filter_functions" in config:
        config["filter_functions"] = [(f.pop("function"), f) for f in config.pop("filter_functions")]

    if "overrides" in config:  # pragma: no cover
        overrides = config.pop("overrides")
        shared, specific = _split_overrides(overrides)

        if specific and not for_fetcher:
            raise exceptions.ConfigurationError(
                "Context-sensitive overrides are not possible (or needed) for "
                f"Name-to-source mapping, but got {overrides=}."
            )

        config["overrides"] = InheritedKeysDict(specific, default=shared) if for_fetcher else shared

    return Mapper(**config)


def _split_overrides(overrides: Any) -> Any:
    specific = {k: v for k, v in overrides.items() if isinstance(v, dict)}
    shared = {k: v for k, v in overrides.items() if k not in specific}
    return shared, specific
