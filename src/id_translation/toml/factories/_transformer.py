from typing import Any

from id_translation.transform.types import Transformer
from id_translation.types import IdType

from ._initialize import initialize


def default_transformer_factory(clazz: str, config: dict[str, Any]) -> Transformer[IdType]:
    """Create a :class:`.Transformer` from config."""
    from id_translation import transform as default_module  # noqa: PLC0415

    return initialize(
        clazz,
        config,
        Transformer,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
        default_module,
    )
