from typing import Any

from id_translation.fetching import AbstractFetcher
from id_translation.types import IdType, SourceType

from ._initialize import initialize


def default_fetcher_factory(clazz: str, config: dict[str, Any]) -> AbstractFetcher[SourceType, IdType]:
    """Create an :class:`.AbstractFetcher` from config."""
    from id_translation import fetching as default_module  # noqa: PLC0415

    return initialize(
        clazz,
        config,
        AbstractFetcher,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
        default_module,
    )
