import logging
import pickle  # noqa: 403
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Generic, List, Optional

import pandas as pd

from id_translation._base_metadata import BaseMetadata
from id_translation.types import HasSources, IdType, SourceType

from ..offline.types import PlaceholderTranslations, SourcePlaceholderTranslations

BASE_LOGGER = logging.getLogger(__package__).getChild("CacheMetadata")


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
        cache_keys: List[str],
        placeholders: Dict[SourceType, List[str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not cache_keys:  # pragma: no cover
            raise ValueError("Must specify at least one cache key.")
        self._cache_keys = cache_keys
        self._placeholders = placeholders

    @property
    def cache_keys(self) -> List[str]:
        """Yields hierarchical cache keys for this metadata."""
        return self._cache_keys.copy()

    @property
    def placeholders(self) -> Dict[SourceType, List[str]]:
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

    @property
    def _logger(self) -> logging.Logger:
        return BASE_LOGGER.getChild(self.cache_keys[0])

    def _log_reject(self, msg: str) -> None:
        self._logger.debug(msg.format(slug="Fetch new translations"))  # noqa: G001

    def _log_accept(self, msg: str) -> None:
        self._logger.debug(msg.format(kind="translations"))  # noqa: G001

    def _serialize(self, to_json: Dict[str, Any]) -> Dict[str, Any]:
        ans = to_json.copy()
        to_json.clear()
        return ans

    @classmethod
    def _deserialize(cls, from_json: Dict[str, Any]) -> Dict[str, Any]:
        return dict(cache_keys=from_json.pop("_cache_keys"), placeholders=from_json.pop("_placeholders"))


class CacheAccess(Generic[SourceType, IdType]):
    """Utility class for managing the FETCH_ALL-cache.

    Args:
        max_age: Cache timeout.
        metadata: Metadata object used to determine cache validity.
    """

    @classmethod
    def base_cache_dir_for_all_fetchers(cls) -> Path:
        """Top-level cache dir for all fetchers managed by any ``CacheAccess``-instance."""
        return Path.home().absolute().joinpath(".cache/id-translation/cached-fetcher-data/")

    @classmethod
    def clear_all_cache_data(cls) -> None:
        """Remove the entire cache directory tree for ALL instances."""
        import shutil

        cache_dir = cls.base_cache_dir_for_all_fetchers()
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
        self._base_dir = self.base_cache_dir_for_all_fetchers().joinpath(top_level_key)
        self._logger = logging.getLogger(__package__).getChild("CacheAccess").getChild(top_level_key)

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory used by this ``CacheAccess``.

        Created from :meth:`base_cache_dir_for_all_fetchers` and the first value of :attr:`CacheMetadata.cache_keys`.

        Returns:
            Cache dir for a single fetcher.
        """
        return self._base_dir

    @property
    def metadata_path(self) -> Path:
        return self._base_dir.joinpath("metadata.json")

    @property
    def data_path(self) -> Path:
        return self._base_dir.joinpath("data.pkl")

    def read_cache(self, source: SourceType) -> Optional[PlaceholderTranslations[SourceType]]:
        """Read cached translation data for `source`."""
        if not self._metadata.use_cached(self.metadata_path, self._max_age):
            return None

        with self.data_path.open("rb") as f:
            try:
                spt = pickle.load(f)  # noqa: S301
                ans = spt[source]
                if not isinstance(ans, PlaceholderTranslations):  # pragma: no cover
                    reason = f"Got {type(ans).__name__} but expected {PlaceholderTranslations.__name__}."
                    self.clear(reason)
                    raise TypeError(reason)

                self._logger.debug(f"Returning cached data for {source=}", extra=dict(source=source))
                return ans
            except (TypeError, KeyError, pickle.UnpicklingError) as e:
                # These errors indicate a likely corrupted cache. Any other is probably the users' fault.
                f.close()
                self.clear(f"Got error {e} while deserializing", log_level=logging.ERROR, exc_info=True)
        return None

    def write_cache(self, data: SourcePlaceholderTranslations[SourceType]) -> None:
        """Overwrite the current cache (if it exists) with new and update metadata."""
        if self.metadata_path.exists():
            self._logger.debug(f"Overwriting existing cache data in '{self.cache_dir}'.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.metadata_path.write_text(self._metadata.to_json())
        with self.data_path.open("wb") as f:
            pickle.dump(data, f)

    def clear(self, reason: str, log_level: int = logging.DEBUG, *, exc_info: bool = False) -> None:
        """Remove cached data for the current instance."""
        deleted = []

        if self.data_path.exists():
            self.data_path.unlink(missing_ok=True)
            deleted.append(self.data_path)

        if self.metadata_path.exists():
            self.metadata_path.unlink(missing_ok=True)
            deleted.append(self.metadata_path)

        if self._logger.isEnabledFor(log_level):
            delete_info = "\n".join(map("    - {}".format, deleted)) if deleted else "    There is nothing to delete."
            self._logger.log(
                log_level,
                f"Clear cache: {reason}. The following files have been deleted:\n{delete_info}",
                exc_info=exc_info,
            )
