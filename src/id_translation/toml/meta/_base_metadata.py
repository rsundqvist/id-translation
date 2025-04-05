import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Any, Literal, Self, TypeAlias

import pandas

from id_translation._compat import fmt_sec
from id_translation.translator_typing import CacheMissReasonType


class BaseMetadata(ABC):
    """Base implementation for Metadata types.

    Args:
        versions: Versions, e.g. ``{'python': '3.11.11'`, 'your-package': '1.0.0'}``.
        created: The time at which the metadata was originally created.
    """

    MaxAge: TypeAlias = str | pandas.Timedelta | timedelta | None

    def __init__(
        self,
        versions: dict[str, str] | None = None,
        created: datetime | None = None,
    ) -> None:
        self.versions = self.get_package_versions([]) if versions is None else versions
        self.created = created or datetime.now(UTC)

    @abstractmethod
    def _to_dict(self, to_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `to_json` into JSON-serializable types."""

    @classmethod
    @abstractmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `from_json` into desired types."""

    @abstractmethod
    def _is_equivalent(self, other: Self) -> str:
        """Implementation-specific equivalence check."""

    def is_equivalent(self, other: Self) -> str:
        """Compute equivalency with `other`.

        Args:
            other: Another metadata instance.

        Returns:
            A string `reason_not_equivalent` or an empty string.
        """
        if not isinstance(other, self.__class__):
            return f"Expected class={self.__class__.__name__} but got {other.__class__}"

        for package, version in self.versions.items():
            other_version = other.versions.get(package)
            if other_version != version:
                return f"Expected {package}={version!r} (your environment) but got {package}={other_version!r}"

        return self._is_equivalent(other)

    def to_dict(self) -> dict[str, Any]:
        """Get a dict representation of this ``BaseMetadata``."""
        raw = self.__dict__.copy()
        kwargs = dict(
            versions=raw.pop("versions"),
            created=raw.pop("created").isoformat(),
        )
        kwargs.update(self._to_dict(raw))
        assert not raw, f"Not serialized: {raw}."  # noqa:  S101
        return kwargs

    def to_json(self) -> str:
        """Get a dict representation of this ``BaseMetadata``."""
        kwargs = self.to_dict()
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

    def use_cached(
        self,
        metadata_path: Path,
        max_age: MaxAge,
    ) -> tuple[Literal[True], str, None] | tuple[Literal[False], str, CacheMissReasonType]:
        """Check status of stored metadata config based a desired configuration ``self``.

        Args:
            metadata_path: Path of stored metadata.
            max_age: Maximum age of stored metadata. Pass zero to force recreation. Smaller than zero = never expire.

        Returns:
            A tuple ``(True, expires_at, None)`` or ``(False, reason, reason_type)``.
        """
        if not metadata_path.exists():
            return False, "no cache metadata found", "metadata-missing"

        stored_config = self.from_json(metadata_path.read_text())

        reason_not_equivalent = self.is_equivalent(stored_config)
        if reason_not_equivalent:
            return False, f"cached instance is not equivalent: {reason_not_equivalent}", "metadata-changed"

        if max_age is None:
            return True, "does not expire", None

        max_age = pandas.Timedelta(max_age)

        expires_at = (stored_config.created + abs(max_age)).replace(microsecond=0)
        offset = fmt_sec(round(abs(datetime.now(UTC) - expires_at).total_seconds()))

        if expires_at <= stored_config.created:
            return False, f"expired at {expires_at.isoformat()} ({offset} ago)", "too-old"
        else:
            return True, f"expires at {expires_at.isoformat()} (in {offset})", None

    @classmethod
    def get_package_versions(cls, extra_packages: Iterable[str]) -> dict[str, str]:
        """Extract package versions using ``importlib.metadata``."""
        assert not isinstance(extra_packages, str)  # noqa: S101
        packages = ["rics", "id-translation", "sqlalchemy", "pandas", *extra_packages]
        return {package: get_version(package) for package in packages}
