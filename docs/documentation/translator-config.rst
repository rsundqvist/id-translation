.. _translator-config:

Configuration
=============
This document describes the TOML format used by the
:meth:`Translator.from_config() <id_translation.Translator.from_config>`-method.

.. seealso::
   Adding ``id-translation`` to a codebase you already have? The :ref:`adoption guide <migration-guide>` walks through
   it end to end, including the recommended single ``create_translator()`` entry point.

.. note::
   Unqualified names are assumed to belong to an appropriate ``id_translation`` module. To specify a custom
   implementation, use ``'fully.qualified.names'`` (in quotation marks). Names are resolved by
   :func:`rics.misc.get_by_full_name`.

Minimal configuration
---------------------
Only a ``fetching`` section is required. This file, saved as ``translation.toml``:

.. code-block:: toml

   [translator]
   fmt = "{id}:{name}"

   [fetching.SqlFetcher]
   connection_string = "postgresql://localhost/db"

is loaded with ``Translator.from_config("translation.toml")``.

Sections
--------
The valid top-level keys are ``translator``, ``fetching``, ``unknown_ids``, and ``transform`` (the
:attr:`~.TranslatorFactory.TOP_LEVEL_KEYS`). Only the ``fetching`` section is required, though it may be left out of
the main configuration file if fetching is configured separately. Any other top-level key
will raise a :class:`~id_translation.exceptions.ConfigurationError`.

Section: Translator
-------------------
.. list-table:: Section keys: ``[translator]``
   :header-rows: 1

   * - Key
     - Type
     - Description
   * - fmt
     - :class:`~id_translation.offline.Format`
     - Specify how translated IDs are displayed. Defaults to ``{id}:{name}``; use ``fmt = "{name}"`` for the label alone.
   * - enable_uuid_heuristics
     - :py:class:`bool`
     - Improves matching when :py:class:`~uuid.UUID`-like IDs are in use.

* Parameters for :attr:`Name <id_translation.types.NameType>`-to-:attr:`source <id_translation.types.SourceType>`
  mapping are specified in a ``[translator.mapping]``-subsection. See: :ref:`Subsection: Mapping` for details (no
  context).

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

.. _translator-config-fetching:

Section: Fetching
-----------------
The type of the fetcher is determined by the second-level key (:ref:`mapping <translator-config-mapping>`, :ref:`cache
<Caching>` and :ref:`MultiFetcher <Multiple fetchers>` reserved). For example, a
:class:`~id_translation.fetching.MemoryFetcher` would be created by adding a ``[fetching.MemoryFetcher]``-section. A
single file may only declare **one** fetcher this way; a single fetcher commonly serves many sources (e.g. one
``SqlFetcher`` across several tables); see :ref:`Multiple fetchers` below if you need to *combine* fetchers, e.g. a
``SqlFetcher`` alongside a ``MemoryFetcher``.

The :class:`~id_translation.fetching.MemoryFetcher` is handy for small, static sources. Give each source one column per
placeholder (``id`` and ``name`` at minimum):

.. code-block:: toml

   [fetching.MemoryFetcher.data.customers]
   id = [1, 2]
   name = ["Alice", "Bob"]

See :meth:`.PlaceholderTranslations.make` for the other accepted ``data`` forms. For string-keyed sources, a scalar
shorthand (``P = "Pending"``) is often handier; the :ref:`adoption guide <migration-guide>` uses it. Avoid it
for integer IDs: TOML keys are always strings, so ``101 = "Widget"`` would key the row under the string ``"101"``.

.. list-table:: Section keys: ``[fetching.<Type>]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - allow_fetch_all
     - :py:class:`bool`
     - Control access to :func:`~id_translation.fetching.Fetcher.fetch_all`.
     - Some fetcher types redefine or ignore this key.
   * - selective_fetch_all
     - :py:class:`bool`
     - ``fetch_all`` skips sources that lack a required placeholder (after mapping).
     -
   * - identifiers
     - :py:class:`Sequence[str] <typing.Sequence>`
     - Hierarchical identifiers for the fetcher.
     - Based on source file if not given.
   * - optional
     - :py:class:`bool`
     - If ``True``, discard on :attr:`~id_translation.types.HasSources.sources`-resolution crash.
     - Multi-fetcher mode only. See :ref:`Optional fetchers` for details.

The keys listed above are for the :class:`~id_translation.fetching.AbstractFetcher` class, which all fetchers created by
TOML configuration must inherit. Additional parameters vary based on the chosen implementation. See the
:mod:`id_translation.fetching` module for choices.

