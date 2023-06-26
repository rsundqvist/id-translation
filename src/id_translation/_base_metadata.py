import json
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict


def _initialize_versions() -> Dict[str, str]:
    from pandas import __version__ as pandas_version
    from rics import __version__ as rics
    from sqlalchemy import __version__ as sqlalchemy

    from id_translation import __version__ as id_translation

    ans = dict(
        rics=rics,
        id_translation=id_translation,
        sqlalchemy=sqlalchemy,
        pandas=pandas_version,
    )

    if sys.version_info < (3, 11):  # pragma: no cover
        import tomli

        ans["tomli"] = tomli.__version__
    return ans


class BaseMetadata(ABC):
    """Base implementation for Metadata types.

    Args:
        versions: Top-level dependency versions.
        created: The time at which the metadata was originally created.
    """

    def __init__(self, versions: Dict[str, str] = None, created: datetime = None) -> None:
        self.versions = versions or _initialize_versions()
        self.created = created or datetime.now()

    @abstractmethod
    def _serialize(self, to_json: Dict[str, Any]) -> Dict[str, Any]:
        """Turn `to_json` into JSON-serializable types."""

    @classmethod
    @abstractmethod
    def _deserialize(cls, from_json: Dict[str, Any]) -> Dict[str, Any]:
        """Turn `from_json` into desired types."""

    @abstractmethod
    def _is_equivalent(self, other: "BaseMetadata") -> str:
        """Implementation-specific equivalence check."""

    @abstractmethod
    def _log_reject(self, msg: str) -> None:
        """Log metadata reject event. Subclasses should format the `slug` key."""

    @abstractmethod
    def _log_accept(self, msg: str) -> None:
        """Log metadata accept event. Subclasses should format the `kind` key."""

    def is_equivalent(self, other: "BaseMetadata") -> str:
        """Equivalency status."""
        if not isinstance(other, self.__class__):
            return f"Expected class={self.__class__.__name__} but got {other.__class__}"

        for package, version in self.versions.items():
            other_version = other.versions.get(package)
            if other_version != version:
                return f"Expected {package}=={version!r} (your environment) but got {package}=={other_version!r}"

        return self._is_equivalent(other)

    def to_json(self) -> str:
        """Get a JSON representation of this ``BaseMetadata``."""
        raw = self.__dict__.copy()
        kwargs = dict(
            versions=raw.pop("versions"),
            created=raw.pop("created").isoformat(),
        )
        kwargs.update(self._serialize(raw))
        assert not raw, f"Not serialized: {raw}."  # noqa:  S101
        return json.dumps(kwargs, indent=True)

    @classmethod
    def from_json(cls, s: str) -> "BaseMetadata":
        """Create ``BaseMetadata`` from a JSON string `s`."""
        raw = json.loads(s)

        kwargs = dict(
            versions=raw.pop("versions"),
            created=datetime.fromisoformat(raw.pop("created")),
        )
        kwargs.update(cls._deserialize(raw))

        assert not raw, f"Not deserialized: {raw}."  # noqa:  S101
        return cls(**kwargs)

    def use_cached(self, metadata_path: Path, max_age: timedelta) -> bool:
        """Check status of stored metadata config based a desired configuration ``self``.

        Args:
            metadata_path: Path of stored metadata.
            max_age: Maximum age of stored metadata.

        Returns:
            ``True`` if the cached instance is still viable.
        """

        def log_reject(reason: str) -> None:
            self._log_reject(f"{{slug}}; {reason}. Metadata path='{metadata_path}'.")

        if not metadata_path.exists():
            log_reject("no cache metadata found")
            return False

        stored_config = self.from_json(metadata_path.read_text())

        reason_not_equivalent = self.is_equivalent(stored_config)
        if reason_not_equivalent:
            log_reject(f"cached instance is not equivalent. {reason_not_equivalent}")
            return False

        expires_at = stored_config.created + max_age
        offset = timedelta(seconds=round(abs(datetime.now() - expires_at).total_seconds()))

        fmt = "%Y-%m-%dT%H:%M:%S"
        if expires_at <= stored_config.created:
            log_reject(f"cache expired at {expires_at:{fmt}} ({offset} ago)")
            return False

        self._log_accept(
            f"Accept cached {{kind}} in '{metadata_path.parent}'. " f"Expires at {expires_at:{fmt}} (in {offset})."
        )
        return True
