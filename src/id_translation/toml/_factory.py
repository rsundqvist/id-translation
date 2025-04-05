import logging
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeAlias

from rics.collections.dicts import InheritedKeysDict

from id_translation._compat import PathLikeType
from id_translation.exceptions import ConfigurationError
from id_translation.fetching import AbstractFetcher, CacheAccess, Fetcher, MultiFetcher
from id_translation.mapping import Mapper
from id_translation.transform.types import Transformer, Transformers
from id_translation.types import IdType, NameType, SourceType

from . import factories as cf
from ._load_toml import load_toml_file
from .meta import ConfigMetadata, Metaconf

if TYPE_CHECKING:
    from id_translation import Translator


class TranslatorFactory(Generic[NameType, SourceType, IdType]):
    """Create a :class:`.Translator` from TOML inputs."""

    FetcherFactory: TypeAlias = Callable[[str, dict[str, Any]], AbstractFetcher[Any, Any]]
    """Signature for :attr:`FETCHER_FACTORY`."""

    FETCHER_FACTORY: FetcherFactory = staticmethod(cf.default_fetcher_factory)
    """A callable ``(clazz, config) -> AbstractFetcher``.

    Overwrite attribute with your own :attr:`.FetcherFactory` implementation to customize.

    Args:
        clazz: Type of :class:`.AbstractFetcher` to create.
        config: Keyword arguments for the fetcher class.

    Returns:
        An :class:`.AbstractFetcher` instance.

    Raises:
        exceptions.ConfigurationError: If `config` is invalid.
        TypeError: If `clazz` is not an :class:`.AbstractFetcher` subtype.

    See Also:
        :ref:`translator-config-fetching`
    """

    MapperFactory: TypeAlias = Callable[[dict[str, Any], bool], Mapper[Any, Any, Any] | None]
    """Signature for :attr:`MAPPER_FACTORY`."""

    MAPPER_FACTORY: MapperFactory = cf.default_mapper_factory
    """A callable ``(config, for_fetcher) -> Mapper | None``.

    Overwrite attribute with your own :attr:`.MapperFactory` implementation to customize.

    If ``None`` is returned, a suitable default is used instead.

    Args:
        config: Keyword arguments for the :class:`.Mapper`.
        for_fetcher: Flag indicating that the :class:`.Mapper` returned will be used by an :class:`.AbstractFetcher` instance.

    Returns:
        A :class:`.Mapper` instance or ``None``.

    Raises:
        ConfigurationError: If `config` is invalid.

    See Also:
        :ref:`translator-config-mapping`
    """

    TransformerFactory: TypeAlias = Callable[[str, dict[str, Any]], Transformer[Any]]
    """Signature for :attr:`TRANSFORMER_FACTORY`."""

    TRANSFORMER_FACTORY: TransformerFactory = cf.default_transformer_factory
    """A callable ``(clazz, config) -> Transformer``.

    Overwrite attribute with your own :attr:`.TransformerFactory` implementation to customize.

    Args:
        clazz: Type of :class:`.Transformer` to create.
        config: Keyword arguments for the transformer class.

    Returns:
        A :class:`.Transformer` instance.

    Raises:
        ConfigurationError: If `config` is invalid.

    See Also:
        :ref:`translator-config-transform`
    """

    CacheAccessFactory: TypeAlias = Callable[[str, dict[str, Any]], CacheAccess[Any, Any]]
    """Signature for :attr:`CACHE_ACCESS_FACTORY`."""

    CACHE_ACCESS_FACTORY: CacheAccessFactory = cf.default_cache_access_factory
    """A callable ``(clazz, config) -> CacheAccess``.

    Overwrite attribute with your own :attr:`.CacheAccessFactory` implementation to customize.

    Args:
        clazz: Type of :class:`.CacheAccess` to create.
        config: Keyword arguments for the cache class.

    Returns:
        A :class:`.CacheAccess` instance.

    Raises:
        ConfigurationError: If `config` is invalid.
    """

    TOP_LEVEL_KEYS = ("translator", "mapping", "fetching", "unknown_ids", "transform")
    """Top-level keys allowed in the main configuration file."""

    def __init__(
        self,
        file: PathLikeType,
        fetchers: Iterable[PathLikeType],
        clazz: type["Translator[NameType, SourceType, IdType]"] | None = None,
    ) -> None:
        from id_translation import Translator

        self.file = str(file)
        self.extra_fetchers = list(map(str, fetchers))
        self.clazz: type[Translator[NameType, SourceType, IdType]] = clazz or Translator[NameType, SourceType, IdType]

        metaconf_path = str(Path(self.file).with_name("metaconf.toml"))
        self._metaconf = Metaconf.from_path_or_default(metaconf_path)
        self.logger = logging.getLogger(__package__).getChild(type(self).__name__)

    @property
    def metaconf(self) -> Metaconf:
        """Returns the meta configuration instance used by this factory."""
        return self._metaconf

    def create(self) -> "Translator[NameType, SourceType, IdType]":
        """Create :class:`.Translator` instance."""
        config_metadata = ConfigMetadata.from_toml_paths(self.file, self.extra_fetchers, self.clazz)
        with _rethrow_with_file(self.file):
            config: dict[str, Any] = self.load_toml_file(self.file)

        fetcher, fetcher_transformers = self._handle_fetching(
            config.pop("fetching", {}), self.extra_fetchers, _identifier_from_config_metadata(config_metadata)
        )

        with _rethrow_with_file(self.file):
            _check_allowed_keys(self.TOP_LEVEL_KEYS, actual=config, toml_path="<root>")
            translator_config = config.pop("translator", {})
            mapper = self._make_mapper("translator", translator_config)
            _make_default_translations(translator_config, config.pop("unknown_ids", {}))

            translator_transformers = self._handler_transformers(config.pop("transform", {}))
            if keys := set(fetcher_transformers).intersection(translator_transformers):
                msg = f"Transformers for {len(keys)} sources also defined on the fetcher level: {keys}."
                raise ValueError(msg)
            translator_config["transformers"] = translator_transformers | fetcher_transformers

            ans = self.clazz(
                fetcher,
                mapper=mapper,
                **translator_config,
            )

            ans._config_metadata = config_metadata
            return ans

    def load_toml_file(self, path: str) -> dict[str, Any]:
        """Read a TOML file from `path` with the current :attr:`.Metaconf.env` settings.

        Args:
            path: Path to file.

        Returns:
            A dict parsed from `path`.

        See Also:
            :func:`.load_toml_file`
        """
        env = self.metaconf.env
        return load_toml_file(
            path,
            allow_interpolation=env.allow_interpolation,
            allow_nested=env.allow_nested,
            allow_blank=env.allow_blank,
        )

    def _handle_fetching(
        self,
        config: dict[str, Any],
        extra_fetchers: list[str],
        default_identifiers: list[list[str]],
    ) -> tuple[Fetcher[SourceType, IdType], Transformers[SourceType, IdType]]:
        multi_fetcher_kwargs = config.pop("MultiFetcher", {})

        fetchers: list[Fetcher[SourceType, IdType]] = []
        transformers: Transformers[SourceType, IdType] = {}

        if config:
            with _rethrow_with_file(self.file):
                fetchers.append(self._make_fetcher(default_identifiers[0], **config))  # Add primary fetcher

        for i, fetcher_file in enumerate(extra_fetchers, start=1):
            with _rethrow_with_file(fetcher_file):
                fetcher_config = self.load_toml_file(fetcher_file)
                _check_allowed_keys(["fetching", "transform"], actual=fetcher_config, toml_path="<root>")
                fetcher = self._make_fetcher(default_identifiers[i], **fetcher_config["fetching"])
                new_transformers = self._handler_transformers(fetcher_config.get("transform", {}))

                if keys := set(new_transformers).intersection(transformers):
                    msg = f"Transformers for {len(keys)} sources were already defined in another fetcher file: {keys}."
                    raise ValueError(msg)
                transformers.update(new_transformers)
            fetchers.append(fetcher)

        if not fetchers:
            raise ConfigurationError(
                f"At least one [fetching]-section is required. Add it to '{self.file}',"
                " or as an auxiliary configuration.",
            )

        retval: Fetcher[SourceType, IdType]
        if len(fetchers) == 1:
            if multi_fetcher_kwargs and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(
                    f"MultiFetcher arguments {multi_fetcher_kwargs} are ignored; only one fetcher defined."
                )
            retval = fetchers[0]
        else:
            retval = MultiFetcher(*fetchers, **multi_fetcher_kwargs)
        return retval, transformers

    @classmethod
    def _make_mapper(cls, parent_section: str, config: dict[str, Any]) -> Mapper[Any, Any, Any] | None:
        if "mapping" not in config:
            return None  # pragma: no cover

        config = config.pop("mapping")
        for_fetcher = parent_section.startswith("fetching")
        if for_fetcher:
            config = {**AbstractFetcher.default_mapper_kwargs(), **config}

        return cls.MAPPER_FACTORY(config, for_fetcher)

    @classmethod
    def _make_cache_access(cls, config: dict[str, Any]) -> CacheAccess[Any, Any]:
        return cls.CACHE_ACCESS_FACTORY(config.pop("type"), config)

    @classmethod
    def _make_fetcher(cls, identifiers: list[str], **config: Any) -> AbstractFetcher[SourceType, IdType]:
        mapper = cls._make_mapper("fetching", config) if "mapping" in config else None
        cache_access = cls._make_cache_access(config.pop("cache")) if "cache" in config else None

        if len(config) == 0:  # pragma: no cover
            raise ConfigurationError("Fetcher implementation section missing.")
        if len(config) > 1:  # pragma: no cover
            raise ConfigurationError(f"Multiple fetcher implementations specified in the same file: {sorted(config)}")

        clazz, kwargs = next(iter(config.items()))

        kwargs["identifiers"] = kwargs.get("identifiers", identifiers)
        kwargs["mapper"] = mapper
        kwargs["cache_access"] = cache_access
        return cls.FETCHER_FACTORY(clazz, kwargs)

    @classmethod
    def _handler_transformers(cls, per_source: dict[SourceType, dict[str, Any]]) -> Transformers[SourceType, IdType]:
        transformers = {}

        for source, config in per_source.items():
            if len(config) != 1:
                raise ConfigurationError(
                    "Transformation config must be specified as [transform.<source>.<transformer-class>] sections."
                )
            clazz, kwargs = next(iter(config.items()))
            transformers[source] = cls.TRANSFORMER_FACTORY(clazz, kwargs)
        return transformers


