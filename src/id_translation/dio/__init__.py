"""Insertion and extraction of IDs and translations.

See :doc:`/documentation/translation-io` for help.
"""

from ._data_structure_io import DataStructureIO
from ._resolve import (
    get_resolution_order,
    is_registered,
    load_integrations,
    register_io,
    resolve_io,
)
from ._util import pretty_io_name

ENTRYPOINT_GROUP: str = "id_translation.dio"  # Public reexport. Must match _repository.ENTRYPOINT_GROUP.
"""Group used to discover :class:`DataStructureIO` integrations.

See :func:`load_integrations` and :py:func:`importlib.metadata.entry_points` for details.
"""

__all__ = [
    "ENTRYPOINT_GROUP",
    "DataStructureIO",
    "get_resolution_order",
    "is_registered",
    "load_integrations",
    "pretty_io_name",
    "register_io",
    "resolve_io",
]
