import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Tuple, Type

try:
    import tomllib  # type: ignore
except ModuleNotFoundError:
    # PEP-680 compatibility layer for Python < 3.11, see https://peps.python.org/pep-0680/
    # Shamelessly stolen from https://github.com/hukkin/tomli#building-a-tomlitomllib-compatibility-layer
    import tomli as tomllib  # type: ignore

import pandas as pd

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")

if TYPE_CHECKING:
    from . import Translator  # noqa: F401


@dataclass(frozen=True, eq=False)
class ConfigMetadata:
    """Metadata pertaining to how a ``Translator`` instance was initialized from TOML configuration."""

    id_translation_version: str
    """The ``id_translation`` version under which this instance was created."""
    rics_version: str
    """The ``rics`` version under which this instance was created."""
    created: pd.Timestamp
    """The time at which the ``Translator`` was originally initialized. Second precision."""
    path: Path
    """Absolute path of the main translation configuration."""
    extra_fetchers: Tuple[Path, ...]
    """Absolute paths of configuration files for auxiliary fetchers."""
    clazz: str
    """String representation of the class type."""

    def is_equivalent(self, other: "ConfigMetadata") -> bool:  # pragma: no cover
        """Check if this ``ConfigMetadata`` is equivalent to `other`.

        Configs are equivalent if:

            - They have the same ``rics`` version, and
            - Use the same fully qualified class name, and
            - The main configuration files are equal after parsing, and
            - They have the same number of auxiliary (`"extra"`) fetcher configurations, and
            - All auxiliary fetcher configurations are equal after parsing.

        Args:
            other: Another ``ConfigMetadata`` instance.

        Returns:
            Equivalence status.
        """
        if self.id_translation_version != other.id_translation_version:
            LOGGER.debug(
                f"Versions 'id_translation' not equal. Expected '{self.id_translation_version}', but got '{other.id_translation_version}'."
            )
            return False

        if self.rics_version != other.rics_version:
            LOGGER.debug(f"Versions 'rics' not equal. Expected '{self.rics_version}', but got '{other.rics_version}'.")
            return False

        if self.clazz != other.clazz:
            LOGGER.debug(f"Class not equal. Expected '{self.clazz}', but got '{other.clazz}'.")
            return False

        if tomllib.loads(self.path.read_text()) != tomllib.loads(other.path.read_text()):
            return False

        if len(self.extra_fetchers) != len(other.extra_fetchers):
            LOGGER.debug(
                f"Number of auxiliary fetchers changed. Expected {len(self.extra_fetchers)}"
                f" but got {len(other.extra_fetchers)}."
            )
            return False

        def func(i: int) -> bool:
            if tomllib.loads(self.extra_fetchers[i].read_text()) != tomllib.loads(other.extra_fetchers[i].read_text()):
                LOGGER.debug(f"Configuration has changed for auxiliary fetcher at {self.extra_fetchers[i]}.")
                return False
            return True

        return all(map(func, range(len(self.extra_fetchers))))

    def to_json(self) -> str:
        """Get a JSON representation of this ``ConfigMetadata``."""
        raw = self.__dict__.copy()
        kwargs = dict(
            id_translation_version=raw.pop("id_translation_version"),
            rics_version=raw.pop("rics_version"),
            created=raw.pop("created").isoformat(),
            path=str(raw.pop("path")),
            extra_fetchers=list(map(str, raw.pop("extra_fetchers"))),
            clazz=raw.pop("clazz"),
        )
        assert not raw, f"Not serialized: {raw}."  # noqa:  S101
        return json.dumps(kwargs, indent=True)

    @classmethod
    def from_json(cls, s: str) -> "ConfigMetadata":
        """Create ``ConfigMetadata`` from a JSON string `s`."""
        raw = json.loads(s)
        kwargs = dict(
            id_translation_version=raw.pop("id_translation_version"),
            rics_version=raw.pop("rics_version"),
            created=pd.Timestamp.fromisoformat(raw.pop("created")),
            path=Path(raw.pop("path")),
            extra_fetchers=tuple(map(Path, raw.pop("extra_fetchers"))),
            clazz=raw.pop("clazz"),
        )
        assert not raw, f"Not deserialized: {raw}."  # noqa:  S101
        return ConfigMetadata(**kwargs)


def make_metadata(
    path: str,
    extra_fetchers: List[str],
    clazz: Type["Translator[Any, Any, Any]"],
) -> ConfigMetadata:
    """Convenience class for creating ``ConfigMetadata`` instances."""
    from rics import __version__ as rics_version

    from id_translation import __version__ as id_translation_version

    def fully_qualified_name(t: Type["Translator[Any, Any, Any]"]) -> str:
        return t.__module__ + "." + t.__qualname__

    return ConfigMetadata(
        id_translation_version=id_translation_version,
        rics_version=rics_version,
        created=pd.Timestamp.now().round("s"),
        path=Path(path).absolute(),
        extra_fetchers=tuple(map(Path.absolute, map(Path, extra_fetchers))),
        clazz=fully_qualified_name(clazz),
    )


def use_cached_translator(
    metadata_path: Path,
    reference_metadata: ConfigMetadata,
    max_age: pd.Timedelta,
) -> bool:
    """Returns ``True`` if given metadata indicates that the cached ``Translator`` is still viable."""
    if not metadata_path.exists():
        LOGGER.info(f"Metadata file '{metadata_path}' does not exist. Create new Translator.")
        return False

    now = pd.Timestamp.now().round("s")

    metadata = ConfigMetadata.from_json(metadata_path.read_text())
    LOGGER.debug(f"Metadata found: {metadata}")

    if not reference_metadata.is_equivalent(metadata):
        return False

    expires_at = metadata.created + max_age
    age = abs(now - expires_at)

    if expires_at < metadata.created:
        LOGGER.info(f"Reject cached Translator in '{metadata_path.parent}'. Expired at {expires_at} ({age} ago).")
        return False

    LOGGER.info(f"Accept cached Translator in '{metadata_path.parent}'. Expires at {expires_at} (in {age}).")
    return True
