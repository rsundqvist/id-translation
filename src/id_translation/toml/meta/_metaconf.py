import logging
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Self

from rics.paths import AnyPath, any_path_to_path

from .._load_toml import _rethrow_with_file, load_toml_file
from ..exceptions import ConfigFileError

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")


@dataclass(frozen=True)
class EnvConf:
    """Control environment-variable interpolation.

    All keys are forwarded to :func:`~id_translation.toml.load_toml_file`.
    """

    allow_interpolation: bool = True
    allow_blank: bool = False
    allow_nested: bool = False

    @classmethod
    def from_dict(cls, config: dict[str, bool]) -> Self:
        """Construct environment interpolation configuration object from a dict.

        Args:
            config: Dict representation of an ``EnvConf``.

        Returns:
            A new ``EnvConf`` instance.
        """
        return cls(**config)


@dataclass(frozen=True)
class EquivalenceConf:
    """Determines how equivalence between configuration files is determined.

    .. seealso::

       The :class:`~id_translation.toml.meta.ConfigMetadata` class.
    """

    python_version: str = "{v.major}.{v.minor}.{v.micro}"
    """Used to format the ``'python_version'`` version using ``v=sys.version_info``."""
    extra_packages: list[str] = field(default_factory=list)
    """Additional package whose versions are used to determine :class:`~id_translation.toml.meta.ConfigMetadata` equivalence."""

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> Self:
        """Construct equivalence configuration object from a dict.

        Args:
            config: Dict representation of an ``EquivalenceConf``.

        Returns:
            A new ``EquivalenceConf`` instance.

        Raises:
            TypeError: If ``extra_packages`` is not a list.
        """
        config = dict(config)
        extra_packages = config.pop("extra_packages", [])
        if not isinstance(extra_packages, list):  # A string or table would be spread into its characters or keys.
            raise TypeError(f"bad equivalence.extra_packages={extra_packages!r}: expected list[str]")
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

    The sample above comes from the
    https://github.com/rsundqvist/id-translation-project/tree/master/demo/bci-id-translation demo.

    """

    env: EnvConf = field(default_factory=EnvConf)
    """Controls how and if variable substitution (on the form ``${VAR}``) is performed. See :class:`~id_translation.toml.meta.EnvConf`. """

    equivalence: EquivalenceConf = field(default_factory=EquivalenceConf)
    """Controls how equivalence checks are performed. See :class:`~id_translation.toml.meta.EquivalenceConf`."""

    def as_dict(self) -> dict[str, Any]:
        """Return a dict representation of `self`."""
        return asdict(self)

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> Self:
        """Construct meta configuration object from a dict.

        Args:
            config: Dict representation of a ``Metaconf``.

        Returns:
            A new ``Metaconf`` instance.

        Raises:
            TypeError: For unknown top-level keys.
            TypeError: If ``[env]`` or ``[equivalence]`` is not a table.
            TypeError: If ``[env]`` or ``[equivalence]`` has an unknown key.
            TypeError: If ``equivalence.extra_packages`` is not a list.
        """
        config = dict(config)
        env = config.pop("env", {})
        equivalence = config.pop("equivalence", {})

        if config:
            raise TypeError(f"Unknown keys: {sorted(config)}")
        for key, value in (("env", env), ("equivalence", equivalence)):
            if not isinstance(value, dict):
                raise TypeError(f"bad {key}={value!r}: expected a table")

        return cls(
            env=EnvConf.from_dict(env),
            equivalence=EquivalenceConf.from_dict(equivalence),
        )

    @classmethod
    def from_path_or_default(cls, path: AnyPath) -> Self:
        """Read TOML configuration or return default configuration.

        Raises:
            ~id_translation.toml.exceptions.ConfigFileError: If the file is not valid TOML, or has unknown keys or
                values of the wrong type. The hint names the file.
            OSError: If the file exists but cannot be read.
        """
        path = any_path_to_path(path)
        if not path.exists():
            return cls()

        config = load_toml_file(path)
        with _rethrow_with_file(path):
            try:
                rv = cls.from_dict(config)
                rv._check_types()  # Validate the TOML path; type checkers handle the rest.
            except TypeError as e:  # From the checks above, of the file's own keys and values.
                raise ConfigFileError(f"{type(e).__name__}: {e}") from e
        return rv

    def _check_types(self) -> None:
        self._check_env_types()
        self._check_equivalence_types()

    def _check_env_types(self) -> None:
        env = self.env
        if not isinstance(env.allow_interpolation, bool):
            raise TypeError(f"bad {env.allow_interpolation=}: expected bool")
        if not isinstance(env.allow_nested, bool):
            raise TypeError(f"bad {env.allow_nested=}: expected bool")
        if not isinstance(env.allow_blank, bool):
            raise TypeError(f"bad {env.allow_blank=}: expected bool")

    def _check_equivalence_types(self) -> None:
        equivalence = self.equivalence

        # Check Python version string.
        if not isinstance(equivalence.python_version, str):
            raise TypeError(f"bad {equivalence.python_version=}: expected str")
        try:
            equivalence.python_version.format(v=sys.version_info)
        except (AttributeError, IndexError, KeyError, TypeError, ValueError) as e:
            raise TypeError(f"bad {equivalence.python_version=}: {e!r}") from e

        # Check extra packages.
        if not isinstance(equivalence.extra_packages, list):
            raise TypeError(f"bad {equivalence.extra_packages=}: expected list[str]")

        if equivalence.extra_packages:
            try:
                from packaging.utils import InvalidName, canonicalize_name  # noqa: PLC0415
            except ImportError:  # Missing, or older than 23.2 (no InvalidName); the check is best-effort.
                return

            for name in equivalence.extra_packages:
                try:
                    canonicalize_name(name, validate=True)  # Checks the type, too.
                except (InvalidName, TypeError) as e:
                    raise TypeError(f"bad {equivalence.extra_packages=}: {e}") from e
