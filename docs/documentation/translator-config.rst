.. _translator-config:

TOML Configuration Files
========================
The recommended way of creating and configuring translators is the :meth:`Translator.from_config()
<id_translation.Translator.from_config>` method. For an example, see the :ref:`dvdrental` page.

.. hint::
    For ``Fetcher`` classes and functions used by ``Mapper``, ``rics``-package implementations are used by default. To
    specify an external class or function, use ``'fully.qualified.names'`` in quotation marks. Names are resolved by
    :func:`~rics.utility.misc.get_by_full_name`, using an appropriate ``default_module`` argument.

For an introduction to the translation process itself, see the :ref:`translation-primer`.

Multiple fetchers
-----------------
Complex applications may require multiple fetchers. These may be specified in auxiliary config files, one fetcher per
file. Only the ``fetching`` key will be considered in these files. If multiple fetchers are defined, a
:class:`~id_translation.fetching.MultiFetcher` is created. Fetchers defined this way are **hierarchical**. The input
order determines rank, affecting Name-to-:attr:`source <id_translation.fetching.Fetcher.sources>` mapping. For
example, for a ``Translator`` created by running:

>>> from id_translation import Translator
>>> extra_fetchers=["fetcher.toml", "backup-fetcher.toml"]
>>> Translator.from_config("translation.toml", extra_fetchers=extra_fetchers)

the :func:`Translator.map <id_translation.Translator.map>`-function will first consider the sources of the fetcher
defined in **translation.toml** (if there is one), then `fetcher.toml` and finally `backup-fetcher.toml`.

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
     - Comments
   * - fmt
     - :class:`~id_translation.offline.Format`
     - Specify how translated IDs are displayed
     -

* Parameters for :attr:`Name <id_translation.ttypes.NameType>`-to-:attr:`source <id_translation.ttypes.SourceType>`
  mapping are specified in a ``[translator.mapping]``-subsection. See: :ref:`Subsection: Mapping` for details (context =
  :attr:`source <id_translation.ttypes.SourceType>`).

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
     - Specify an format for untranslated IDs.
     - Can be a plain string ``fmt='Unknown'``, or ``fmt='{id}'`` to leave as-is.

* Alternative :attr:`placeholder <id_translation.offline.Format.placeholders>`-values for unknown IDs can be declared
  in a ``[unknown_ids.overrides]``-subsection. See: :ref:`Subsection: Overrides` for details (context =
  :attr:`source <id_translation.ttypes.SourceType>`).

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

* The :class:`~id_translation.fetching.AbstractFetcher` class uses a :class:`~rics.mapping.Mapper` to bind actual
  :attr:`placeholder <id_translation.fetching.Fetcher.placeholders>` names in
  :attr:`~id_translation.fetching.Fetcher.sources` to desired
  :attr:`placeholder names <id_translation.offline.Format.placeholders>` requested by the calling Translator instance.
  See: :ref:`Subsection: Mapping` for details (context = :attr:`source <id_translation.ttypes.SourceType>`).
* Additional parameters vary based on the chosen implementation. See the :mod:`id_translation.fetching` module for
  choices.

.. hint::

   Custom classes may be initialized by using sections with fully qualified type names in single quotation marks. For
   example, a ``[fetching.'my.library.SuperFetcher']`` would import and initialize a ``SuperFetcher`` from the
   ``my.library`` module.

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
     - :attr:`~rics.mapping.types.ScoreFunction`
     - Compute value/candidate-likeness
     - See: :mod:`rics.mapping.score_functions`
   * - unmapped_values_action
     - `raise | warn | ignore`
     - Handle unmatched values.
     - See: :class:`rics.utility.action_level.ActionLevel`
   * - cardinality
     - `OneToOne | ManyToOne`
     - Determine how many candidates to map a single value to.
     - See: :class:`rics.mapping.Cardinality`

* Score functions which take additional keyword arguments should be specified in a child section, eg
  ``[*.mapping.<score-function-name>]``. See: :mod:`rics.mapping.score_functions` for options.
* External functions may be used by putting fully qualified names in single quotation marks. Names which do not contain
  any dot characters (``'.'``) are assumed to refer to functions in the appropriate ``rics.mapping`` submodule.

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
     - See: :mod:`rics.mapping.filter_functions`

.. note::

   Additional keys depend on the chosen function implementation.

As an example, the next snippet ensures that only names ending with an ``_id``-suffix will be translated by using a
:func:`~rics.mapping.filter_functions.require_regex_match` filter.

.. code-block:: toml

    [[translator.mapping.filter_functions]]
    function = "require_regex_match"
    regex = ".*_id$"
    where = "name"


Score function
~~~~~~~~~~~~~~
There are some :attr:`~rics.mapping.types.ScoreFunction` s which take additional keyword arguments. These must
be declared in a ``[*.overrides.<score-function-name>]``-subsection. See: :mod:`rics.mapping.score_functions` for options.

Score function heuristics
~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristics may be used to aid an underlying `score_function` to make more difficult matches. There are two types of
heuristic functions: :attr:`~rics.mapping.types.AliasFunction` s and Short-circuiting functions (which are
really just differently interpreted :attr:`~rics.mapping.types.FilterFunction` s).

Heuristics are given in ``[[*.mapping.score_function_heuristics]]`` **list**-subsections (note the double brackets) and
are applied in the order in which they are given by the :class:`~rics.mapping.HeuristicScore` wrapper
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
     - See: :mod:`rics.mapping.heuristic_functions`
   * - mutate
     - :py:class:`bool`
     - Keep changes made by `function`.
     - Disabled by default.

.. note::

   Additional keys depend on the chosen function implementation.

As an example, the next snippet lets us match table columns such as `animal_id` to the `id` placeholder by using a
:func:`~rics.mapping.heuristic_functions.value_fstring_alias` heuristic.

.. code-block:: toml

    [[fetching.mapping.score_function_heuristics]]
    function = "value_fstring_alias"
    fstring = "{context}_{value}"

.. hint::

   For difficult matches, consider using :ref:`overrides <Subsection: Overrides>` instead.

Subsection: Overrides
---------------------
Shared or context-specific key-value pairs implemented by the :class:`~rics.utility.collections.dicts.InheritedKeysDict`
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
   :attr:`mapping process <rics.mapping.Mapper.apply>` provides detailed information in debug mode, which may be used to
   discover issues.

.. hint::

   Overrides may also be used to `prevent` mapping certain values.

For example, let's assume that a SQL source table called `title_basics` with two columns `title` and `name` with
identical contents. We would like to use a format ``'[{title}. ]{name}'`` to output translations such as
`'Mr. Astaire'`. To avoid output such as `'Top Hat. Top Hat'` for movies, we may add

.. code-block:: toml

  [fetching.mapping.overrides.movies]
  title = "_"

to force the fetcher to inform the ``Translator`` that the `title` placeholder (column) does not exist for the
`title_basics` source (we used `'_'` since TOML `does not have <https://github.com/toml-lang/toml/issues/30>`__ a
``null``-type).
