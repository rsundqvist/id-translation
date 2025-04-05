"""Integration for insertion and extraction of IDs and translations to and from various data structures.

User-defined integrations
-------------------------
The purpose of creating new integrations is typically to enable translation of a new data type.
To get started, inherit from :class:`DataStructureIO` or copy an
:class:`existing <id_translation.dio.integration.polars>` integration. Don't forget to
:meth:`register <.DataStructureIO.register>` the implementation, or the :class:`.Translator` won't be able to find it.

Automatic integration discovery
-------------------------------
You may add an entrypoint in the :attr:`{entrypoint_group!r} <id_translation.dio.ENTRYPOINT_GROUP>` entrypoint group to
automatically register custom implementations (as opposed to calling :meth:`.DataStructureIO.register` manually). The
snippet below shows how the :mod:`bundled <.integration>` integrations are registered using project entrypoints.

.. code-block:: toml
   :caption: Entrypoints in ``pyproject.toml`` in the https://github.com/rsundqvist/id-translation/blob//v0.13.0/pyproject.toml#L45-L48 project.

   [project.entry-points."id_translation.dio.integration"]
   # Names are not used.
   dask_io = "id_translation.dio.integration.dask:DaskIO"
   polars_io = "id_translation.dio.integration.polars:PolarsIO"

The :func:`loader <id_translation.dio.load_integrations>` will skip the integration if calling
:class:`EntryPoint.load() <importlib.metadata.EntryPoint>` raises an :py:class:`ImportError`.

.. autodata:: id_translation.dio::ENTRYPOINT_GROUP
"""

# The autodata is a workaround for ENTRYPOINT_GROUP
#   https://github.com/sphinx-doc/sphinx/issues/6495#issuecomment-1058033697
#   https://github.com/sphinx-doc/sphinx/issues/12020

from ._data_structure_io import DataStructureIO
from ._resolve import (
    ENTRYPOINT_GROUP,
    get_resolution_order,
    is_registered,
    load_integrations,
    register_io,
    resolve_io,
)

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
__doc__ = __doc__.format(entrypoint_group=ENTRYPOINT_GROUP)
