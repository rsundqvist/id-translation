.. _translator-config:

Configuration
=============
This document describes the TOML format used by the
:meth:`Translator.from_config() <id_translation.Translator.from_config>`-method.

.. hint::
    Functions or classes are resolved by name using :func:`rics.misc.get_by_full_name`.

    Unqualified names are assumed to
    belong to an appropriate ``id_translation`` module. To specify a custom implementation, use
    ``'fully.qualified.names'`` (in quotation marks).

Meta configuration
------------------
The ``metaconf.toml``-file must be placed next to the main TOML configuration file, and determines how other files are
processed by the the factory.

.. list-table:: Sections: ``[env]``
   :header-rows: 1
   :widths: 15 60 25

   * - Top-level section
     - Description
     - Details
   * - ``[env]``
     - | Control environment-variable interpolation; ``${VAR}`` or
       | ``${VAR:default}``. Default is ``true`` for :meth:`~.Translator.from_config`.
     - :func:`~id_translation.utils.load_toml_file`.

.. note::

   The ``metaconf.toml``-file is `always` read as-is, without any processing.

Sections
--------
The only valid top-level keys are ``translator``, ``unknown_ids``, and ``fetching``. Only the ``fetching`` section is
required, though it may be left out of the main configuration file if fetching is configured separately. Other top-level
keys will raise a :class:`~id_translation.exceptions.ConfigurationError` if present.

Section: Translator
-------------------
.. list-table:: Section keys: ``[translator]``
   :header-rows: 1

   * - Key
     - Type
     - Description
   * - fmt
     - :class:`~id_translation.offline.Format`
     - Specify how translated IDs are displayed.
   * - enable_uuid_heuristics
     - :py:class:`bool`
     - Enabling may improve matching when :py:class:`~uuid.UUID`-like IDs are in use.

* Parameters for :attr:`Name <id_translation.types.NameType>`-to-:attr:`source <id_translation.types.SourceType>`
  mapping are specified in a ``[translator.mapping]``-subsection. See: :ref:`Subsection: Mapping` for details (context =
  :attr:`source <id_translation.types.SourceType>`).

Section: Unknown IDs
--------------------
.. list-table:: Section keys: ``[unknown_ids]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - fmt
     - :class:`~id_translation.offline.Format`
     - Specify a format for untranslated IDs.
     - Can be a plain string ``fmt='Unknown'``, or ``fmt='{id}'`` to leave as-is.

* Alternative :attr:`placeholder <id_translation.offline.Format.placeholders>`-values for unknown IDs can be declared
  in a ``[unknown_ids.overrides]``-subsection. See: :ref:`Subsection: Overrides` for details (context =
  :attr:`source <id_translation.types.SourceType>`).

.. note::

   Sources that are translated using default placeholders count as successful translations when using
   :meth:`Translator.translate(max_fails != 1) <.Translator.translate>`.

.. _translator-config-transform:

Section: Transformations
------------------------
You may specify one :class:`.Transformer` per source. Subsection keys are passed directly to the ``init``-method of the
chosen transformer type. For available transformers, see the :mod:`API documentation <.transform>`.

.. note::

   You may add ``[transform.'<source>']``-sections either in the main configuration file, or in an auxiliary fetcher
   configuration. It is a :class:`~id_translation.exceptions.ConfigurationError` to specify transformations for the same
   `source` more than once.


For example, to configure a :class:`.BitmaskTransformer`, add a section on the form
``[transform.'<source>'.BitmaskTransformer]`` to an appropriate configuration file:

.. code-block:: toml

   [transform.'<source>'.BitmaskTransformer]
   joiner = " AND "
   overrides = [
       { id = 0, override = "NOT_SET" },
       { id = 0b1000, override = "OVERFLOW" },
   ]

This will create a transform that formats bitmasks such as ``0b101`` in the following way:

.. code-block:: python

   translator.translate((0b000, 0b101, 8), name="<source>")
   ("NOT_SET", "1:name-of-1 AND 4:name-of-4", "OVERFLOW")

.. hint::

   Custom transformers may be initialized by using sections with fully qualified type names.

For example, a ``[transform.'<source>'.'my.library.SuperTransformer']``-section would import and initialize a
``SuperTransformer`` from the ``my.library`` module.

.. _translator-config-fetching:

Section: Fetching
-----------------
The type of the fetcher is determined by the second-level key (other than ``mapping``, which is reserved). For example,
a :class:`~id_translation.fetching.MemoryFetcher` would be created by adding a ``[fetching.MemoryFetcher]``-section.

