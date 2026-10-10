"""User-defined transformations of IDs and translations.

See the :ref:`transformation-primer` for how to register transformers, and when they apply.
"""

from ._impl.bitmask import BitmaskTransformer
from ._impl.stack import TransformerStack, as_transformer

__all__ = [
    "BitmaskTransformer",
    "TransformerStack",
    "as_transformer",
]
