"""Factory functions for translation classes."""
from contextlib import contextmanager as _contextmanager
from pathlib import Path as _Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generator as _Generator,
    Generic as _Generic,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

from rics import misc
from rics._internal_support.types import PathLikeType
from rics.collections import dicts

from . import exceptions, fetching
from ._config_utils import ConfigMetadata as _ConfigMetadata
from ._load_toml import load_toml_file as _load_toml_file
from .mapping import HeuristicScore as _HeuristicScore, Mapper as _Mapper
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
    """A callable ``(clazz, config) -> AbstractFetcher``. Overwrite attribute to customize."""
    MAPPER_FACTORY: MapperFactory = default_mapper_factory
    """A callable ``(config, for_fetcher) -> Mapper``. Overwrite attribute to customize."""

    def __init__(
        self,
        file: PathLikeType,
        extra_fetchers: Iterable[PathLikeType],
        clazz: Union[str, Type["Translator[NameType, SourceType, IdType]"]] = None,
    ) -> None:
        self.file = str(file)
        self.extra_fetchers = list(map(str, extra_fetchers))
        self.clazz: Type[Translator[NameType, SourceType, IdType]] = self.resolve_class(clazz)
        self._metaconf = _read_metaconf(self.file)

    def create(self) -> "Translator[NameType, SourceType, IdType]":
        """Create a ``Translator`` from a TOML file."""
        config_metadata = _ConfigMetadata.from_toml_paths(
            self.file,
            self.extra_fetchers,
            self.clazz,
        )
        with _rethrow_with_file(self.file):
            config: Dict[str, Any] = self.load_toml_file(self.file)

        fetcher: fetching.Fetcher[SourceType, IdType] = self._handle_fetching(
            config.pop("fetching", {}), self.extra_fetchers, _cache_keys_from_config_metadata(config_metadata)
        )

        with _rethrow_with_file(self.file):
            _check_allowed_keys(["translator", "mapping", "fetching", "unknown_ids"], config, "<root>")
            translator_config = config.pop("translator", {})
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

            ans._config_metadata = config_metadata
            return ans

    def load_toml_file(self, path: str) -> Dict[str, Any]:
        """Read a TOML file from `path`."""
        config = dict(allow_interpolation=True)
        config.update(self._metaconf.get("env", {}))
        return _load_toml_file(path, **config)

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
        extra_fetchers: List[str],
        default_cache_keys: List[List[str]],
    ) -> fetching.Fetcher[SourceType, IdType]:
        multi_fetcher_kwargs = config.pop("MultiFetcher", {})

        fetchers: List[fetching.Fetcher[SourceType, IdType]] = []

        if config:
            with _rethrow_with_file(self.file):
                fetchers.append(self._make_fetcher(default_cache_keys[0], **config))  # Add primary fetcher

        for i, file_fetcher_file in enumerate(extra_fetchers, start=1):
            with _rethrow_with_file(file_fetcher_file):
                fetcher_config = self.load_toml_file(file_fetcher_file)
                fetcher = self._make_fetcher(default_cache_keys[i], **fetcher_config["fetching"])
            fetchers.append(fetcher)

        if not fetchers:
            raise exceptions.ConfigurationError(
                f"At least one [fetching]-section is required. Add it to '{self.file}',"
                " or as an auxiliary configuration.",
            )

        return fetchers[0] if len(fetchers) == 1 else fetching.MultiFetcher(*fetchers, **multi_fetcher_kwargs)

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
    def _make_fetcher(cls, cache_keys: List[str], **config: Any) -> fetching.AbstractFetcher[SourceType, IdType]:
        mapper = cls._make_mapper("fetching", config) if "mapping" in config else None

        if len(config) == 0:  # pragma: no cover
            raise exceptions.ConfigurationError("Fetcher implementation section missing.")
        if len(config) > 1:  # pragma: no cover
            raise exceptions.ConfigurationError(
                f"Multiple fetcher implementations specified in the same file: {sorted(config)}"
            )

        clazz, kwargs = next(iter(config.items()))

        kwargs["cache_keys"] = kwargs.get("cache_keys", cache_keys)
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


def _cache_keys_from_config_metadata(config_metadata: _ConfigMetadata) -> List[List[str]]:
    # Use the config filename and sha hash as the default keys
    return list(map(lambda t: [t[0].name, t[1]], (config_metadata.main,) + config_metadata.extra_fetchers))


def _read_metaconf(file: str) -> Dict[str, Any]:
    path = _Path(file).with_name("metaconf.toml")
    if path.exists():
        metaconf = _load_toml_file(path)
    else:
        return {}

    return metaconf


@_contextmanager
def _rethrow_with_file(file: str) -> _Generator[None, None, None]:
    try:
        yield
    except Exception as e:  # noqa: B902
        msg = f"{type(e).__name__}: {e}"
        raise exceptions.ConfigurationError(f"{msg}\n   raised when parsing file: {_Path(file).resolve()}")
