import logging
import pickle
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic

import pandas as pd

from ..offline.types import PlaceholderTranslations, SourcePlaceholderTranslations
from ..types import ID, HasSources, IdType, SourceType
from ..utils import BaseMetadata


@dataclass(eq=False)
class CacheMetadata(BaseMetadata, Generic[SourceType, IdType], HasSources[SourceType]):
    """Metadata pertaining to fetcher caching logic.

    Args:
        cache_keys: Hierarchical identifiers for the cache. The first key is used to determine storage location, while
            the rest are used to detect configuration changes (which invalidate the cache). A typical key would be
            ``[config-file-name, config-file-sha]``.
        placeholders: A Source-to-placeholder dict.
        **kwargs: Forwarded to base classes.
    """

    def __init__(
        self,
        *,
        cache_keys: list[str],
        placeholders: dict[SourceType, list[str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not cache_keys:  # pragma: no cover
            raise ValueError("Must specify at least one cache key.")
        self._cache_keys = cache_keys
        self._placeholders = placeholders

    @property
    def cache_keys(self) -> list[str]:
        """Yields hierarchical cache keys for this metadata."""
        return self._cache_keys.copy()

    @property
    def placeholders(self) -> dict[SourceType, list[str]]:
        return self._placeholders

    def _is_equivalent(self, other: "BaseMetadata") -> str:
        assert isinstance(other, CacheMetadata)  # noqa: S101

        if self._cache_keys != other._cache_keys:
            return f"Expected cache_keys={self._cache_keys} (requested) but got {other._cache_keys}"

        if list(self.placeholders) != list(other.placeholders):
            return f"Expected sources={list(self.placeholders)} (requested) but got {list(other.placeholders)}"

        for source, expected in self.placeholders.items():
            if sorted(expected) != sorted(other.placeholders[source]):
                return f"For {source=}, expected placeholders={expected} but got {other.placeholders[source]}"

        return ""

    def _serialize(self, to_json: dict[str, Any]) -> dict[str, Any]:
        ans = to_json.copy()
        to_json.clear()
        return ans

    @classmethod
    def _deserialize(cls, from_json: dict[str, Any]) -> dict[str, Any]:
        return dict(cache_keys=from_json.pop("_cache_keys"), placeholders=from_json.pop("_placeholders"))


class CacheAccess(Generic[SourceType, IdType]):
    """Utility class for managing the FETCH_ALL-cache.

    Args:
        max_age: Cache timeout.
        metadata: Metadata object used to determine cache validity.
    """

    CLEAR_CACHE_EXCEPTION_TYPES: tuple[type[Exception], ...] = (pickle.UnpicklingError,)
    """Error types which trigger cache deletion"""

    BASE_CACHE_PATH: Path = Path.home().joinpath(".cache/id-translation/cached-fetcher-data/")
    """Top-level cache dir for all fetchers managed by any ``CacheAccess``-instance."""

    @classmethod
    def base_cache_dir_for_all_fetchers(cls) -> Path:  # pragma: no cover
        """Top-level cache dir for all fetchers managed by any ``CacheAccess``-instance."""
        import warnings

        warnings.warn(
            "This method has been deprecated. Please use CacheAccess.BASE_CACHE_PATH instead.",
            category=DeprecationWarning,
            stacklevel=2,
        )
        return cls.BASE_CACHE_PATH

    @classmethod
    def clear_all_cache_data(cls) -> None:
        """Remove the entire cache directory tree for ALL instances."""
        import shutil

        cache_dir = cls.BASE_CACHE_PATH
        print(f"Deleting the common cache directory tree at:\n    '{cache_dir}'")
        shutil.rmtree(cache_dir)

    def __init__(
        self,
        max_age: pd.Timedelta,
        metadata: CacheMetadata[SourceType, IdType],
    ) -> None:
        if max_age < pd.Timedelta(0):
            raise ValueError("fetch_all_cache_max_age must be non-negative")  # pragma: no cover
        self._max_age = max_age.to_pytimedelta()  # Avoids serializing pandas types.
        self._metadata: CacheMetadata[SourceType, IdType] = metadata
        top_level_key = next(iter(self._metadata.cache_keys))
        self._base_dir = self.BASE_CACHE_PATH.joinpath(top_level_key)
        self._logger = logging.getLogger(__package__).getChild("CacheAccess").getChild(top_level_key)

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory used by this ``CacheAccess``.

        Created from :attr:`BASE_CACHE_PATH` and the first value of :attr:`CacheMetadata.cache_keys`.

        Returns:
            Cache dir for a single fetcher.
        """
        return self._base_dir

    @property
    def metadata_path(self) -> Path:
        return self._base_dir / "metadata.json"

    @property
    def data_dir(self) -> Path:
        return self._base_dir / "sources"

    def source_path(self, source: Any) -> Path:
        """Get the data path for `source`."""
        return self.data_dir / f"{source}.pkl"

    def read_cache(self, source: SourceType) -> PlaceholderTranslations[SourceType] | None:
        """Read cached translation data for `source`."""
        use_cached, reason = self._metadata.use_cached(self.metadata_path, self._max_age)
        if not use_cached:
            return None

        self._logger.debug(f"Use cached data for {source=}: {reason}. Cache dir: '{self.cache_dir}'.")

        path = self.source_path(source)
        try:
            with path.open("rb") as f:
                records = pickle.load(f)  # noqa: S301
        except self.CLEAR_CACHE_EXCEPTION_TYPES as e:
            self.clear(
                f"Deserializing of {source=} failed; the cache is likely corrupted."
                f"\n    -      Path: '{path}'"
                f"\n    - Exception: {type(e).__qualname__}: {e}",
                log_level=logging.ERROR,
                exc_info=True,
            )
            return None

        placeholders = tuple(self._metadata.placeholders[source])
        id_pos = placeholders.index(ID) if ID in placeholders else -1
        return PlaceholderTranslations(source, placeholders=placeholders, records=records, id_pos=id_pos)

    def write_cache(self, data: SourcePlaceholderTranslations[SourceType]) -> None:
        """Overwrite the current cache (if it exists) with new and update metadata."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_path.write_text(self._metadata.to_json())

        for source, pht in data.items():
            with self.source_path(source).open("wb") as f:
                pickle.dump(pht.records, f)

    def clear(self, reason: str, log_level: int = logging.DEBUG, *, exc_info: bool = False) -> None:
        """Remove cached data for the current instance."""
        deleted = [*self.cache_dir.rglob("*")]
        shutil.rmtree(self.cache_dir)

        if self._logger.isEnabledFor(log_level):
            delete_info = "\n".join(map("    - {}".format, deleted)) if deleted else "    There is nothing to delete."
            self._logger.log(
                log_level,
                f"Clear cache: {reason}.\nThe following files have been deleted:\n{delete_info}",
                exc_info=exc_info,
            )
