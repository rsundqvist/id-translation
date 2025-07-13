import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as get_version
from pathlib import Path
from typing import Any, Literal, Self

from rics.strings import format_seconds as fmt_sec

from id_translation.translator_typing import CacheMissReasonType


class BaseMetadata(ABC):
    """Base implementation for Metadata types.

    Args:
        versions: Versions, e.g. ``{'python': '3.11.11'`, 'your-package': '1.0.0'}``.
        created: The time at which the metadata was originally created.
    """

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
        max_age: str | timedelta | None,
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
        elif isinstance(max_age, str):
            delta = self._delta_from_string(max_age)
        else:
            delta = max_age

        expires_at = (stored_config.created + abs(delta)).replace(microsecond=0)
        offset = fmt_sec(round(abs(datetime.now(UTC) - expires_at).total_seconds()))

        if expires_at <= stored_config.created:
            return False, f"expired at {expires_at.isoformat()} ({offset} ago)", "too-old"
        else:
            return True, f"expires at {expires_at.isoformat()} (in {offset})", None

    @classmethod
    def _delta_from_string(cls, max_age: str) -> timedelta:
        try:
            import pandas  # noqa: PLC0415

            return pandas.Timedelta(max_age).to_pytimedelta()  # type: ignore[no-any-return]
        except ImportError:
            pass

        unit = ""
        for c in max_age:
            if c.isalpha():
                unit = c
                break

        if not unit:
            msg = f"bad {max_age=}"
            raise ValueError(msg)

        unit_multiplier: int
        match unit.lower():
            case "s":
                unit_multiplier = 1
            case "m":
                unit_multiplier = 60
            case "h":
                unit_multiplier = 60 * 60
            case "d":
                unit_multiplier = 60 * 60 * 24
            case _:
                raise ValueError(f"bad {max_age=}")

        n_units = int(max_age[: max_age.index(unit)])
        return timedelta(seconds=n_units * unit_multiplier)

    @classmethod
    def get_package_versions(cls, extra_packages: Iterable[str]) -> dict[str, str]:
        """Extract package versions using ``importlib.metadata``."""
        assert not isinstance(extra_packages, str)  # noqa: S101
        packages = ["id-translation", *extra_packages]
        return {package: get_version(package) for package in packages}
