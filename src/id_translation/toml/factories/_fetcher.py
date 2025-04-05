from typing import Any

from rics.misc import get_by_full_name

from id_translation.fetching import AbstractFetcher
from id_translation.types import IdType, SourceType


def default_fetcher_factory(clazz: str, config: dict[str, Any]) -> AbstractFetcher[SourceType, IdType]:
    """Create an :class:`.AbstractFetcher` from config."""
    from id_translation import fetching as default_module

    cls = get_by_full_name(
        clazz,
        default_module,
        subclass_of=AbstractFetcher,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
    )
    return cls(**config)