.. list-table:: Section keys: ``[fetching]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - allow_fetch_all
     - :py:class:`bool`
     - Control access to :func:`~id_translation.fetching.Fetcher.fetch_all`.
     - Some fetchers types redefine or ignore this key.
   * - | fetch_all_unmapped
       | _values_action
     - `raise | warn | ignore`
     - Special action level for :func:`~id_translation.fetching.Fetcher.fetch_all`.
     - Interacts with `selective_fetch_all`.
   * - selective_fetch_all
     - :py:class:`bool`
     - Sources without required keys are are not fetched.
     - | Implicit `fetch_all_unmapped`
       | `_values_action='ignore'`
   * - | fetch_all_cache
       | _max_age
     - :class:`pandas.Timedelta`
     - Specified as a string, eg `'12h'` or `'30d'`.
     - Set to non-zero value to enable.
   * - cache_keys
     - :py:class:`Sequence[str] <typing.Sequence>`
     - Hierarchical identifier for the cache.
     - Provided automatically if not given.
   * - optional
     - :py:class:`bool`
     - If ``True``, discard on :attr:`~id_translation.fetching.Fetcher.sources`-resolution crash.
     - Multi-fetcher mode only.
   * - | concurrent_operation
       | _action
     - `raise | ignore`
     - Action to take if fetch(-all) operations are executed concurrently.
     - Should be set to ``'ignore'`` for thread-safe fetchers

The keys listed above are for the :class:`~id_translation.fetching.AbstractFetcher` class, which all fetchers created by
TOML configuration must inherit. Additional parameters vary based on the chosen implementation. See the
:mod:`id_translation.fetching` module for choices.

The ``AbstractFetcher`` uses a  a :class:`~id_translation.mapping.Mapper` to bind actual
:attr:`placeholder <id_translation.fetching.Fetcher.placeholders>` names in
:attr:`~id_translation.fetching.Fetcher.sources` to desired
:attr:`placeholder names <id_translation.offline.Format.placeholders>` requested by the calling Translator instance.
See: :ref:`Subsection: Mapping` for details. For all mapping operations performed by the ``AbstractFetcher``, context =
:attr:`source <id_translation.types.SourceType>`.

.. hint::

   Custom fetchers may be initialized by using sections with fully qualified type names in single quotation marks. For
   example, a ``[fetching.'my.library.SuperFetcher']``-section would import and initialize a ``SuperFetcher`` from the
   ``my.library`` module.

   Under the hood, this will call :func:`~rics.misc.get_by_full_name` using ``name="my.library.SuperFetcher"``.


Multiple fetchers
~~~~~~~~~~~~~~~~~
Complex applications may require multiple fetchers. These may be specified in auxiliary config files, one fetcher per
file. Only the ``fetching`` key will be considered in these files. If multiple fetchers are defined, a
:class:`~id_translation.fetching.MultiFetcher` is created. Fetchers defined this way are **hierarchical**. The input
order determines rank, affecting Name-to-:attr:`source <id_translation.fetching.Fetcher.sources>` mapping. For
example, for a ``Translator`` created by running

>>> from id_translation import Translator
>>> extra_fetchers=["primary-fetcher.toml", "secondary-fetcher.toml"]
>>> Translator.from_config("translation.toml", extra_fetchers=extra_fetchers)

the :func:`Translator.map <id_translation.Translator.map>`-function will first consider the sources of the fetcher
defined in `translation.toml` (if there is one), then `primary-fetcher.toml` and finally `secondary-fetcher.toml`.

.. list-table:: Section keys: ``[fetching.MultiFetcher]`` (main config only)
   :header-rows: 1

   * - Key
     - Type
     - Description
   * - max_workers
     - :py:class:`int`
     - Maximum number of individual child fetchers to call in parallel.
   * - duplicate_translation_action
     - `raise | warn | ignore`
     - Action to take when multiple fetchers return translations for the same source.
   * - duplicate_source_discovered_action
     - `raise | warn | ignore`
     - Action to take when multiple fetchers claim the same source.

The ``[fetching.MultiFetcher]`` section is permitted only in the main configuration file.

.. _translator-config-mapping:

Subsection: Mapping
-------------------
For more information about the mapping procedure, please refer to the :ref:`mapping-primer` page.

.. list-table:: Section keys: ``[*.mapping]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - score_function
     - :attr:`~id_translation.mapping.types.ScoreFunction`
     - Compute value/candidate-likeness
     - See: :mod:`id_translation.mapping.score_functions`
   * - unmapped_values_action
     - `raise | warn | ignore`
     - Handle unmatched values.
     - See: :class:`rics.action_level.ActionLevel`
   * - cardinality
     - `OneToOne | ManyToOne`
     - Determine how many candidates to map a single value to.
     - See: :class:`id_translation.mapping.Cardinality`

* Score functions which take additional keyword arguments should be specified in a child section, eg
  ``[*.mapping.<score-function-name>]``. See: :mod:`id_translation.mapping.score_functions` for options.
