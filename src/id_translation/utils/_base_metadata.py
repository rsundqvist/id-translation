import json
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rics.performance import format_seconds


def _initialize_versions() -> dict[str, str]:
    from pandas import __version__ as pandas_version
    from rics import __version__ as rics
    from sqlalchemy import __version__ as sqlalchemy

    from .. import __version__ as id_translation

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

    def __init__(self, versions: dict[str, str] | None = None, created: datetime | None = None) -> None:
        self.versions = versions or _initialize_versions()
        self.created = created or datetime.now()

    @abstractmethod
    def _serialize(self, to_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `to_json` into JSON-serializable types."""

    @classmethod
    @abstractmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `from_json` into desired types."""

    @abstractmethod
    def _is_equivalent(self, other: "BaseMetadata") -> str:
        """Implementation-specific equivalence check."""

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
        return json.dumps(kwargs, indent=4)

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

    def use_cached(self, metadata_path: Path, max_age: timedelta) -> tuple[bool, str]:
        """Check status of stored metadata config based a desired configuration ``self``.

        Args:
            metadata_path: Path of stored metadata.
            max_age: Maximum age of stored metadata.

        Returns:
            A tuple ``(use_cached, reason)``.
        """
        if not metadata_path.exists():
            return False, "no cache metadata found"

        stored_config = self.from_json(metadata_path.read_text())

        reason_not_equivalent = self.is_equivalent(stored_config)
        if reason_not_equivalent:
            return False, f"cached instance is not equivalent: {reason_not_equivalent}"

        expires_at = (stored_config.created + max_age).replace(microsecond=0)
        offset = format_seconds(round(abs(datetime.now() - expires_at).total_seconds()))

        if expires_at <= stored_config.created:
            return False, f"expired at {expires_at.isoformat()} ({offset} ago)"
        else:
            return True, f"expires at {expires_at.isoformat()} (in {offset})"
