"""Insertion and extraction of IDs and translations.

See :doc:`/documentation/translation-io` for help.
"""

from ._data_structure_io import DataStructureIO
from ._resolve import (
    _ENTRYPOINT_GROUP,
    get_resolution_order,
    is_registered,
    load_integrations,
    register_io,
    resolve_io,
)

ENTRYPOINT_GROUP: str = _ENTRYPOINT_GROUP  # Public reexport. Makes Sphinx happy.
"""Group used to discover :class:`DataStructureIO` integrations.

See :func:`load_integrations` and :py:func:`importlib.metadata.entry_points` for details.
"""

__all__ = [
    "ENTRYPOINT_GROUP",
    "DataStructureIO",
    "get_resolution_order",
    "is_registered",
    "load_integrations",
    "register_io",
    "resolve_io",
]

load_integrations()
