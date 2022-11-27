"""Factory functions for translation classes."""
from typing import TYPE_CHECKING, Any, Callable, Dict, Generic as _Generic, Iterable, List, Optional, Tuple, Type, Union

try:
    import tomllib  # type: ignore
except ModuleNotFoundError:
    # PEP-680 compatibility layer for Python < 3.11, see https://peps.python.org/pep-0680/
    # Shamelessly stolen from https://github.com/hukkin/tomli#building-a-tomlitomllib-compatibility-layer
    import tomli as tomllib  # type: ignore

from rics import misc
from rics._internal_support.types import PathLikeType
from rics.action_level import ActionLevel as _ActionLevel
from rics.collections import dicts
from rics.mapping import HeuristicScore as _HeuristicScore, Mapper as _Mapper

from . import _config_utils, exceptions, fetching
from .types import IdType, NameType, SourceType

if TYPE_CHECKING:
    from . import Translator

FetcherFactory = Callable[[str, Dict[str, Any]], fetching.AbstractFetcher]
"""A callable which creates new ``AbstractFetcher`` instances from a dict config.

Config format is described in :ref:`translator-config-fetching`.

Args:
    clazz: Type of ``AbstractFetcher`` to create.
    config: Keyword arguments for the fetcher class.

Returns:
    A ``Fetcher`` instance.

Raises:
    exceptions.ConfigurationError: If `config` is invalid.
    TypeError: If `clazz` is not an AbstractFetcher subtype.
"""

MapperFactory = Callable[[Dict[str, Any], bool], Optional[_Mapper]]
"""A callable which creates new ``Mapper`` instances from a dict config.

Config format is described in :ref:`translator-config-mapping`.

If ``None`` is returned, a suitable default is used instead.

Args:
    config: Keyword arguments for the ``Mapper``.
    for_fetcher: Flag indicating that the ``Mapper`` returned will be used by an ``AbstractFetcher`` instance.

Returns:
    A ``Mapper`` instance or ``None``.

Raises:
    ConfigurationError: If `config` is invalid.
"""


def default_fetcher_factory(clazz: str, config: Dict[str, Any]) -> fetching.AbstractFetcher[SourceType, IdType]:
    """Create an ``AbstractFetcher`` from config."""
    fetcher_class = misc.get_by_full_name(clazz, default_module=fetching)
    fetcher = fetcher_class(**config)
    if not isinstance(fetcher, fetching.AbstractFetcher):  # pragma: no cover
        raise TypeError(f"Fetcher of type {fetcher} created from '{clazz}' is not an AbstractFetcher.")
    return fetcher


def default_mapper_factory(config: Dict[str, Any], for_fetcher: bool) -> Optional[_Mapper[Any, Any, Any]]:
    """Create a ``Mapper`` from config."""
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

        if isinstance(score_function, _HeuristicScore):  # pragma: no cover
            for h, kwargs in heuristics:
                score_function.add_heuristic(h, kwargs)
        else:
            config["score_function"] = _HeuristicScore(score_function, heuristics)

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

        config["overrides"] = dicts.InheritedKeysDict(specific, default=shared) if for_fetcher else shared

    return _Mapper(**config)


