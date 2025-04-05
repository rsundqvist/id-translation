import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Self

from .._load_toml import load_toml_file

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")


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
