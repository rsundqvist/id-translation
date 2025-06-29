Translation IO
==============
The :mod:`id_translation.dio` module defines how IDs are read and written to various data structures.

.. currentmodule:: id_translation.dio

User-defined integrations
-------------------------
The purpose of creating new integrations is typically to enable translation of a new data type.
To get started, inherit from :class:`DataStructureIO` or copy an
:class:`existing <id_translation.dio.integration.polars>` integration. Don't forget to
:meth:`register <.DataStructureIO.register>` the implementation, or the :class:`.Translator` won't be able to find it.

Automatic integration discovery
-------------------------------
You may add an entrypoint in the ``'id_translation.dio'`` entrypoint group to
automatically register custom implementations (as opposed to calling :meth:`.DataStructureIO.register` manually). The
snippet below shows how the :mod:`bundled <.integration>` integrations are registered using project entrypoints.

.. code-block:: toml
   :caption: Entrypoints in ``pyproject.toml`` in the
        https://github.com/rsundqvist/id-translation/blob/v0.15.0/pyproject.toml#L50-L54 project.

   [project.entry-points."id_translation.dio"]
   # The name (e.g. 'pandas_io') is not important, but should be unique.
   pandas_io = "id_translation.dio.integration.pandas:PandasIO"
   dask_io = "id_translation.dio.integration.dask:DaskIO"
   polars_io = "id_translation.dio.integration.polars:PolarsIO"

The :func:`loader <id_translation.dio.load_integrations>` will skip the integration if calling
:class:`EntryPoint.load() <importlib.metadata.EntryPoint>` raises an :py:class:`ImportError`.

Selection process
-----------------
The :class:`~id_translation.Translator` will call :func:`.resolve_io` once per task. The first implementation whose
:meth:`DataStructureIO.handles_type`-method returns ``True`` will be used. The order in which implementations are
considered is determined by the :attr:`~DataStructureIO.priority` attribute.

Bundled implementations have priorities in the `1000 - 1999` range (inclusive); see the table below.

..
   The csv-table directive does not work properly when used in src/id_translation/dio/__init__.py with :path:.

.. csv-table:: Ranking of built-in :class:`DataStructureIO` implementations.
   :file: io-ranks.csv
   :header-rows: 1

New implementations default to ``priority=10_000`` and are therefore considered first.
