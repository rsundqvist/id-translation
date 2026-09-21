.. _translation-io:

Translation IO
==============
The :mod:`id_translation.dio` module defines how IDs are read and written to various data structures.

.. currentmodule:: id_translation.dio

Runtime arguments
-----------------
Relevant methods (e.g. :meth:`.Translator.translate`) accept an `io_kwargs` argument, which may be used to customize
the behavior of the :class:`.DataStructureIO` implementation. Exceptions raised due to invalid `io_kwargs` arguments
propagate to the caller; set :envvar:`ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS` to log and suppress them instead.

Arguments are implementation-specific. See :class:`~.integration.pandas.PandasIO` for an example.

User-defined integrations
-------------------------
The purpose of creating new integrations is typically to enable translation of a new data type.
To get started, inherit from :class:`DataStructureIO` or copy an
:class:`existing <.integration.polars.PolarsIO>` integration. Don't forget to
:meth:`register <.DataStructureIO.register>` the implementation, or the :class:`.Translator` won't be able to find it.

Integrations may take initialization arguments (see :ref:`Runtime arguments`), but should not require them.

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

A negative :attr:`~DataStructureIO.priority` makes an integration *opt-in* rather than unusable. The entrypoint is
still loaded, but the implementation is not considered until :meth:`~DataStructureIO.register` is called, after which
it is ordered by ``abs(priority)`` as any other integration is. Installing the underlying package is therefore not
enough to change how anything translates; the application has to ask.

Call :meth:`~DataStructureIO.unregister` to disable any implementation, including a bundled one. Of any sequence of
``register()`` and ``unregister()`` calls, the last one wins. The sign of `priority` only sets the initial state;
changing it later affects the order, never whether an implementation is enabled.

Selection process
-----------------
The :class:`~id_translation.Translator` will call :func:`.resolve_io` once per task. The first implementation whose
:meth:`DataStructureIO.handles_type`-method returns ``True`` will be used. The order in which implementations are
considered is determined by the magnitude of the :attr:`~DataStructureIO.priority` attribute. At equal magnitude, the
implementation registered most recently comes first, followed by those never registered, sorted by qualified name.

Bundled implementations have priority magnitudes in the `1000 - 1999` range (inclusive); the opt-in ones carry the
negative of theirs. See the table below.

..
   The csv-table directive does not work properly when used in src/id_translation/dio/__init__.py with :path:.

.. _io-implementations:

.. csv-table:: Ranking of built-in :class:`DataStructureIO` implementations.
   :file: io-ranks.csv
   :header-rows: 1

New implementations default to ``priority=10_000``, and are therefore considered first.

.. rubric:: Footnotes

.. [#automatic] Registered automatically if dependencies are installed.
.. [#explicit] Opt-in (negative ``priority``); requires an explicit :meth:`~DataStructureIO.register` call.