class TranslatorFactory(_Generic[NameType, SourceType, IdType]):
    """Create a ``Translator`` from TOML inputs."""

    FETCHER_FACTORY: FetcherFactory = default_fetcher_factory
    """A callable ``(name, kwargs) -> AbstractFetcher``. Overwrite attribute to customize."""
    MAPPER_FACTORY: MapperFactory = default_mapper_factory
    """A callable ``(kwargs) -> Mapper``. Overwrite attribute to customize."""

    def __init__(
        self,
        file: PathLikeType,
        extra_fetchers: Iterable[PathLikeType],
        clazz: Union[str, Type["Translator[NameType, SourceType, IdType]"]] = None,
    ) -> None:
        self.file = str(file)
        self.extra_fetchers = list(map(str, extra_fetchers))
        self.clazz: Type[Translator[NameType, SourceType, IdType]] = self.resolve_class(clazz)

    def create(self) -> "Translator[NameType, SourceType, IdType]":
        """Create a ``Translator`` from a TOML file."""
        with open(self.file, "rb") as f:
            config: Dict[str, Any] = tomllib.load(f)

        _check_allowed_keys(["translator", "mapping", "fetching", "unknown_ids"], config, "<root>")

        translator_config = config.pop("translator", {})

        fetcher: fetching.Fetcher[SourceType, IdType] = self._handle_fetching(
            config.pop("fetching", {}), self.extra_fetchers
        )

        mapper = self._make_mapper("translator", translator_config)
        default_fmt_placeholders: Optional[dicts.InheritedKeysDict[SourceType, str, Any]]
        default_fmt, default_fmt_placeholders = _make_default_translations(**config.pop("unknown_ids", {}))

        ans = self.clazz(
            fetcher,
            mapper=mapper,
            default_fmt=default_fmt,
            default_fmt_placeholders=default_fmt_placeholders,
            **translator_config,
        )

        ans._config_metadata = _config_utils.make_metadata(
            self.file,
            self.extra_fetchers,
            self.clazz,
        )

        return ans

    @classmethod
    def resolve_class(
        cls, clazz: Union[str, Type["Translator[NameType, SourceType, IdType]"]] = None
    ) -> Type["Translator[NameType, SourceType, IdType]"]:
        """Resolve desired ``Translator`` type."""
        if clazz is None:
            from . import Translator

            return Translator

        if isinstance(clazz, str):
            return misc.get_by_full_name(clazz)  # type: ignore[no-any-return]
        else:
            return clazz

    def _handle_fetching(
        self,
        config: Dict[str, Any],
        extra_fetchers: Iterable[str],
    ) -> fetching.Fetcher[SourceType, IdType]:
        fetchers: List[fetching.Fetcher[SourceType, IdType]] = []
        if config:
            fetchers.append(self._make_fetcher(**config))  # Add primary fetcher

        for file_fetcher_file in extra_fetchers:
            with open(file_fetcher_file, "rb") as f:
                fetchers.append(self._make_fetcher(**tomllib.load(f)["fetching"]))

        if not fetchers:
            raise exceptions.ConfigurationError(
                "Section [fetching] is required when no pre-initialized AbstractFetcher is given."
            )

        return (
            fetchers[0]
            if len(fetchers) == 1
            else fetching.MultiFetcher(*fetchers, duplicate_source_discovered_action=_ActionLevel.WARN)
        )

    @classmethod
    def _make_mapper(cls, parent_section: str, config: Dict[str, Any]) -> Optional[_Mapper[Any, Any, Any]]:
        if "mapping" not in config:
            return None  # pragma: no cover

        config = config.pop("mapping")
        for_fetcher = parent_section.startswith("fetching")
        if for_fetcher:
            config = {**fetching.AbstractFetcher.default_mapper_kwargs(), **config}

        return TranslatorFactory.MAPPER_FACTORY(config, for_fetcher)

    @classmethod
    def _make_fetcher(cls, **config: Any) -> fetching.AbstractFetcher[SourceType, IdType]:
        mapper = cls._make_mapper("fetching", config) if "mapping" in config else None

        if len(config) == 0:  # pragma: no cover
            raise exceptions.ConfigurationError("Fetcher implementation section missing.")
        if len(config) > 1:  # pragma: no cover
            raise exceptions.ConfigurationError(
                f"Multiple fetcher implementations specified in the same file: {sorted(config)}"
            )

        clazz, kwargs = next(iter(config.items()))
        kwargs["mapper"] = mapper
        return TranslatorFactory.FETCHER_FACTORY(clazz, kwargs)


def _make_default_translations(
    **config: Any,
) -> Tuple[str, Optional[dicts.InheritedKeysDict[SourceType, str, Any]]]:  # pragma: no cover
    _check_allowed_keys(["fmt", "overrides"], config, toml_path="translator.unknown_ids")

    fmt = config.pop("fmt", None)
    if "overrides" in config:
        shared, specific = _split_overrides(config.pop("overrides"))
        return fmt, dicts.InheritedKeysDict(specific, default=shared)
    else:
        return fmt, None


def _check_allowed_keys(allowed: Iterable[str], actual: Iterable[str], toml_path: str) -> None:  # pragma: no cover
    bad_keys = set(actual).difference(allowed)
    if bad_keys:
        raise ValueError(f"Forbidden keys {sorted(bad_keys)} in [{toml_path}]-section.")


def _split_overrides(overrides: Any) -> Any:
    specific = {k: v for k, v in overrides.items() if isinstance(v, dict)}
    shared = {k: v for k, v in overrides.items() if k not in specific}
    return shared, specific
