import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from ._base_metadata import BaseMetadata
from ._load_toml import load_toml_file

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")

if TYPE_CHECKING:
    from .. import Translator


@dataclass(frozen=True)
class EnvConf:
    """Control environment-variable interpolation.

    All keys are forwarded to :func:`.load_toml_file`.
    """

    allow_interpolation: bool = True
    allow_blank: bool = False
    allow_nested: bool = False

    @classmethod
    def from_dict(cls, config: dict[str, bool]) -> Self:
        """Construct environment interpolation configuration object from a dict.

        Args:
            config: Dict representation of a ``EnvConf`` to consume.

        Returns:
            A new ``EnvConf`` instance.
        """
        return cls(**config)


@dataclass(frozen=True)
class EquivalenceConf:
    """Determines how equivalence between configuration files is determined."""

    python_version: str = "{v.major}.{v.minor}.{v.micro}"
    """Used to format the ``'python_version'`` version using ``v=sys.version_info``."""
    extra_packages: list[str] = field(default_factory=list)
    """Additional package whose versions are used to determine :class:`ConfigMetadata` equivalence."""

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> Self:
        """Construct equivalence configuration object from a dict.

        Args:
            config: Dict representation of an ``EquivalenceConf`` to consume.

        Returns:
            A new ``EquivalenceConf`` instance.
        """
        extra_packages = config.pop("extra_packages", [])
        return cls(**config, extra_packages=[*extra_packages])


