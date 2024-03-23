import json
import logging
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._base_metadata import BaseMetadata
from ._load_toml import load_toml_file

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")

if TYPE_CHECKING:
    from .. import Translator


class ConfigMetadata(BaseMetadata):
    """Metadata pertaining to how a :class:`.Translator` instance was initialized from TOML configuration.

    Equivalence:
        Configs are equivalent if and only if...

        - They have the same top-level dependency versions, and
        - Use the same fully qualified class name, and
        - The main configuration is equal after parsing, and
        - They have the same number of auxiliary (`"extra"`) fetcher configurations, and
        - All auxiliary fetcher configurations are equal after parsing.

    Args:
        main: Absolute path and fingerprint of the main translation configuration."
        extra_fetchers: Absolute path and fingerprint of configuration files for auxiliary fetchers.
        clazz: String representation of the class type.
    """

    def __init__(
        self,
        main: tuple[Path, str],
        extra_fetchers: tuple[tuple[Path, str], ...],
        clazz: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.main = main
        self.extra_fetchers = extra_fetchers
        self.clazz = clazz

    def _serialize(self, to_json: dict[str, Any]) -> dict[str, Any]:
        kwargs = dict(
            main=tuple(map(str, to_json.pop("main"))),
            extra_fetchers=[tuple(map(str, t)) for t in to_json.pop("extra_fetchers")],
        )
        kwargs["class"] = to_json.pop("clazz")
        return kwargs

    @classmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        def to_path_tuple(args: list[str]) -> tuple[Path, str]:
            return Path(args[0]), args[1]

        return dict(
            main=to_path_tuple(from_json.pop("main")),
            extra_fetchers=tuple(map(to_path_tuple, from_json.pop("extra_fetchers"))),
            clazz=from_json.pop("class"),
        )

    def _is_equivalent(self, other: BaseMetadata) -> str:  # pragma: no cover
        assert isinstance(other, ConfigMetadata)  # noqa: S101

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

    @staticmethod
    def from_toml_paths(
        path: str,
        extra_fetchers: list[str],
        clazz: type["Translator[Any, Any, Any]"],
    ) -> "ConfigMetadata":
        """Convenience function for creating ``ConfigMetadata`` instances."""
        return ConfigMetadata(
            main=_create_path_tuple(path),
            extra_fetchers=tuple(map(_create_path_tuple, extra_fetchers)),
            clazz=clazz.__module__ + "." + clazz.__qualname__,  # Fully qualified name
        )


def _create_path_tuple(str_path: str) -> tuple[Path, str]:
    p = Path(str_path).expanduser().absolute()
    content = load_toml_file(p)
    return p, sha256(json.dumps(content).encode()).hexdigest()
