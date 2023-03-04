import json
import logging
import sys
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Type

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

    versions: Dict[str, str]
    """Top-level dependency versions under which this instance was created."""
    created: pd.Timestamp
    """The time at which the ``Translator`` was originally initialized. Second precision."""
    main: Tuple[Path, str]
    """Absolute path and fingerprint of the main translation configuration."""
    extra_fetchers: Tuple[Tuple[Path, str], ...]
    """Absolute path and fingerprint of configuration files for auxiliary fetchers."""
    clazz: str
    """String representation of the class type."""

    def is_equivalent(self, other: "ConfigMetadata") -> str:  # pragma: no cover
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
            Reason for non-equivalence, if any.
        """
        for package, version in self.versions.items():
            other_version = other.versions.get(package)
            if other_version != version:
                return f"Expected {package}=={version!r} (your environment) but got {package}=={other_version!r}"

        if self.clazz != other.clazz:
            return f"Class not equal. Expected '{self.clazz}', but got '{other.clazz}'"

        if self.main[1] != other.main[1]:
            return f"Main configuration changed. Expected fingerprint {self.main[1]}, but got {other.main[1]}"

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

    def to_json(self) -> str:
        """Get a JSON representation of this ``ConfigMetadata``."""
        raw = self.__dict__.copy()
        kwargs = dict(
            versions=raw.pop("versions"),
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
            versions=raw.pop("versions"),
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
    from rics import __version__ as rics
    from sqlalchemy import __version__ as sqlalchemy

    from id_translation import __version__ as id_translation

    versions = dict(
        rics=rics,
        id_translation=id_translation,
        sqlalchemy=sqlalchemy,
        pandas=pd.__version__,
        tomllib=tomllib.__version__ if hasattr(tomllib, "__version__") else None,
    )

    def create_path_tuple(str_path: str) -> Tuple[Path, str]:
        p = Path(str_path).expanduser().absolute()
        with p.open("rb") as f:
            content = tomllib.load(f)
        return p, sha256(json.dumps(content).encode()).hexdigest()

    return ConfigMetadata(
        versions=versions,
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

    def log_reject(reason: str) -> None:
        LOGGER.info(f"Create new Translator; {reason}. Metadata path='{metadata_path}'.")

    if not metadata_path.exists():
        log_reject("no cache metadata found")
        return False

    stored_config = ConfigMetadata.from_json(metadata_path.read_text())

    reason_not_equivalent = wanted_config.is_equivalent(stored_config)
    if reason_not_equivalent:
        log_reject(f"cached instance is not equivalent. {reason_not_equivalent}")
        return False

    expires_at = stored_config.created + max_age
    offset = abs(pd.Timestamp.now() - expires_at).round("s")

    if expires_at <= stored_config.created:
        log_reject(f"cache expired at {expires_at} ({offset} ago)")
        return False

    LOGGER.info(f"Accept cached Translator in '{metadata_path.parent}'. Expires at {expires_at} (in {offset}).")
    return True