* External functions may be used by putting fully qualified names in single quotation marks. Names which do not contain
  any dot characters (``'.'``) are assumed to refer to functions in the appropriate ``id_translation.mapping`` submodule.

.. hint::

   For difficult matches, consider using :ref:`overrides <Subsection: Overrides>` instead.

Filter functions
~~~~~~~~~~~~~~~~
Filters are given in ``[[*.mapping.filter_functions]]`` **list**-subsections. These may be used to remove undesirable
matches, for example SQL tables which should not be used or a ``DataFrame`` column that should not be translated.

.. list-table:: Section keys: ``[[*.mapping.filter_functions]]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - function
     - :py:class:`str`
     - Function name.
     - See: :mod:`id_translation.mapping.filter_functions`

.. note::

   Additional keys depend on the chosen function implementation.

As an example, the next snippet ensures that only names ending with an ``'_id'``-suffix will be translated by using a
:func:`~id_translation.mapping.filter_functions.filter_names`-filter.

.. code-block:: toml

    [[translator.mapping.filter_functions]]
    function = "filter_names"
    regex = ".*_id$"
    remove = false  # This is the default (like the built-in filter).

Score function
~~~~~~~~~~~~~~
There are some :attr:`~id_translation.mapping.types.ScoreFunction` s which take additional keyword arguments. These must
be declared in a ``[*.overrides.<score-function-name>]``-subsection. See: :mod:`id_translation.mapping.score_functions`
for options.

Score function heuristics
~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristics may be used to aid an underlying `score_function` to make more difficult matches. There are two types of
heuristic functions: :attr:`~id_translation.mapping.types.AliasFunction` s and Short-circuiting functions (which are
really just differently interpreted :attr:`~id_translation.mapping.types.FilterFunction` s).

Heuristics are given in ``[[*.mapping.score_function_heuristics]]`` **list**-subsections (note the double brackets) and
are applied in the order in which they are given by the :class:`~id_translation.mapping.HeuristicScore` wrapper
class.

.. list-table:: Section keys: ``[[*.mapping.score_function_heuristics]]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - function
     - :py:class:`str`
     - Function name.
     - See: :mod:`id_translation.mapping.heuristic_functions`
   * - mutate
     - :py:class:`bool`
     - Keep changes made by `function`.
     - Disabled by default.

.. note::

   Additional keys depend on the chosen function implementation.

As an example, the next snippet lets us match table columns such as `animal_id` to the `id` placeholder by using a
:func:`~id_translation.mapping.heuristic_functions.value_fstring_alias` heuristic.

.. code-block:: toml

    [[fetching.mapping.score_function_heuristics]]
    function = "value_fstring_alias"
    fstring = "{context}_{value}"

.. hint::

   For difficult matches, consider using :ref:`overrides <Subsection: Overrides>` instead.

Subsection: Overrides
---------------------
Shared or context-specific key-value pairs implemented by the :class:`~rics.collections.dicts.InheritedKeysDict`
class. When used in config files, these appear as ``[*.overrides]``-sections. Top-level override items are given in the
``[*.overrides]``-section, while context-specific items are specified using a subsection, eg
``[*.overrides.<context-name>]``.

.. note::

   The type of ``context`` is determined by the class that owns the overrides.

This next snipped is from :doc:`another example <examples/notebooks/pickle-translation/PickleFetcher>`. For unknown IDs,
the name is set to `'Name unknown'` for the `'name_basics'` source and `'Title unknown'` for the `'title_basics'`
source, respectively. They both inherit the `from` and `to` keys which rare set to `'?'`.

.. code-block:: toml

    [unknown_ids.overrides]
    from = "?"
    to = "?"

    [unknown_ids.overrides.name_basics]
    name = "Name unknown"
    [unknown_ids.overrides.title_basics]
    name = "Title unknown"

.. warning::

   Overrides have no fixed keys. No validation is performed and errors may be silent. The
   :attr:`mapping process <id_translation.mapping.Mapper.apply>` provides detailed information in debug mode, which may
   be used to discover issues.

.. hint::

   Overrides may also be used to `prevent` mapping certain values.

Preventing unwanted mappings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
For example, let's assume that a SQL source table called `title_basics` with two columns `title` and `name` with
identical contents. We would like to use a format ``'[{title}. ]{name}'`` to output translations such as
`'Mr. Astaire'`. To avoid output such as `'Top Hat. Top Hat'` for movies, we may add

.. code-block:: toml

  [fetching.mapping.overrides.movies]
  title = "_"

to force the fetcher to inform the ``Translator`` that the `title` placeholder (column) does not exist for the
`title_basics` source (we used `'_'` since TOML `does not have <https://github.com/toml-lang/toml/issues/30>`__ a
``null``-type).
