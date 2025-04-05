from typing import Any

from rics.misc import get_by_full_name

from id_translation.fetching import CacheAccess
from id_translation.types import IdType, SourceType


def default_cache_access_factory(clazz: str, config: dict[str, Any]) -> CacheAccess[SourceType, IdType]:
    """Create a :class:`.CacheAccess` from config."""
    cls = get_by_full_name(
        clazz,
        subclass_of=CacheAccess,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
    )
    return cls(**config)