The ``AbstractFetcher`` uses a :class:`~id_translation.mapping.Mapper` to bind actual
:attr:`placeholder <id_translation.types.HasSources.placeholders>` names in
:attr:`~id_translation.types.HasSources.sources` to desired
:attr:`placeholder names <id_translation.offline.Format.placeholders>` requested by the calling ``Translator`` instance.
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
file. These files may only contain ``fetching`` and ``transform`` sections. If multiple fetchers are defined, a
:class:`~id_translation.fetching.MultiFetcher` is created. Fetchers defined this way are **hierarchical**. The input
order determines rank, affecting Name-to-:attr:`source <id_translation.types.HasSources.sources>` mapping. For
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
     - ``int``
     - Maximum number of individual child fetchers to call in parallel.
   * - on_source_conflict
     - `raise | warn | ignore`
     - Action for disputes during :meth:`source discovery <.Fetcher.initialize_sources>`.
   * - fetcher_discarded_log_level
     - ``int | str``
     - Log level used when an :attr:`~.Fetcher.optional` fetcher is discarded because
       :meth:`source discovery <.Fetcher.initialize_sources>` failed.

.. _optional-fetchers:

Optional fetchers
~~~~~~~~~~~~~~~~~
:meth:`Optional <.Fetcher.optional>` fetchers are allowed to raise when :meth:`.Fetcher.initialize_sources` is called.
Fetchers should **not** raise when imported or initialized. To suppress init errors (e.g. :class:`ModuleNotFoundError`),
the config file must specify ``optional = true`` in the class init args:

.. code-block:: toml

   [fetching."my_module.MyFetcher"]
   optional = true

The :envvar:`ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS` variable must also be ``true``. The
:class:`~id_translation.toml.TranslatorFactory` will always use the ``ERROR`` level for fetchers that are discarded this
way.

.. warning::

   Using ``ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS=true`` can and often will hide configuration errors
   (e.g. misspelled argument names) or broken packages.

A fetcher discarded because it failed to *initialize* takes its file's
:ref:`[transform]-section <translator-config-transform>` with it, in the main configuration as well as in an auxiliary
one. A fetcher discarded later, when :meth:`.Fetcher.initialize_sources` raises, does not: the section was built when
the configuration was read. Its transformers stay registered, and apply to nothing unless a surviving fetcher serves
the same source.

.. note::

   ``optional = true`` covers an unavailable *data source*, not an unreadable file: the file must parse, and its
   top-level sections are checked, before any fetcher is built. The ``[transform]``-section itself is built after the
   discard check, so a malformed one is a :class:`~id_translation.exceptions.ConfigurationError` only when its fetcher
   survives: a discarded fetcher takes even a broken section with it.

Caching
~~~~~~~
A fetcher can have one :class:`.CacheAccess`, declared in the same file as the fetcher by a
``[fetching.cache.'<type>']`` section. Like fetchers and transformers, the section is keyed by the fully qualified type
name, and its keys are passed to the constructor as-is:

.. code-block:: toml

   [fetching.SqlFetcher]
   connection_string = "postgresql://localhost/db"

   [fetching.cache.'my.library.MyCacheAccess']
   ttl = 3600  # Cache timeout in seconds

This is equivalent to ``SqlFetcher(connection_string=..., cache_access=MyCacheAccess(ttl=3600))``. With
:ref:`Multiple fetchers`, each file's cache applies only to the fetcher declared in that file.

.. _choosing-a-cache:

Choosing a caching strategy
^^^^^^^^^^^^^^^^^^^^^^^^^^^
Before implementing a :class:`.CacheAccess`, check whether a simpler built-in mechanism already fits. All three avoid
re-fetching translation data; they differ in scope, lifetime, and storage.

.. list-table::
   :header-rows: 1

   * - Mechanism
     - Scope
     - Lifetime
     - Storage
     - Use when
   * - :meth:`~.Translator.go_offline`
     - Whole :class:`.Translator`
     - In-process; discards the fetcher
     - Memory
     - Required IDs are known in advance.
   * - :meth:`~.Translator.load_persistent_instance`
     - Whole :class:`.Translator`
     - Cross-process; reused until it :meth:`must be recreated <.Translator.load_persistent_instance>`
     - Disk (:mod:`pickle`)
     - The cache should be shared or reused between processes.
   * - :class:`.CacheAccess`
     - Per source
     - User-defined
     - User-defined
     - You need per-source control, or want to avoid the others' trade-offs.


Implementing ``CacheAccess``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
This library does not provide any ``CacheAccess`` implementations.

Instead, users may implement the :class:`.CacheAccess` interface to define their own caching logic. The
:class:`.AbstractFetcher` will then call :meth:`.CacheAccess.load` and :meth:`.CacheAccess.store` when appropriate.

.. seealso::

   The :ref:`on-disk <caching_example>` and :ref:`in-memory <in_memory_caching_example>` ``CacheAccess`` examples.


.. _translator-config-mapping:

