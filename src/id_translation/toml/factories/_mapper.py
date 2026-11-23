from typing import Any

from rics.collections.dicts import InheritedKeysDict

from id_translation.mapping import HeuristicScore, Mapper

from ..exceptions import ConfigFileError
from ._initialize import expect_table


def default_mapper_factory(config: dict[str, Any], for_fetcher: bool) -> Mapper[Any, Any, Any] | None:
    """Create a :class:`~id_translation.mapping.Mapper` from config."""
    if "score_function" in config and isinstance(config["score_function"], dict):
        score_function = config.pop("score_function")
        if len(score_function) != 1:
            section = "fetching" if for_fetcher else "translator"
            msg = f"[{section}.mapping.score_function] must hold exactly one entry, got {sorted(score_function)}."
            raise ConfigFileError(msg)
        score_function, score_function_kwargs = next(iter(score_function.items()))
        config["score_function"] = score_function
        config["score_function_kwargs"] = score_function_kwargs

    if "score_function_heuristics" in config:
        if "score_function" not in config:  # pragma: no cover
            section = "fetching" if for_fetcher else "translator"
            raise ConfigFileError(
                f"Section [{section}.mapping.score_function_heuristics] requires an explicit score function."
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
            raise ConfigFileError(
                "Context-sensitive overrides are not possible (or needed) for "
                f"Name-to-source mapping, but got {overrides=}."
            )

        config["overrides"] = InheritedKeysDict(specific, default=shared) if for_fetcher else shared

    return Mapper(**config)


def _split_overrides(overrides: Any) -> Any:
    specific = {k: v for k, v in overrides.items() if isinstance(v, dict)}
    shared = {k: v for k, v in overrides.items() if k not in specific}
    return shared, specific


def _check_shape(config: dict[str, Any], *, section: str) -> None:
    if isinstance(score_function := config.get("score_function"), dict):
        if len(score_function) != 1:
            msg = f"[{section}.score_function] must hold exactly one entry, got {sorted(score_function)}."
            raise ConfigFileError(msg)
        name, kwargs = next(iter(score_function.items()))
        expect_table(kwargs, f"{section}.score_function.{name}")
    for key in ("filter_functions", "score_function_heuristics"):
        if key not in config:
            continue
        entries = config[key]
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ConfigFileError(f"[[{section}.{key}]] must be a list of tables.")
        if missing := [i for i, entry in enumerate(entries) if "function" not in entry]:
            raise ConfigFileError(f"[[{section}.{key}]] entries {missing} have no 'function' key.")
    if "overrides" in config:
        expect_table(config["overrides"], f"{section}.overrides")
