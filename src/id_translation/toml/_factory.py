import logging
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeAlias

from rics.collections.dicts import InheritedKeysDict
from rics.env.read import read_bool
from rics.types import AnyPath

from id_translation.exceptions import ConfigurationError
from id_translation.fetching import AbstractFetcher, CacheAccess, Fetcher, MultiFetcher
from id_translation.mapping import Mapper
from id_translation.transform import as_transformer
from id_translation.transform.types import Transformer, Transformers
from id_translation.types import IdType, NameType, SourceType

from .._utils.emit_warning import emit_warning
from . import factories as cf
from ._load_toml import load_toml_file
from .meta import ConfigMetadata, Metaconf

if TYPE_CHECKING:
    from id_translation import Translator


SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS = "ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS"


class TranslatorFactory(Generic[NameType, SourceType, IdType]):
    """Create a :class:`~id_translation.Translator` from TOML inputs."""

    FetcherFactory: TypeAlias = Callable[[str, dict[str, Any]], AbstractFetcher[Any, Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.FETCHER_FACTORY`."""

    FETCHER_FACTORY: FetcherFactory = staticmethod(cf.default_fetcher_factory)
    """A callable ``(clazz, config) -> AbstractFetcher``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.FetcherFactory` implementation to customize.

    Args:
        clazz: Type of :class:`~id_translation.fetching.AbstractFetcher` to create.
        config: Keyword arguments for the fetcher class.

    Returns:
        An :class:`~id_translation.fetching.AbstractFetcher` instance.

    Raises:
        exceptions.ConfigurationError: If `config` is invalid.
        TypeError: If `clazz` is not an :class:`~id_translation.fetching.AbstractFetcher` subtype.

    See Also:
        :ref:`translator-config-fetching`
    """

    MapperFactory: TypeAlias = Callable[[dict[str, Any], bool], Mapper[Any, Any, Any] | None]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.MAPPER_FACTORY`."""

    MAPPER_FACTORY: MapperFactory = cf.default_mapper_factory
    """A callable ``(config, for_fetcher) -> Mapper | None``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.MapperFactory` implementation to customize.

    If ``None`` is returned, a suitable default is used instead.

    Args:
        config: Keyword arguments for the :class:`~id_translation.mapping.Mapper`.
        for_fetcher: Flag indicating that the :class:`~id_translation.mapping.Mapper` returned will be used by an
            :class:`~id_translation.fetching.AbstractFetcher` instance.

    Returns:
        A :class:`~id_translation.mapping.Mapper` instance or ``None``.

    Raises:
        ~id_translation.exceptions.ConfigurationError: If `config` is invalid.

    See Also:
        :ref:`translator-config-mapping`
    """

    TransformerFactory: TypeAlias = Callable[[str, dict[str, Any]], Transformer[Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.TRANSFORMER_FACTORY`."""

    TRANSFORMER_FACTORY: TransformerFactory = cf.default_transformer_factory
    """A callable ``(clazz, config) -> Transformer``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.TransformerFactory` implementation to customize.

    Args:
        clazz: Type of :class:`~id_translation.transform.types.Transformer` to create.
        config: Keyword arguments for the transformer class.

    Returns:
        A :class:`~id_translation.transform.types.Transformer` instance.

    Raises:
        ~id_translation.exceptions.ConfigurationError: If `config` is invalid.

    See Also:
        :ref:`translator-config-transform`
    """

    CacheAccessFactory: TypeAlias = Callable[[str, dict[str, Any]], CacheAccess[Any, Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.CACHE_ACCESS_FACTORY`."""

    CACHE_ACCESS_FACTORY: CacheAccessFactory = cf.default_cache_access_factory
    """A callable ``(clazz, config) -> CacheAccess``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.CacheAccessFactory` implementation to customize.

    Args:
        clazz: Type of :class:`~id_translation.fetching.CacheAccess` to create.
        config: Keyword arguments for the cache class.

    Returns:
        A :class:`~id_translation.fetching.CacheAccess` instance.

    Raises:
        ~id_translation.exceptions.ConfigurationError: If `config` is invalid.
    """

    TOP_LEVEL_KEYS = ("translator", "fetching", "unknown_ids", "transform")
    """Top-level keys allowed in the main configuration file."""

    def __init__(
        self,
        file: AnyPath,
        fetchers: Iterable[AnyPath],
        clazz: type["Translator[NameType, SourceType, IdType]"] | None = None,
        suppress_optional_fetcher_init_errors: bool | None = None,
    ) -> None:
        from id_translation import Translator  # noqa: PLC0415

        self.file = str(file)
        self.extra_fetchers = list(map(str, fetchers))
        self.clazz: type[Translator[NameType, SourceType, IdType]] = clazz or Translator[NameType, SourceType, IdType]

        metaconf_path = Path(self.file).with_name("metaconf.toml")
        self._metaconf = Metaconf.from_path_or_default(metaconf_path)
        self.logger = logging.getLogger(__package__).getChild(type(self).__name__)

        if suppress_optional_fetcher_init_errors is None:
            suppress_optional_fetcher_init_errors = read_bool(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS)
        self.suppress_optional_fetcher_init_errors = suppress_optional_fetcher_init_errors

    @property
    def metaconf(self) -> Metaconf:
        """Returns the :class:`~id_translation.toml.meta.Metaconf` used by this factory."""
        return self._metaconf

    def create(self) -> "Translator[NameType, SourceType, IdType]":
        """Create :class:`~id_translation.Translator` instance."""
        config_metadata = ConfigMetadata.from_toml_paths(self.file, self.extra_fetchers, self.clazz)
        with _rethrow_with_file(self.file):
            config: dict[str, Any] = self.load_toml_file(self.file)

        fetcher, fetcher_file_transformers = self._handle_fetching(
            config.pop("fetching", {}),
            self.extra_fetchers,
            _identifier_from_config_metadata(config_metadata),
            config.pop("transform", {}),
        )

        with _rethrow_with_file(self.file):
            _check_allowed_keys(self.TOP_LEVEL_KEYS, actual=config, toml_path="<root>")
            translator_config = config.pop("translator", {})
            mapper = self._make_mapper("translator", translator_config)
            _make_default_translations(translator_config, config.pop("unknown_ids", {}))

            translator_config["transformers"] = self._chain_transformers(*fetcher_file_transformers)

            ans = self.clazz(
                fetcher,
                mapper=mapper,
                **translator_config,
            )

            ans._config_metadata = config_metadata
            return ans

    def load_toml_file(self, path: str) -> dict[str, Any]:
        """Read a TOML file from `path` with the current :attr:`Metaconf.env <id_translation.toml.meta.Metaconf.env>` settings.

        Args:
            path: Path to file.

        Returns:
            A dict parsed from `path`.

        See Also:
            :func:`~id_translation.toml.load_toml_file`
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
        main_transform: dict[SourceType, dict[str, Any]],
    ) -> tuple[Fetcher[SourceType, IdType], list[dict[SourceType, list[Transformer[IdType]]]]]:
        multi_fetcher_kwargs = config.pop("MultiFetcher", {})

        fetchers: list[Fetcher[SourceType, IdType]] = []
        # Gathered for the Translator, which owns all transformers; see `Translator.transformers`.
        transformers: list[dict[SourceType, list[Transformer[IdType]]]] = []

        main_discarded = False
        if config:
            with _rethrow_with_file(self.file, show_init_errors_hint=True):
                fetcher = self._make_fetcher(default_identifiers[0], **config)

            if isinstance(fetcher, Exception):
                self._log_optional_fetcher_init_error(fetcher, str(self.file), main_transform)
                main_discarded = True
            else:
                fetchers.append(fetcher)  # Add primary fetcher

        for i, fetcher_file in enumerate(extra_fetchers, start=1):
            # Config-shape errors go outside the hinted block: the suppress variable only skips a fetcher that
            # fails to construct, so it cannot help with a malformed file.
            with _rethrow_with_file(fetcher_file):
                fetcher_config = self.load_toml_file(fetcher_file)
                _check_allowed_keys(["fetching", "transform"], actual=fetcher_config, toml_path="<root>")
                if "fetching" not in fetcher_config:
                    raise ConfigurationError("A [fetching]-section is required.")

            with _rethrow_with_file(fetcher_file, show_init_errors_hint=True):
                fetcher = self._make_fetcher(default_identifiers[i], **fetcher_config["fetching"])

            transform = fetcher_config.get("transform", {})
            if isinstance(fetcher, Exception):
                self._log_optional_fetcher_init_error(fetcher, fetcher_file, transform)
                continue

            # After the discard check: a fetcher that fails to initialize takes its file's transformers with it.
            # Covers that discard only -- a child dropped later, by `MultiFetcher` discovery, has had this section
            # built long since.
            with _rethrow_with_file(fetcher_file):
                from_file = self._handler_transformers(transform)

            fetchers.append(fetcher)
            transformers.append(from_file)

        if not main_discarded:
            # The main file's, appended last to preserve the documented chaining order -- and dropped with the
            # primary fetcher when that fetcher is discarded at init. Outside the hinted block, which does not
            # apply to a bad section.
            with _rethrow_with_file(self.file):
                transformers.append(self._handler_transformers(main_transform))

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

    def _log_optional_fetcher_init_error(
        self,
        exception: BaseException,
        fetcher_file: str,
        transform: dict[SourceType, Any] | None = None,
    ) -> None:
        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        value = getenv(SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS)
        env = f"{SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}={value}"
        url = DOC_LINK + "documentation/translator-config.html#optional-fetchers"
        # The reverse mistake -- a transformer for a source nobody serves -- warns; this would be silent.
        dropped = sorted(map(str, transform)) if transform else []
        self.logger.exception(
            f"Discarded optional fetcher in file '{fetcher_file}': {exception!r}."
            f"\nHint: Discarded since `optional=true` and `{env}`."
            + (f"\nHint: Its [transform]-sections went with it: {dropped}." if dropped else "")
            + f"\nHint: See {url} for help.",
            exc_info=exception,
            extra={"fetcher_file": str(fetcher_file), "reason": str(exception), "dropped_transform": dropped},
        )

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

    def _make_fetcher(
        self,
        __identifiers: list[str],
        **config: Any,
    ) -> AbstractFetcher[SourceType, IdType] | Exception:
        mapper = self._make_mapper("fetching", config) if "mapping" in config else None
        cache_access = self._make_cache_access(config.pop("cache")) if "cache" in config else None

        if len(config) == 0:  # pragma: no cover
            raise ConfigurationError("Fetcher implementation section missing.")
        if len(config) > 1:  # pragma: no cover
            raise ConfigurationError(f"Multiple fetcher implementations specified in the same file: {sorted(config)}")

        clazz, kwargs = next(iter(config.items()))

        kwargs["identifiers"] = kwargs.get("identifiers", __identifiers)
        kwargs["mapper"] = mapper
        kwargs["cache_access"] = cache_access

        is_optional = kwargs.get("optional")
        if isinstance(is_optional, bool):
            # Only if ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS=true.
            is_optional = is_optional and self.suppress_optional_fetcher_init_errors
        else:
            is_optional = False

        try:
            return self.FETCHER_FACTORY(clazz, kwargs)
        except Exception as e:
            if is_optional:
                return e
            raise

    @classmethod
    def _handler_transformers(
        cls, per_source: dict[SourceType, dict[str, Any]]
    ) -> dict[SourceType, list[Transformer[IdType]]]:
        """Read one file's ``[transform]``-sections into ``{source: chain}``, in declaration order."""
        if not isinstance(per_source, dict):
            raise ConfigurationError(
                "The [transform]-section must contain [transform.<source>.<transformer-class>] subsections."
                f"\nGot: transform = {per_source!r}."
            )

        transformers: dict[SourceType, list[Transformer[IdType]]] = {}

        for source, config in per_source.items():
            if not isinstance(config, dict) or not config:
                raise ConfigurationError(
                    "Transformation config must be specified as [transform.<source>.<transformer-class>] sections."
                    f"\nGot: {source!r} = {config!r}."
                )
            transformers[source] = [cls.TRANSFORMER_FACTORY(clazz, kwargs) for clazz, kwargs in config.items()]
        return transformers

    @staticmethod
    def _chain_transformers(
        *levels: dict[SourceType, list[Transformer[IdType]]],
    ) -> Transformers[SourceType, IdType]:
        """Concatenate per-source chains across files, `levels` first to last."""
        chains: dict[SourceType, list[Transformer[IdType]]] = {}
        for level in levels:
            for source, transformers in level.items():
                chains.setdefault(source, []).extend(transformers)
        return {source: as_transformer(chain) for source, chain in chains.items()}


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

    if "mapping" in bad_keys:  # TODO(2.0.0): Remove this branch
        bad_keys.remove("mapping")
        emit_warning(
            "The top-level 'mapping' key is not used."
            "\nHint: You want [translator.mapping] or [fetching.mapping]."
            "\nWARNING: This will raise in `id-translation==2.0.0`.",
            FutureWarning,
        )

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
def _rethrow_with_file(
    file: str,
    *,
    show_init_errors_hint: bool = False,
) -> Generator[None, None, None]:
    try:
        yield
    except Exception as e:
        file_hint = f"In file: {Path(file).resolve()}"
        notes = [file_hint]
        if show_init_errors_hint:
            notes.append(f"Setting {SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true may help temporarily.")

        for hint in notes:
            e.add_note(f"Hint: {hint}")

        if isinstance(e, ConfigurationError):
            raise
        else:
            msg = f"{type(e).__name__}: {e}\n    raised when parsing file: {Path(file).resolve()}"
            raise ConfigurationError(msg) from e
