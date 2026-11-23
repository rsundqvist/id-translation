import json
import logging
import sys
from collections.abc import Iterable
from datetime import date, time
from hashlib import sha256
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rics.collections.misc import as_list
from rics.paths import AnyPath

from id_translation._utils import add_hints
from id_translation.toml._load_toml import load_toml_file

from ._base_metadata import BaseMetadata
from ._metaconf import Metaconf

LOGGER = logging.getLogger(__package__).getChild("Translator").getChild("config")

if TYPE_CHECKING:
    from id_translation import Translator


class ConfigMetadata(BaseMetadata):
    """Metadata pertaining to how a :class:`~id_translation.Translator` instance was initialized from TOML configuration.

    Equivalence:
        Configs are equivalent if and only if...

        - They have the same top-level dependency versions, and
        - Use the same fully qualified class name, and
        - The main configuration is equal after parsing, and
        - They have the same number of auxiliary (`"extra"`) fetcher configurations, and
        - All auxiliary fetcher configurations are equal after parsing, and
        - They have the same meta configuration (``metaconf.toml``).

    Environment variable changes may also make configurations non-equivalent if interpolations such as ``${VAR}`` are
    present and :attr:`EnvConf.allow_interpolation <id_translation.toml.meta.EnvConf.allow_interpolation>` is set.

    Args:
        main: Absolute path and fingerprint of the main translation configuration."
        extra_fetchers: Absolute path and fingerprint of configuration files for auxiliary fetchers.
        clazz: String representation of the class type.
        metaconf: A :class:`~id_translation.toml.meta.Metaconf` instance that determines, among other things, how other
            config paths are processed.
        kwargs: Forwarded to base class.
    """

    def __init__(
        self,
        main: tuple[Path, str],
        extra_fetchers: tuple[tuple[Path, str], ...],
        clazz: str,
        metaconf: Metaconf,
        **kwargs: Any,
    ) -> None:
        if "versions" not in kwargs:
            kwargs["versions"] = {
                "python": metaconf.equivalence.python_version.format(v=sys.version_info),
                **self.get_package_versions(metaconf.equivalence.extra_packages),
            }
        super().__init__(**kwargs)
        self.main = main
        self.extra_fetchers = extra_fetchers
        self.clazz = clazz
        self.metaconf = metaconf

    def _to_dict(self, to_json: dict[str, Any]) -> dict[str, Any]:
        return {
            "main": tuple(map(str, to_json.pop("main"))),
            "extra_fetchers": [tuple(map(str, t)) for t in to_json.pop("extra_fetchers")],
            "metaconf": to_json.pop("metaconf").as_dict(),
            "class": to_json.pop("clazz"),
        }

    @classmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        def to_path_tuple(args: list[str]) -> tuple[Path, str]:
            return Path(args[0]), args[1]

        return dict(
            main=to_path_tuple(from_json.pop("main")),
            extra_fetchers=tuple(map(to_path_tuple, from_json.pop("extra_fetchers"))),
            clazz=from_json.pop("class"),
            metaconf=Metaconf.from_dict(from_json.pop("metaconf")),
        )

    def _reason_not_equivalent(self, other: BaseMetadata) -> str:
        assert isinstance(other, ConfigMetadata)  # noqa: S101

        if self.clazz != other.clazz:
            return f"Class not equal. Expected '{self.clazz}', but got '{other.clazz}'"

        if self.main[1] != other.main[1]:
            return f"Main configuration changed: {self.main[0]}"

        if self.metaconf != other.metaconf:
            return f"Meta configuration changed: {_diff(other.metaconf.as_dict(), self.metaconf.as_dict())}"

        if len(self.extra_fetchers) != len(other.extra_fetchers):
            return (
                f"Number of auxiliary fetchers changed. Expected {len(self.extra_fetchers)}"
                f" fetchers but got {len(other.extra_fetchers)}"
            )

        for rank, ((path, fingerprint), (_, other_fingerprint)) in enumerate(
            zip(self.extra_fetchers, other.extra_fetchers, strict=True), start=1
        ):
            if fingerprint != other_fingerprint:
                return f"Auxiliary fetcher configuration #{rank} changed: {path}"  # The main file has rank 0.

        return ""

    @staticmethod
    def from_toml_paths(
        path: AnyPath,
        extra_fetchers: AnyPath | Iterable[AnyPath] = (),
        *,
        clazz: type["Translator[Any, Any, Any]"],
    ) -> "ConfigMetadata":
        """Create ``ConfigMetadata`` from configuration files, without creating a :class:`~id_translation.Translator`.

        Args:
            path: Path to the main TOML configuration file.
            extra_fetchers: A path, or paths, to fetching configuration TOML files, in rank order.
            clazz: The :class:`~id_translation.Translator` class, which is part of equivalence.

        Returns:
            A new ``ConfigMetadata``.
        """
        main_path = str(Path(path).expanduser())
        fetcher_paths: list[AnyPath] = as_list(extra_fetchers)  # A bare path is one path, not characters.
        metaconf_path = str(Path(main_path).with_name("metaconf.toml"))
        metaconf = Metaconf.from_path_or_default(metaconf_path)

        def _create_path_tuple(str_path: str) -> tuple[Path, str]:
            p = Path(str_path).expanduser().absolute()
            content = load_toml_file(
                p,
                allow_interpolation=metaconf.env.allow_interpolation,
                allow_nested=metaconf.env.allow_nested,
                allow_blank=metaconf.env.allow_blank,
            )

            json_content = json.dumps(
                content,
                sort_keys=False,  # key order is meaningful in places, e.g. transformers
                default=_fingerprint_default,
            )
            return p, sha256(json_content.encode()).hexdigest()

        main = _create_path_tuple(main_path)
        extra = tuple(_create_path_tuple(str(Path(p))) for p in fetcher_paths)
        try:
            return ConfigMetadata(
                main=main,
                extra_fetchers=extra,
                clazz=clazz.__module__ + "." + clazz.__qualname__,  # Fully qualified name
                metaconf=metaconf,
            )
        except Exception as e:
            # E.g. an extra_packages entry that is not installed, or not a name. Not id-translation's own missing
            # metadata, though: the file may not exist.
            if not (isinstance(e, PackageNotFoundError) and e.name not in metaconf.equivalence.extra_packages):
                add_hints(e, f"In file: {Path(metaconf_path).resolve()}")
            raise


def _fingerprint_default(obj: Any) -> str:
    # TOML date and time literals. Tagged, so that changing a date to an equal string still changes the fingerprint.
    if isinstance(obj, date | time):
        return f"{type(obj).__name__}:{obj.isoformat()}"
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _diff(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> str:
    changes = [
        f"{section}.{key}: {old[section].get(key)!r} -> {value!r}"
        for section, values in new.items()
        for key, value in values.items()
        if old.get(section, {}).get(key) != value
    ]
    return ", ".join(changes)
