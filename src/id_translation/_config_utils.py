import json
import logging
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Tuple, Type

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # pragma: no cover

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
    main: Tuple[Path, str]
    """Absolute path and fingerprint of the main translation configuration."""
    extra_fetchers: Tuple[Tuple[Path, str], ...]
    """Absolute path and fingerprint of configuration files for auxiliary fetchers."""
    clazz: str
    """String representation of the class type."""

    def is_equivalent(self, other: "ConfigMetadata") -> bool:  # pragma: no cover
        """Check if this ``ConfigMetadata`` is equivalent to `other`.

        Configs are equivalent if:

            - They have the same ``rics`` version, and
            - Use the same fully qualified class name, and
            - The main configuration is equal after parsing, and
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

        if self.main[1] != other.main[1]:
            LOGGER.debug(f"Main configuration changed. Expected fingerprint {self.main[1]}, but got {other.main[1]}.")
            return False

        if len(self.extra_fetchers) != len(other.extra_fetchers):
            LOGGER.debug(
                f"Number of auxiliary fetchers changed. Expected {len(self.extra_fetchers)}"
                f" fetchers but got {len(other.extra_fetchers)}."
            )
            return False

        def func(i: int) -> bool:
            path, fingerprint = self.extra_fetchers[i]
            _, other_fingerprint = other.extra_fetchers[i]
            if fingerprint != other_fingerprint:
                LOGGER.debug(
                    f"Configuration changed for auxiliary fetcher #{i} at {path}. "
                    f"Expected fingerprint {fingerprint}, but got {other_fingerprint}."
                )
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
            main=tuple(map(str, raw.pop("main"))),
            extra_fetchers=[tuple(map(str, t)) for t in raw.pop("extra_fetchers")],
        )
        kwargs["class"] = raw.pop("clazz")
        assert not raw, f"Not serialized: {raw}."  # noqa:  S101
        return json.dumps(kwargs, indent=True)

    @classmethod
    def from_json(cls, s: str) -> "ConfigMetadata":
        """Create ``ConfigMetadata`` from a JSON string `s`."""
        raw = json.loads(s)

        def to_path_tuple(args: List[str]) -> Tuple[Path, str]:
            return Path(args[0]), args[1]

        kwargs = dict(
            id_translation_version=raw.pop("id_translation_version"),
            rics_version=raw.pop("rics_version"),
            created=pd.Timestamp.fromisoformat(raw.pop("created")),
            main=to_path_tuple(raw.pop("main")),
            extra_fetchers=tuple(map(to_path_tuple, raw.pop("extra_fetchers"))),
            clazz=raw.pop("class"),
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

    def create_path_tuple(str_path: str) -> Tuple[Path, str]:
        p = Path(str_path).expanduser().absolute()
        with p.open("rb") as f:
            content = tomllib.load(f)
        return p, sha256(json.dumps(content).encode()).hexdigest()

    return ConfigMetadata(
        id_translation_version=id_translation_version,
        rics_version=rics_version,
        created=pd.Timestamp.now().round("s"),
        main=create_path_tuple(path),
        extra_fetchers=tuple(map(create_path_tuple, extra_fetchers)),
        clazz=clazz.__module__ + "." + clazz.__qualname__,  # Fully qualified name
    )


def use_cached_translator(
    metadata_path: Path,
    wanted_config: ConfigMetadata,
    max_age: pd.Timedelta,
) -> bool:
    """Returns ``True`` if given metadata indicates that the cached ``Translator`` is still viable."""
    if not metadata_path.exists():
        LOGGER.info(f"Metadata file '{metadata_path}' does not exist. Create new Translator.")
        return False

    stored_config = ConfigMetadata.from_json(metadata_path.read_text())
    LOGGER.debug(f"Metadata found: {stored_config}")

    if not wanted_config.is_equivalent(stored_config):
        LOGGER.info(f"Configuration has changed. Reject cached Translator in '{metadata_path.parent}'.")
        return False

    expires_at = stored_config.created + max_age
    offset = abs(pd.Timestamp.now() - expires_at).round("s")

    if expires_at <= stored_config.created:
        LOGGER.info(f"Reject cached Translator in '{metadata_path.parent}'. Expired at {expires_at} ({offset} ago).")
        return False

    LOGGER.info(f"Accept cached Translator in '{metadata_path.parent}'. Expires at {expires_at} (in {offset}).")
    return True
