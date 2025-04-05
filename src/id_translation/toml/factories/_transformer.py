from typing import Any

from rics.misc import get_by_full_name

from id_translation.transform.types import Transformer
from id_translation.types import IdType


def default_transformer_factory(clazz: str, config: dict[str, Any]) -> Transformer[IdType]:
    """Create a :class:`.Transformer` from config."""
    from id_translation import transform as default_module

    cls = get_by_full_name(
        clazz,
        default_module,
        subclass_of=Transformer,  # type: ignore[type-abstract]  # https://github.com/python/mypy/issues/4717
    )
    return cls(**config)