def _make_default_translations(
    out: dict[str, Any],
    config: dict[str, Any],
) -> None:
    _check_allowed_keys(["fmt", "overrides"], actual=config, toml_path="translator.unknown_ids")

    if "fmt" in config:
        out["default_fmt"] = config.pop("fmt")
    if "overrides" in config:
        shared, specific = _split_overrides(config.pop("overrides"))
        out["default_fmt_placeholders"] = InheritedKeysDict(specific, default=shared)


def _check_allowed_keys(allowed: Iterable[str], *, actual: Iterable[str], toml_path: str) -> None:
    bad_keys = set(actual).difference(allowed)
    if bad_keys:
        raise ValueError(f"Forbidden keys {sorted(bad_keys)} in [{toml_path}]-section.")


def _split_overrides(overrides: Any) -> Any:
    specific = {k: v for k, v in overrides.items() if isinstance(v, dict)}
    shared = {k: v for k, v in overrides.items() if k not in specific}
    return shared, specific


def _identifier_from_config_metadata(config_metadata: ConfigMetadata) -> list[list[str]]:
    # Use the config filename and sha hash as the default keys
    return list(map(lambda t: [t[0].name, t[1]], (config_metadata.main, *config_metadata.extra_fetchers)))


@contextmanager
def _rethrow_with_file(file: str) -> Generator[None, None, None]:
    try:
        yield
    except Exception as e:
        if isinstance(e, ConfigurationError):
            e.add_note(f"    raised when parsing file: {Path(file).resolve()}")
            raise
        else:
            msg = f"{type(e).__name__}: {e}\n    raised when parsing file: {Path(file).resolve()}"
            raise ConfigurationError(msg) from e
