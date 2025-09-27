from typing import Any

from id_translation.fetching import CacheAccess
from id_translation.types import IdType, SourceType

from ._initialize import initialize


def default_cache_access_factory(clazz: str, config: dict[str, Any]) -> CacheAccess[SourceType, IdType]:
    """Create a :class:`.CacheAccess` from config."""
    return initialize(
        clazz,
        config,
        CacheAccess,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
        default_module=None,
    )
