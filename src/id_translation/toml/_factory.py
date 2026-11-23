import logging
from collections.abc import Callable, Iterable
from inspect import isabstract, signature
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeAlias, get_origin

from rics.collections.dicts import InheritedKeysDict
from rics.collections.misc import as_list
from rics.env.read import read_bool
from rics.misc import get_by_full_name
from rics.types import AnyPath

from id_translation import fetching
from id_translation._utils import add_hints, type_name
from id_translation.fetching import AbstractFetcher, CacheAccess, Fetcher, MultiFetcher
from id_translation.mapping import Mapper
from id_translation.transform import as_transformer
from id_translation.transform.types import Transformer
from id_translation.types import IdType, NameType, SourceType

from . import factories as cf
from ._load_toml import _rethrow_with_file, load_toml_file
from .exceptions import ConfigFileError
from .factories._initialize import expect_table
from .factories._mapper import _check_shape as _check_mapping_shape
from .meta import ConfigMetadata, Metaconf

if TYPE_CHECKING:
    from id_translation import Translator


SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS = "ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS"


class TranslatorFactory(Generic[NameType, SourceType, IdType]):
    """Create a :class:`~id_translation.Translator` from TOML inputs."""

    FetcherFactory: TypeAlias = Callable[[str, dict[str, Any]], Fetcher[Any, Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.FETCHER_FACTORY`."""

    FETCHER_FACTORY: ClassVar[FetcherFactory] = cf.default_fetcher_factory
    """A callable ``(clazz, config) -> Fetcher``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.FetcherFactory` implementation to customize.
    The default creates an :class:`~id_translation.fetching.AbstractFetcher`; a custom factory may create any
    :class:`~id_translation.fetching.Fetcher`.

    An implementation may raise a :class:`~id_translation.toml.exceptions.ConfigFileError` for a section that breaks its own rules. Any
    other error, such as an :class:`ImportError` for a missing driver or an :class:`OSError` for a refused connection,
    propagates as itself, with a hint naming the file.

    Args:
        clazz: Name of the fetcher type to create, e.g. ``'SqlFetcher'`` or ``'my.library.SuperFetcher'``.
        config: Keyword arguments for the fetcher: the keys of its section, plus arguments added by the factory.

    Returns:
        A :class:`~id_translation.fetching.Fetcher` instance.

    Raises:
        ~id_translation.toml.exceptions.ConfigFileError: If the default factory is given a `clazz` that cannot be
            imported, or that does not create an :class:`~id_translation.fetching.AbstractFetcher`.

    See Also:
        :ref:`translator-config-fetching`
    """

    MapperFactory: TypeAlias = Callable[[dict[str, Any], bool], Mapper[Any, Any, Any] | None]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.MAPPER_FACTORY`."""

    MAPPER_FACTORY: ClassVar[MapperFactory] = cf.default_mapper_factory
    """A callable ``(config, for_fetcher) -> Mapper | None``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.MapperFactory` implementation to customize.

    If ``None`` is returned, a suitable default is used instead. A custom factory skips the default factory's shape
    checks of the section's contents. For a ``[fetching.mapping]``-section it receives the fetcher defaults (a
    ``score_function`` and ``overrides``) merged under the section's own keys.

    Args:
        config: Keyword arguments for the :class:`~id_translation.mapping.Mapper`.
        for_fetcher: Flag indicating that the :class:`~id_translation.mapping.Mapper` returned will be used by an
            :class:`~id_translation.fetching.AbstractFetcher` instance.

    Returns:
        A :class:`~id_translation.mapping.Mapper` instance or ``None``.

    Raises:
        ~id_translation.toml.exceptions.ConfigFileError: If the default factory is given a section it cannot use, e.g.
            context-specific overrides in ``[translator.mapping]``. An error from the
            :class:`~id_translation.mapping.Mapper` itself, such as a :class:`TypeError` for an unknown key, propagates
            as itself.

    See Also:
        :ref:`translator-config-mapping`
    """

    TransformerFactory: TypeAlias = Callable[[str, dict[str, Any]], Transformer[Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.TRANSFORMER_FACTORY`."""

    TRANSFORMER_FACTORY: ClassVar[TransformerFactory] = cf.default_transformer_factory
    """A callable ``(clazz, config) -> Transformer``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.TransformerFactory` implementation to customize.

    An implementation may raise a :class:`~id_translation.toml.exceptions.ConfigFileError` for a section that breaks its own rules. Any
    other error, such as an :class:`ImportError` for a missing optional dependency, propagates as itself, with a hint
    naming the file.

    Args:
        clazz: Type of :class:`~id_translation.transform.types.Transformer` to create.
        config: Keyword arguments for the transformer class.

    Returns:
        A :class:`~id_translation.transform.types.Transformer` instance.

    Raises:
        ~id_translation.toml.exceptions.ConfigFileError: If `clazz` cannot be imported, or does not create a
            :class:`~id_translation.transform.types.Transformer`.

    See Also:
        :ref:`translator-config-transform`
    """

    CacheAccessFactory: TypeAlias = Callable[[str, dict[str, Any]], CacheAccess[Any, Any]]
    """Signature for :attr:`~id_translation.toml.TranslatorFactory.CACHE_ACCESS_FACTORY`."""

    CACHE_ACCESS_FACTORY: ClassVar[CacheAccessFactory] = cf.default_cache_access_factory
    """A callable ``(clazz, config) -> CacheAccess``.

    Overwrite attribute with your own :attr:`~id_translation.toml.TranslatorFactory.CacheAccessFactory` implementation to customize.

    Args:
        clazz: Type of :class:`~id_translation.fetching.CacheAccess` to create.
        config: Keyword arguments for the cache class.

    Returns:
        A :class:`~id_translation.fetching.CacheAccess` instance.

    Raises:
        ~id_translation.toml.exceptions.ConfigFileError: If `clazz` cannot be imported, or does not create a
            :class:`~id_translation.fetching.CacheAccess`.
    """

    TOP_LEVEL_KEYS = ("translator", "fetching", "unknown_ids", "transform")
    """Top-level keys allowed in the main configuration file."""

    def __init__(
        self,
        file: AnyPath,
        fetchers: AnyPath | Iterable[AnyPath],
        clazz: type["Translator[NameType, SourceType, IdType]"] | None = None,
        suppress_optional_fetcher_init_errors: bool | None = None,
    ) -> None:
        from id_translation import Translator  # noqa: PLC0415

        # Expanded once, here: every later read (fingerprint, metaconf.toml, the files themselves) uses these.
        self.file = str(Path(file).expanduser())
        fetcher_paths: list[AnyPath] = as_list(fetchers)  # A bare path is one path, not characters.
        self.extra_fetchers = [str(Path(p).expanduser()) for p in fetcher_paths]
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
        config_metadata = ConfigMetadata.from_toml_paths(self.file, self.extra_fetchers, clazz=self.clazz)
        with _rethrow_with_file(self.file):
            config = self.load_toml_file(self.file)
            _check_sections(self.TOP_LEVEL_KEYS, actual=config)
            # Before the fetchers: building one may be slow or fail, which would hide a typo here.
            _check_allowed_keys(self.TOP_LEVEL_KEYS, actual=config, toml_path="<root>")
            _check_allowed_keys(self._translator_keys(), actual=config.get("translator", {}), toml_path="translator")

        fetcher = self._handle_fetching(
            config.pop("fetching", {}),
            self.extra_fetchers,
            _identifier_from_config_metadata(config_metadata),
        )

        with _rethrow_with_file(self.file):
            translator_config = config.pop("translator", {})
            mapper = self._make_mapper("translator", translator_config)
            _make_default_translations(translator_config, config.pop("unknown_ids", {}))

            # Only the main file has a top-level [transform]-section. It belongs to the Translator and may transform any
            # source; a fetcher's own [fetching.transform]-section belongs to that fetcher. See `_handle_fetching`.
            main_transform = self._handler_transformers(config.pop("transform", {}), section="transform")
            translator_config["transformers"] = {s: as_transformer(chain) for s, chain in main_transform.items()}

            translator = self.clazz(fetcher, mapper=mapper, **translator_config)

        translator._config_metadata = config_metadata
        return translator

    def _translator_keys(self) -> list[str]:
        from id_translation import Translator  # noqa: PLC0415

        # Arguments that other sections provide are not keys here. A subclass's own arguments are; one that takes
        # `**kwargs` hides the base arguments from its own signature.
        from_other_sections = {"fetcher", "mapper", "default_fmt", "default_fmt_placeholders", "transformers"}
        keywords = {
            p.name
            for cls in (Translator, get_origin(self.clazz) or self.clazz)
            for p in signature(cls).parameters.values()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
        }
        return ["mapping", *sorted(keywords - from_other_sections)]

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
    ) -> Fetcher[SourceType, IdType]:
        multi_fetcher_kwargs = config.pop("MultiFetcher", {})
        with _rethrow_with_file(self.file):
            expect_table(multi_fetcher_kwargs, "fetching.MultiFetcher")
            allowed = [p.name for p in signature(MultiFetcher).parameters.values() if p.kind is p.KEYWORD_ONLY]
            _check_allowed_keys(allowed, actual=multi_fetcher_kwargs, toml_path="fetching.MultiFetcher")

        # Each fetcher carries its own [fetching.transform]-section, so whatever discards or outranks a fetcher, at
        # construction or at discovery, takes its transformers with it.
        fetchers: list[Fetcher[SourceType, IdType]] = []

        if config:
            with _rethrow_with_file(self.file):
                fetcher = self._make_fetcher(default_identifiers[0], config, main=True)
            assert not isinstance(fetcher, Exception), "the main fetcher cannot be optional"  # noqa: S101
            fetchers.append(fetcher)  # Add primary fetcher

        for i, fetcher_file in enumerate(extra_fetchers, start=1):
            fetcher_config = self._load_auxiliary_file(fetcher_file)
            with _rethrow_with_file(fetcher_file):
                fetcher = self._make_fetcher(default_identifiers[i], fetcher_config["fetching"])

            if isinstance(fetcher, Exception):
                transform = fetcher_config["fetching"].get("transform", {})
                self._log_optional_fetcher_init_error(fetcher, fetcher_file, transform)
                continue

            fetchers.append(fetcher)

        if not fetchers:
            if extra_fetchers:  # The main file declares none: a main fetcher cannot be discarded.
                raise ConfigFileError(
                    "All [fetching]-sections were discarded as optional; see the logged errors.",
                    hints=[f"In file: {Path(f).resolve()}" for f in extra_fetchers],
                )

            raise ConfigFileError(
                f"At least one [fetching]-section is required. Add it to '{self.file}', or as an auxiliary configuration.",
                hints=f"In file: {Path(self.file).resolve()}",
            )

        retval: Fetcher[SourceType, IdType]
        # Counted as declared, so a fetcher discarded at construction doesn't change the type or drop these settings.
        if bool(config) + len(extra_fetchers) == 1:
            if multi_fetcher_kwargs:
                with _rethrow_with_file(self.file):
                    MultiFetcher(**multi_fetcher_kwargs)  # Unused; raises for values that a second fetcher would hit.
                if self.logger.isEnabledFor(logging.DEBUG):
                    self.logger.debug(
                        f"MultiFetcher arguments {multi_fetcher_kwargs} are ignored; only one fetcher defined."
                    )
            retval = fetchers[0]
        else:
            with _rethrow_with_file(self.file):
                retval = MultiFetcher(*fetchers, **multi_fetcher_kwargs)
        return retval

    def _load_auxiliary_file(self, fetcher_file: str) -> dict[str, Any]:
        with _rethrow_with_file(fetcher_file):
            fetcher_config = self.load_toml_file(fetcher_file)
            if "transform" in fetcher_config:
                raise ConfigFileError(
                    "A top-level [transform]-section is allowed in the main file only.",
                    hints="Use [fetching.transform.<source>.<transformer-class>]: transformers in an auxiliary file"
                    " belong to its fetcher, and apply to the sources that fetcher serves.",
                )
            _check_allowed_keys(["fetching"], actual=fetcher_config, toml_path="<root>")
            _check_sections(["fetching"], actual=fetcher_config)
            if "fetching" not in fetcher_config:
                raise ConfigFileError("A [fetching]-section is required.")
            if "MultiFetcher" in fetcher_config["fetching"]:
                raise ConfigFileError(f"[fetching.MultiFetcher] is allowed in the main file only: '{self.file}'.")
        return fetcher_config

    def _log_optional_fetcher_init_error(
        self,
        exception: BaseException,
        fetcher_file: str,
        transform: dict[SourceType, Any] | None = None,
    ) -> None:
        from id_translation._utils import DOC_LINK  # noqa: PLC0415

        reason = f"{SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true` or `suppress_optional_fetcher_init_errors=True"
        url = DOC_LINK + "documentation/translator-config.html#optional-fetchers"
        # The reverse mistake, a transformer for a source nobody serves, warns. This one would be silent.
        dropped = sorted(map(str, transform)) if transform else []
        self.logger.exception(
            f"Discarded optional fetcher in file '{fetcher_file}': {exception!r}."
            f"\nHint: Discarded since `optional=true` and `{reason}`."
            + (f"\nHint: Its [fetching.transform]-sections went with it: {dropped}." if dropped else "")
            + f"\nHint: See {url} for help.",
            exc_info=exception,
            extra={"fetcher_file": str(fetcher_file), "reason": str(exception), "dropped_transform": dropped},
        )

    @classmethod
    def _make_mapper(cls, parent_section: str, config: dict[str, Any]) -> Mapper[Any, Any, Any] | None:
        if "mapping" not in config:
            return None  # pragma: no cover

        config = config.pop("mapping")
        expect_table(config, f"{parent_section}.mapping")
        if "score_function_kwargs" in config:
            raise ConfigFileError(
                f"Key 'score_function_kwargs' is not allowed in [{parent_section}.mapping].",
                hints=f"Use a [{parent_section}.mapping.score_function.<name>] table for the score function's arguments.",
            )
        if cls.MAPPER_FACTORY is cf.default_mapper_factory:  # A custom factory's grammar is its own.
            # The user's section only: the defaults merged in below are not tables, e.g. overrides=InheritedKeysDict().
            _check_mapping_shape(config, section=f"{parent_section}.mapping")
        for_fetcher = parent_section.startswith("fetching")
        if for_fetcher:
            config = {**AbstractFetcher._default_mapper_kwargs(), **config}

        mapper = cls.MAPPER_FACTORY(config, for_fetcher)
        if mapper is not None:  # Means a suitable default.
            _check_factory_result(mapper, Mapper, hook="MAPPER_FACTORY", key=f"[{parent_section}.mapping]")
        return mapper

    @staticmethod
    def _pop_single_impl(config: dict[str, Any], *, what: str, section: str) -> tuple[str, dict[str, Any]]:
        if keys := sorted(key for key, value in config.items() if not isinstance(value, dict)):
            raise ConfigFileError(f"Expected only [{section}.'<type>']-sections in [{section}]; got keys {keys}.")
        if len(config) == 0:
            raise ConfigFileError(f"{what} implementation section missing.")
        if len(config) > 1:  # pragma: no cover
            raise ConfigFileError(
                f"Multiple {what.lower()} implementations specified in the same file: {sorted(config)}"
            )

        return next(iter(config.items()))

    def _make_fetcher(
        self,
        __identifiers: list[str],
        config: dict[str, Any],
        *,
        main: bool = False,
    ) -> Fetcher[SourceType, IdType] | Exception:
        config = dict(config)  # Popped below; the caller reads the transform section of a discarded fetcher.
        _check_fetcher_declared(config)
        mapper = self._make_mapper("fetching", config) if "mapping" in config else None
        cache = None
        if "cache" in config:
            expect_table(config["cache"], "fetching.cache")
            cache = self._pop_single_impl(config.pop("cache"), what="Cache", section="fetching.cache")
        transform = config.pop("transform", {})
        self._check_transformers_shape(transform, section="fetching.transform")  # Also for a fetcher discarded below.
        if transform and not config:
            raise ConfigFileError(
                "A [fetching.transform]-section belongs to a fetcher declared in the same file, but there is none.",
                hints="Declare the fetcher here, or use a top-level [transform] in the main file to transform any source.",
            )

        clazz, kwargs = self._pop_single_impl(config, what="Fetcher", section="fetching")
        sections = {"mapper": "[fetching.mapping]", "cache_access": "[fetching.cache.'<type>']"}
        if keys := sorted(key for key in sections if key in kwargs):
            raise ConfigFileError(
                f"Keys {keys} are not allowed in [fetching.{clazz}].",
                hints=[f"Configure the '{key}' in a {sections[key]} section instead." for key in keys],
            )

        kwargs["identifiers"] = kwargs.get("identifiers", __identifiers)
        kwargs["mapper"] = mapper
        kwargs["cache_access"] = None

        if not isinstance(kwargs.get("optional", False), bool):
            raise ConfigFileError(f"Bad optional of type {type_name(kwargs['optional'])}; expected a bool.")
        is_optional = kwargs.get("optional") is True
        if is_optional and main:
            raise ConfigFileError(
                "The fetcher in the main file cannot be optional.",
                hints="Move it to an auxiliary file (`extra_fetchers`) to make it optional.",
            )

        fetcher = self._construct_fetcher(clazz, kwargs, cache, is_optional=is_optional)
        if isinstance(fetcher, Exception):
            return fetcher

        _check_factory_result(fetcher, Fetcher, hook="FETCHER_FACTORY", key=repr(clazz))

        if main and fetcher.optional:
            # After the key check above (is_optional); this catches optional-by-default.
            raise ConfigFileError(
                "The fetcher in the main file cannot be optional.",
                hints="Move it to an auxiliary file (`extra_fetchers`) to make it optional.",
            )

        if not isinstance(fetcher, AbstractFetcher):
            if transform:
                raise ConfigFileError(
                    f"A [fetching.transform]-section requires an AbstractFetcher, but {clazz} is not one.",
                    hints="Override Fetcher.get_transformer(), or use the main file's top-level [transform].",
                )
            return fetcher

        # Built after construction: a fetcher discarded as optional takes its section with it, unbuilt. Its transformers
        # often come from the same missing package that made the fetcher fail. The shape was checked above.
        fetcher._transform_config = self._handler_transformers(transform, section="fetching.transform")
        return fetcher

    def _construct_fetcher(
        self,
        clazz: str,
        kwargs: dict[str, Any],
        cache: tuple[str, dict[str, Any]] | None,
        *,
        is_optional: bool,
    ) -> Fetcher[SourceType, IdType] | Exception:
        # The emergency hatch: anything from the class lookup on, an unresolvable section key or a failing cache
        # included. A factory result of the wrong type, like the checks in _make_fetcher(), is never discarded.
        discard = is_optional and self.suppress_optional_fetcher_init_errors
        # The variable only discards an optional fetcher that fails to construct, so only hint here.
        suppress_hint = f"Setting {SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS}=true may help temporarily."

        if cache is not None:
            try:
                cache_access = type(self).CACHE_ACCESS_FACTORY(*cache)
            except Exception as e:
                if discard:
                    return e
                if is_optional:
                    add_hints(e, suppress_hint)
                raise
            _check_factory_result(cache_access, CacheAccess, hook="CACHE_ACCESS_FACTORY", key=repr(cache[0]))
            kwargs["cache_access"] = cache_access

        try:
            return type(self).FETCHER_FACTORY(clazz, kwargs)
        except Exception as e:
            if discard:
                return e
            if isinstance(e, TypeError):
                add_hints(e, self._fetcher_type_hints(clazz, kwargs))
            if is_optional:
                add_hints(e, suppress_hint)
            raise

    @classmethod
    def _fetcher_type_hints(cls, clazz: str, kwargs: dict[str, Any]) -> list[str]:
        if cls.FETCHER_FACTORY is not cf.default_fetcher_factory:
            return []  # A custom factory's errors are its own.
        try:
            fetcher_class = get_by_full_name(clazz, fetching)
        except Exception:
            return []

        params = ["identifiers", "mapper", "cache_access"]  # Passed to every fetcher; see _make_fetcher().
        is_class = isinstance(fetcher_class, type) and not isabstract(fetcher_class)
        if is_class and issubclass(fetcher_class, AbstractFetcher):
            if _rejects_only(fetcher_class, kwargs, params):
                return [
                    f"{clazz} must accept the keyword arguments {params} and pass them on to AbstractFetcher.__init__()."
                ]
        elif is_class and issubclass(fetcher_class, Fetcher):
            return [
                f"The default TranslatorFactory.FETCHER_FACTORY creates AbstractFetchers only. Set it to a function"
                f" (clazz, config) -> Fetcher that creates {clazz}; `config` holds the keys of its section, plus {params}."
            ]
        return []

    @classmethod
    def _handler_transformers(
        cls, per_source: dict[SourceType, dict[str, Any]], *, section: str
    ) -> dict[SourceType, list[Transformer[IdType]]]:
        """Read a ``[transform]`` or ``[fetching.transform]`` section into ``{source: chain}``, in declaration order.

        Two scopes, by design. The main file's top-level ``[transform]`` belongs to the ``Translator`` and may
        transform any source. A ``[fetching.transform]`` belongs to the fetcher declared next to it and applies only to
        sources that fetcher serves, so it goes wherever that fetcher goes: discarded, outranked, or copied. An
        auxiliary file has no top-level ``[transform]``: transforming another fetcher's sources from one is a
        configuration violation, not a feature.
        """
        cls._check_transformers_shape(per_source, section=section)
        return {
            source: [cls.TRANSFORMER_FACTORY(clazz, kwargs) for clazz, kwargs in config.items()]
            for source, config in per_source.items()
        }

    @staticmethod
    def _check_transformers_shape(per_source: Any, *, section: str) -> None:
        """Raise for a malformed section without importing anything, so that it can be checked for any fetcher."""
        if not isinstance(per_source, dict):
            raise ConfigFileError(
                f"The [{section}]-section must contain [{section}.<source>.<transformer-class>] subsections."
                f"\nGot: {section} = {per_source!r}."
            )

        for source, config in per_source.items():
            if not isinstance(config, dict) or not config:
                raise ConfigFileError(
                    f"Transformation config must be specified as [{section}.<source>.<transformer-class>] sections."
                    f"\nGot: {source!r} = {config!r}."
                )
            if bad := sorted(clazz for clazz, kwargs in config.items() if not isinstance(kwargs, dict)):
                raise ConfigFileError(
                    f"Init arguments must be [{section}.{source}.<transformer-class>] tables; got values for {bad}."
                )


def _make_default_translations(
    out: dict[str, Any],
    config: dict[str, Any],
) -> None:
    _check_allowed_keys(["fmt", "overrides"], actual=config, toml_path="unknown_ids")

    if "fmt" in config:
        out["default_fmt"] = config.pop("fmt")
    if "overrides" in config:
        expect_table(config["overrides"], "unknown_ids.overrides")
        shared, specific = _split_overrides(config.pop("overrides"))
        out["default_fmt_placeholders"] = InheritedKeysDict(specific, default=shared)


def _check_factory_result(value: Any, expected: type, *, hook: str, key: str) -> None:
    # A factory that falls through returns None, which downstream means a default: no cache, or a TestFetcher.
    if not isinstance(value, expected):
        raise TypeError(f"{hook} returned a '{type_name(value)}' for {key}; expected a {expected.__name__}.")


def _check_fetcher_declared(config: dict[str, Any]) -> None:
    """Raise before building anything if a file has ``[fetching.mapping]`` or ``[fetching.cache]`` but no fetcher."""
    shared = [f"[fetching.{key}]" for key in ("mapping", "cache") if key in config]
    if shared and not set(config).difference(("mapping", "cache", "transform")):
        raise ConfigFileError(
            "Fetcher implementation section missing.",
            hints=f"Declare the fetcher for {' and '.join(shared)} in the same file.",
        )


def _check_allowed_keys(allowed: Iterable[str], *, actual: Iterable[str], toml_path: str) -> None:
    bad_keys = set(actual).difference(allowed)

    if bad_keys:
        hints = []
        if toml_path == "<root>" and "mapping" in bad_keys:
            sections = [f"[{parent}.mapping]" for parent in ("translator", "fetching") if parent in allowed]
            hints.append(f"Use {' or '.join(sections)}.")
        if toml_path == "<root>" and list(allowed) == ["fetching"]:
            hints.append("Auxiliary files may only contain a [fetching]-section.")
        if toml_path == "translator":
            translator_hints = {
                "default_fmt": "Use [unknown_ids] fmt.",
                "default_fmt_placeholders": "Use [unknown_ids.overrides]: keys from its .default table go at the top"
                " level, and each .specific.<source> table becomes [unknown_ids.overrides.<source>].",
                "mapper": "Use [translator.mapping].",
                "transformers": "Delete the transformers key to keep current results, or move it to"
                " [transform.'<source>'] to apply the transformers.",
            }
            hints.extend(hint for key, hint in translator_hints.items() if key in bad_keys)
        where = "at the top level" if toml_path == "<root>" else f"in [{toml_path}]-section"
        raise ConfigFileError(f"Forbidden keys {sorted(bad_keys)} {where}.", hints=hints)


def _check_sections(sections: Iterable[str], *, actual: dict[str, Any]) -> None:
    if values := sorted(key for key in sections if key in actual and not isinstance(actual[key], dict)):
        raise ConfigFileError(f"Top-level keys {values} must be sections, e.g. [{values[0]}].")


def _split_overrides(overrides: Any) -> Any:
    specific = {k: v for k, v in overrides.items() if isinstance(v, dict)}
    shared = {k: v for k, v in overrides.items() if k not in specific}
    return shared, specific


def _identifier_from_config_metadata(config_metadata: ConfigMetadata) -> list[list[str]]:
    # Use the config filename and sha hash as the default keys
    return list(map(lambda t: [t[0].name, t[1]], (config_metadata.main, *config_metadata.extra_fetchers)))


def _rejects_only(fetcher_class: type, kwargs: dict[str, Any], params: list[str]) -> bool:
    """Return ``True`` if `fetcher_class` accepts `kwargs` without `params`, but not with them."""
    try:
        sig = signature(fetcher_class)
        sig.bind(**{k: v for k, v in kwargs.items() if k not in params})
    except (TypeError, ValueError):
        return False  # The section is wrong too, or the signature is opaque; the error says what.
    try:
        sig.bind(**kwargs)
    except TypeError:
        return True
    return False