@dataclass(frozen=True)
class Metaconf:
    """Python representation of ``metaconf.toml`` file.

    The ``metaconf.toml`` file always lives next to the main configuration file. It determines how other configuration
    files are read and validated.

    .. code-block:: toml

        [env]
        allow_interpolation = true
        allow_nested = true
        allow_blank = false

        [equivalence]
        # python_version = "{v.major}.{v.minor}"  # Uncomment to allow any patch version
        extra_packages = ["bci-id-translation"]

    The sample above comes from the https://github.com/rsundqvist/id-translation-project/tree/master/demo/bci-id-translation demo.

    """

    env: EnvConf = field(default_factory=EnvConf)
    """Controls how and if variable substitution (on the form ``${VAR}``) is performed. See :class:`EnvConf`. """

    equivalence: EquivalenceConf = field(default_factory=EquivalenceConf)
    """Controls how equivalence checks are performed. See :class:`EquivalenceConf`."""

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> Self:
        """Construct meta configuration object from a dict.

        Args:
            config: Dict representation of a ``Metaconf`` to consume.

        Returns:
            A new ``Metaconf`` instance.
        """
        env = config.pop("env", {})
        equivalence = config.pop("equivalence", {})

        if config:
            raise TypeError(f"Unknown keys: {sorted(config)}")

        return cls(
            env=EnvConf.from_dict(env),
            equivalence=EquivalenceConf.from_dict(equivalence),
        )

    @classmethod
    def from_path_or_default(cls, path: Path | str) -> Self:
        """Read TOML configuration or return default configuration."""
        path = Path(str(path))
        config = load_toml_file(path) if path.exists() else {}
        return cls.from_dict(config)

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of `self`."""
        return asdict(self)


class ConfigMetadata(BaseMetadata):
    """Metadata pertaining to how a :class:`.Translator` instance was initialized from TOML configuration.

    Equivalence:
        Configs are equivalent if and only if...

        - They have the same top-level dependency versions, and
        - Use the same fully qualified class name, and
        - The main configuration is equal after parsing, and
        - They have the same number of auxiliary (`"extra"`) fetcher configurations, and
        - All auxiliary fetcher configurations are equal after parsing.

    The :class:`Metaconf` is not explicitly included in the equivalence check, but changing it will invalidate cached
    instances. Environment variable changes may also invalidate the cache if :attr:`EnvConf.allow_interpolation` is set
    and interpolations such as ``${VAR}`` are present.

    Args:
        main: Absolute path and fingerprint of the main translation configuration."
        extra_fetchers: Absolute path and fingerprint of configuration files for auxiliary fetchers.
        clazz: String representation of the class type.
        metaconf: A :class:`Metaconf` instance that determines, among other things, how other config paths are processed.
        kwargs: Forwarded to base class.
    """

    def __init__(
        self,
        main: tuple[Path, str],
        extra_fetchers: tuple[tuple[Path, str], ...],
        clazz: str,
        metaconf: Metaconf,
        **kwargs: Any,
    ) -> None:
        if "versions" not in kwargs:
            kwargs["versions"] = {
                "python": metaconf.equivalence.python_version.format(v=sys.version_info),
                **self.get_package_versions(metaconf.equivalence.extra_packages),
            }
        super().__init__(**kwargs)
        self.main = main
        self.extra_fetchers = extra_fetchers
        self.clazz = clazz
        self.metaconf = metaconf

    def _to_dict(self, to_json: dict[str, Any]) -> dict[str, Any]:
        return {
            "main": tuple(map(str, to_json.pop("main"))),
            "extra_fetchers": [tuple(map(str, t)) for t in to_json.pop("extra_fetchers")],
            "metaconf": to_json.pop("metaconf").as_dict(),
            "class": to_json.pop("clazz"),
        }

    @classmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        def to_path_tuple(args: list[str]) -> tuple[Path, str]:
            return Path(args[0]), args[1]

        return dict(
            main=to_path_tuple(from_json.pop("main")),
            extra_fetchers=tuple(map(to_path_tuple, from_json.pop("extra_fetchers"))),
            clazz=from_json.pop("class"),
            metaconf=Metaconf.from_dict(from_json.pop("metaconf")),
        )

    def _is_equivalent(self, other: BaseMetadata) -> str:  # pragma: no cover
        assert isinstance(other, ConfigMetadata)  # noqa: S101

        if self.clazz != other.clazz:
            return f"Class not equal. Expected '{self.clazz}', but got '{other.clazz}'"

        if self.main[1] != other.main[1]:
            return f"Main configuration changed. Expected fingerprint {self.main[1]}, but got {other.main[1]}"

        if self.metaconf != other.metaconf:
            return f"Meta configuration changed: {self.metaconf} != {other.metaconf}."

        if len(self.extra_fetchers) != len(other.extra_fetchers):
            return (
                f"Number of auxiliary fetchers changed. Expected {len(self.extra_fetchers)}"
                f" fetchers but got {len(other.extra_fetchers)}"
            )

        for i, (path, fingerprint) in enumerate(self.extra_fetchers):
            _, other_fingerprint = other.extra_fetchers[i]
            if fingerprint != other_fingerprint:
                return (
                    f"Configuration changed for auxiliary fetcher #{i} at {path}. "
                    f"Expected fingerprint {fingerprint}, but got {other_fingerprint}"
                )

        return ""

    @staticmethod
    def from_toml_paths(
        path: str,
        extra_fetchers: list[str],
        clazz: type["Translator[Any, Any, Any]"],
    ) -> "ConfigMetadata":
        """Convenience function for creating ``ConfigMetadata`` instances."""
        metaconf_path = str(Path(path).with_name("metaconf.toml"))
        metaconf = Metaconf.from_path_or_default(metaconf_path)

        def _create_path_tuple(str_path: str) -> tuple[Path, str]:
            p = Path(str_path).expanduser().absolute()
            content = load_toml_file(
                p,
                allow_interpolation=metaconf.env.allow_interpolation,
                allow_nested=metaconf.env.allow_nested,
                allow_blank=metaconf.env.allow_blank,
            )
            return p, sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()

        return ConfigMetadata(
            main=_create_path_tuple(path),
            extra_fetchers=tuple(map(_create_path_tuple, extra_fetchers)),
            clazz=clazz.__module__ + "." + clazz.__qualname__,  # Fully qualified name
            metaconf=metaconf,
        )