Subsection: Mapping
-------------------
Mapping binds names to sources in ``[translator.mapping]``, and placeholders to source columns in
``[fetching.mapping]``; ``*`` below stands for either. The :ref:`mapping-primer` explains the procedure and the terms it
uses (values, candidates and context).

.. list-table:: Section keys: ``[*.mapping]``
   :header-rows: 1

   * - Key
     - Type
     - Description
     - Comments
   * - score_function
     - :attr:`~id_translation.mapping.types.ScoreFunction`
     - Compute value/candidate-likeness
     - See built-in :mod:`~id_translation.mapping.score_functions`.
   * - min_score
     - :py:class:`float`
     - Minimum score for a match.
     - Default ``0.90``.
   * - on_unmapped
     - `raise | warn | ignore`
     - Handle unmatched values.
     -
   * - on_unknown_user_override
     - `raise | warn | keep`
     - Handle an override function returning an unknown candidate.
     -
   * - cardinality
     - :class:`~id_translation.mapping.Cardinality`
     - Determine how many candidates to map a single value to.
     - E.g. `'1:1'` or `'N:1'`.

* External functions may be used by putting fully qualified names in single quotation marks. Names which do not contain
  any dot characters (``'.'``) are assumed to refer to functions in the appropriate ``id_translation.mapping`` submodule.

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
     - See built-in :mod:`~id_translation.mapping.filter_functions`.

.. note::

   Additional keys depend on the chosen function implementation.

As an example, the next snippet ensures that only names ending with an ``'_id'``-suffix will be translated by using a
:func:`~id_translation.mapping.filter_functions.filter_names`-filter.

.. code-block:: toml

    [[translator.mapping.filter_functions]]
    function = "filter_names"
    regex = ".*_id$"
    remove = false  # The default.

Score function
~~~~~~~~~~~~~~
Some score functions (:attr:`~id_translation.mapping.types.ScoreFunction`) take additional keyword arguments, given in a
``[*.mapping.score_function.<name>]``-subsection instead of the ``score_function`` key. At most one may be given:

.. code-block:: toml
   :caption: Arguments for the :func:`~id_translation.mapping.score_functions.modified_hamming` scorer.

   [translator.mapping.score_function.modified_hamming]
   add_length_ratio_term = false

See :mod:`id_translation.mapping.score_functions` for options.

Score function heuristics
~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristics may be used to aid an underlying `score_function` to make more difficult matches. There are two types of
heuristic functions: alias functions (:attr:`~id_translation.mapping.types.AliasFunction`), and short-circuiting
functions such as :func:`~id_translation.mapping.heuristic_functions.short_circuit`, which are filter functions whose
returned candidates are treated as overrides.

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
     - See built-in :mod:`~id_translation.mapping.heuristic_functions`.
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

   For difficult matches, consider using :ref:`overrides <Subsection: Overrides>` instead of match scores.

Subsection: Overrides
---------------------
Overrides pin a mapping by hand, bypassing scoring: a name to a source in ``[translator.mapping.overrides]``, or a
placeholder to a column in ``[fetching.mapping.overrides]``.

.. code-block:: toml

   [translator.mapping.overrides]       # name -> source
   created_by = "staff"

   [fetching.mapping.overrides.staff]   # placeholder -> column, for the 'staff' source only
   id = "staff_id"

Overrides are implemented by the :class:`~rics.collections.dicts.InheritedKeysDict` class. Top-level items in a
``[*.overrides]``-section are shared, while a ``[*.overrides.<context-name>]`` subsection holds context-specific items.

.. note::

   The type of ``context`` is determined by the class that owns the overrides. For fetchers, it is the source: each
   source has its own columns, so placeholder overrides may differ per source. The ``Translator`` has no context,
   since a name is matched against every source at once; its overrides must be top-level, and a subsection raises
   :class:`~id_translation.exceptions.ConfigurationError`.

The same structure supplies placeholder values for unknown IDs. This next snippet is from :doc:`another example
<examples/notebooks/pickle-translation/PickleFetcher>`. For unknown IDs, the `name` placeholder is set to `'Name
unknown'` for the `'name_basics'` source and `'Title unknown'` for the `'title_basics'` source. Both inherit the `from`
and `to` placeholders, which are set to `'?'`.

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
For example, assume that a SQL source table called `title_basics` has two columns, `title` and `name`, with
identical contents. We would like to use a format ``'[{title}. ]{name}'`` to output translations such as
`'Mr. Astaire'`. To avoid output such as `'Top Hat. Top Hat'` for movies, we may add

.. code-block:: toml

  [fetching.mapping.overrides.title_basics]
  title = "_"

