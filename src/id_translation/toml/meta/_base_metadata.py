import json
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib.metadata import version as get_version
from typing import Any, Self


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
        self.created = datetime.now(UTC) if created is None else created.astimezone(UTC)

    @abstractmethod
    def _to_dict(self, to_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `to_json` into JSON-serializable types."""

    @classmethod
    @abstractmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        """Turn `from_json` into desired types."""

    @abstractmethod
    def _reason_not_equivalent(self, other: Self) -> str:
        """Implementation-specific equivalence check."""

    def reason_not_equivalent(self, other: Self) -> str:
        """Explain why `other` is not equivalent to this instance.

        Args:
            other: Another metadata instance, e.g. a stored one.

        Returns:
            The reason, or an empty string if the two are equivalent.
        """
        if not isinstance(other, self.__class__):
            return f"Expected class={self.__class__.__name__} but got {other.__class__}"

        for package, version in self.versions.items():
            other_version = other.versions.get(package)
            if other_version != version:
                return f"Expected {package}={version!r} (your environment) but got {package}={other_version!r}"

        return self._reason_not_equivalent(other)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BaseMetadata) or type(self) is not type(other):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={value!r}" for name, value in vars(self).items())
        return f"{type(self).__name__}({fields})"

    __hash__ = None  # type: ignore[assignment]  # Mutable (e.g. 'versions') with value equality => unhashable.

    def to_dict(self) -> dict[str, Any]:
        """Get a dict representation of this ``BaseMetadata``."""
        raw = self.__dict__.copy()
        kwargs = dict(
            versions=raw.pop("versions"),
            created=raw.pop("created").isoformat(),
        )
        kwargs.update(self._to_dict(raw))
        assert not raw, f"Not serialized: {raw}."  # noqa: S101
        return kwargs

    def to_json(self) -> str:
        """Get a dict representation of this ``BaseMetadata``."""
        kwargs = self.to_dict()
        return json.dumps(kwargs, indent=4)

    @classmethod
    def from_json(cls, s: str) -> Self:
        """Create ``BaseMetadata`` from a JSON string `s`."""
        raw = json.loads(s)

        versions = raw.pop("versions")
        if not isinstance(versions, dict):
            raise TypeError(f"Bad {versions=}: expected a dict.")
        created = datetime.fromisoformat(raw.pop("created"))

        kwargs: dict[str, Any] = {"versions": versions, "created": created}
        kwargs.update(cls._deserialize(raw))

        if raw:
            raise ValueError(f"Unknown keys: {sorted(raw)}.")

        return cls(**kwargs)

    @classmethod
    def get_package_versions(cls, extra_packages: Iterable[str]) -> dict[str, str]:
        """Extract package versions using ``importlib.metadata``."""
        assert not isinstance(extra_packages, str)  # noqa: S101
        packages = ["id-translation", *extra_packages]
        return {package: get_version(package) for package in packages}