to force the fetcher to inform the ``Translator`` that the `title` placeholder (column) does not exist for the
`title_basics` source (we used `'_'` since TOML `does not have <https://github.com/toml-lang/toml/issues/30>`__ a
``null``-type).

.. _translator-config-transform:

Section: Transformations
------------------------
Transformers are declared using ``[transform.'<source>'.'<transformer-type>']`` sections. Subsection keys are passed
directly to the ``__init__``-method of the chosen transformer type.

For example, to configure a :class:`.BitmaskTransformer` for a ``permissions`` source, add a section on the form
``[transform.'<source>'.BitmaskTransformer]`` to an appropriate configuration file. The ``overrides`` are a list of
tables because TOML keys must be strings:

.. code-block:: toml

   [transform.permissions.BitmaskTransformer]
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

   Custom transformers may be initialized by using sections with fully qualified type names. For example, a
   ``[transform.'<source>'.'my.library.SuperTransformer']``-section would import and initialize a ``SuperTransformer``
   from the ``my.library`` module.

Chaining transformers
~~~~~~~~~~~~~~~~~~~~~
You may specify any number of :class:`.Transformer`\ s per source.  Both the main and auxiliary files may contain
``[transform.'<source>'.'<transformer-type>']`` sections for the same `source`. This creates a :class:`.TransformerStack`.
The :class:`.Translator` owns all transformers, regardless of where they're defined.

**Priority**:

* Transformers declared in the same file run in declaration order.
* Auxiliary fetcher files run before the main file.
* Fetcher-provided transformers run before any declared for the same source.
* Equal transformers -- by identity, or by ``__eq__`` -- are the same transformer, so a provided one that is
  already in the chain is not added again.
* Each transformer sees -- and may overwrite -- the effects of those before it.

Sections are keyed by type, so a transformer type may appear at most once per source and file. To chain two
identically-typed transformers, declare them in different files or
:ref:`register them in code <Programmatic transformer registration>`.

Programmatic transformer registration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
There are two ways to perform post-initialization transformer registration:

1. The :meth:`.Translator.register_transformer` method, and
2. The :meth:`.Fetcher.get_transformer` method.

Extending the ``create_translator()`` factory function (see https://github.com/rsundqvist/id-translation-project/) to
take advantage of :meth:`~.Translator.register_transformer` to register bitmask sources is simple:

.. code-block:: python

   t = Translator(...)
   t.initialize_sources()
   for source in t.sources:
       if source.endswith("_bitmask"):
           t.register_transformer(source, BitmaskTransformer())
           t.register_transformer(source, CustomTransformer(), on_existing="append")

This assumes that naming is consistent. Custom fetchers may instead prefer to override :meth:`.Fetcher.get_transformer`,
e.g. to register :py:class:`~enum.IntFlag` enums.

The :meth:`.Translator.initialize_sources` method calls :meth:`~.Fetcher.get_transformer` for all sources, so
**fetcher-provided** transformers are **used automatically**.

Meta configuration
------------------
The ``metaconf.toml``-file must be placed next to the main TOML configuration file, and determines how other files are
processed by the factory. See :class:`~id_translation.toml.meta.Metaconf` for internal representation.

You rarely need this file: environment-variable interpolation (``${VAR}`` / ``${VAR:default}``) is **on by default**.
Add a ``metaconf.toml`` only to *change* that default. See :class:`.ConfigMetadata` for details.

.. list-table:: The ``metaconf.toml`` file format.
   :header-rows: 1
   :widths: 20 20 60

   * - Top-level section
     - Type
     - Description
   * - ``[env]``
     - :class:`~id_translation.toml.meta.EnvConf`
     - Control environment-variable interpolation; ``${VAR}`` or ``${VAR:default}``. Keys: ``allow_interpolation``
       (default ``true``), ``allow_blank`` (default ``false``: raise if a variable resolves to an empty string, as
       ``${VAR:}`` does when ``VAR`` is unset), and ``allow_nested`` (default ``false``).
   * - ``[equivalence]``
     - :class:`~id_translation.toml.meta.EquivalenceConf`
     - Determines how equivalence between configuration files is determined (used by e.g.
       :meth:`~.Translator.load_persistent_instance`).

The ``metaconf.toml``-file is read as-is, without any preprocessing.

Custom TOML initialization
--------------------------
All TOML configuration is interpreted by the :class:`.TranslatorFactory` class. To customize how different components
are created, overwrite the all-caps factory properties of this class. For example, you may overwrite the
:attr:`.TranslatorFactory.FETCHER_FACTORY` attribute with your own implementation to customize how fetcher instances are
created. Likewise, set :attr:`.TranslatorFactory.MAPPER_FACTORY` to use custom :class:`.Mapper` implementations.

If your use case is not covered, consider opening an issue in the repository: https://github.com/rsundqvist/id-translation/issues
