.. _mapping-primer:

Mapping primer
==============
The main entry point for mapping tasks is the :class:`id_translation.mapping.Mapper` class.

.. seealso::
   Mapping is used extensively by the (external) :ref:`id-translation <translation-primer>` package suite.

There are two principal steps involved in the mapping procedure: The :ref:`Step 1/2: Scoring procedure` (see
:meth:`Mapper.compute_scores <id_translation.mapping.Mapper.compute_scores>`) and the subsequent :ref:`Step 2/2: Matching procedure`
(see :meth:`Mapper.to_directional_mapping <id_translation.mapping.Mapper.to_directional_mapping>`). The two are
automatically combined when using the :meth:`Mapper.apply <id_translation.mapping.Mapper.apply>`-function, though they
may be invoked separately by users.

.. hint::
   Setting ``score_function='disabled'`` when creating the ``Mapper`` will force override-only mode. This will require
   manually defined mappings to be defined for every values that should be mapped. Trying to map values without an
   override will raise a :class:`~id_translation.mapping.exceptions.ScoringDisabledError` in this mode.

Step 1/2: Scoring procedure
---------------------------
The ``Mapper`` first applies :ref:`Overrides and filtering`, after which the actual :ref:`Score computations` are
performed.

.. |caption| raw:: html

  <p style="text-align:right; font-style: italic;">Colours mapped by <br> spectral distance (RGB).</p>

.. figure:: ../_images/mapping.png
   :width: 220
   :align: right

   |caption|

Overrides and filtering
~~~~~~~~~~~~~~~~~~~~~~~
Overrides and filtering adhere to a strict hierarchy (the one presented below). Overrides take precedence over filters,
and runtime overrides takes precedence over static overrides.

1. Runtime overrides (type: :attr:`~id_translation.mapping.types.UserOverrideFunction`); set ``score=∞`` for the chosen
   candidate, and ``score=-∞`` for others.

2. Static overrides (type: ``dict`` or :attr:`~rics.collections.dicts.InheritedKeysDict`); set ``score=∞`` for the
   chosen candidate, and ``score=-∞`` for others.

3. Filtering (type: :attr:`~id_translation.mapping.types.FilterFunction`); set ``score=-∞`` for undesirable matches only.

Score computations
~~~~~~~~~~~~~~~~~~
4. Compute value-candidate match scores (type: :attr:`~id_translation.mapping.types.ScoreFunction`). Higher is better.

5. If there are any Heuristics (type: :class:`~id_translation.mapping._heuristic_score.HeuristicScore`), apply..

    a. Short-circuiting (type: :attr:`~id_translation.mapping.types.FilterFunction`); reinterpret a ``FilterFunction``
       such that the returned candidates (if any) are treated as overrides.

    b. Aliasing (type: :attr:`~id_translation.mapping.types.AliasFunction`); try to improve ``ScoreFunction`` accuracy
       by applying heuristics to the ``(value, candidates)``-argument pairs.

    c. Finally, select the best score at each stage (from no to all heuristics) for each pair.

The final output is a score matrix (type: :class:`pandas.DataFrame`), where columns are candidates and values make up
the index.

.. csv-table:: Partial mapping scores for the :ref:`dvdrental` ID translation example.
   :file: dvdrental-scores.csv
   :header-rows: 1
   :stub-columns: 1

The ``'rental_date'``-value can be seen having only negative-infinity matching scores due to filtering.

.. hint::

   The :meth:`Translator.map_scores <id_translation.Translator.map_scores>`-method returns Name-to-source mapping scores.

Step 2/2: Matching procedure
----------------------------
Given precomputed match scores (see the section above), make as many matches as possible given a ``Cardinality``
restriction. These may be summarized as:

* :attr:`~id_translation.mapping.Cardinality.OneToOne` = *'1:1'*: Each value and candidate may be used at most once.
* :attr:`~id_translation.mapping.Cardinality.OneToMany` = *'1:N'*: Values have exclusive ownership of matched candidate(s).
* :attr:`~id_translation.mapping.Cardinality.ManyToOne` = *'N:1'*: Ensure that as many values as possible are
  *unambiguously* mapped (i.e. to a single candidate). This is the **default option** for new ``Mapper`` instances.
* :attr:`~id_translation.mapping.Cardinality.ManyToMany` = *'M:N'*: All matches above the score limit are kept.

In theory, ``OneToMany`` and ``ManyToOne`` are equally restrictive. During mapping however, *the goal is usually to
find matches for values, not candidates*. With that in mind, the ordering above may be considered strictly decreasing
in preciseness.

Conflict resolution
~~~~~~~~~~~~~~~~~~~
When a single match out of multiple viable options must be chosen due to cardinality restrictions, priority is
determined by the iteration order of `values` and `candidates`. The first value will prefer the first candidate, and so
on. This logic does `not` consider future matches.

>>> mapper = Mapper(cardinality='1:1', score_function=lambda value, *_: [1, 0] if value == 'v1' else [1, 1])
>>> mapper.compute_scores(['v0', 'v1'], ['c0', 'c1'])
candidates   c0   c1
values
v0          1.0  1.0
v1          0.0  1.0
>>> mapper.apply(['v0', 'v1'], ['c0', 'c1']).flatten()
{'val0': 'cand0'}

Notice that `val1` was left without a match, even though it could've been assigned to `cand0` if the equally viable
matching `val0 → cand1` had been chosen first.

.. note::

   As of version 3.0.0, a score matrix like this will raise :class:`.AmbiguousScoreError` for any cardinality that
   requires a single candidate (including `1:1`).

Troubleshooting
---------------
Unmapped values are allowed by default. If mapping failure is not an acceptable outcome for your application, initialize
the ``Mapper`` with ``unmapped_values_action='raise'`` to ensure that an error is raised for unmapped values, along with
more detailed log messages which are emitted on the error level.

Mapper ``verbose``-messages
~~~~~~~~~~~~~~~~~~~~~~~~~~~
The ``id_translation.mapping.*.verbose`` loggers emit per-combination mapping scores when matches are made or when
values are left without a match. Records from these loggers are always emitted on the ``DEBUG``-level.

.. note::

   All ``verbose`` messages are suppressed unless :attr:`.Mapper.verbose_logging` is ``True``.

The messages below are from a test case in a strange world where only one kind of animal is allowed to have a specific
number of legs.

.. code-block:: python
    :caption: A listing of matches that were rejected in favour of the current match.

    id_translation.mapping.Mapper.verbose: Accepted: 'dog' -> '4'; score=inf (short-circuit or override).
    id_translation.mapping.Mapper.verbose: This match supersedes 7 other matches:
        'cat' -> '4'; score=1.000 (superseded on candidate=4).
        'three-legged cat' -> '4'; score=0.000 < 0.9 (below threshold).
        'human' -> '4'; score=0.000 < 0.9 (below threshold).

The severity of unmapped values depends on the application. As such, the level for these kinds of messages is determined
by the :attr:`.Mapper.unmapped_values_action`-attribute.

.. code-block:: python
   :caption: Explanation of why a match was not made.

    id_translation.mapping.Mapper.verbose: Could not map value='cat':
        'cat' -> '4'; score=1.000 (superseded on candidate=4: 'dog' -> '4'; score=inf).
        'cat' -> '0'; score=0.000 < 0.9 (below threshold).

Even if ``unmapped_values_action='ignore'``, records are still emitted on the ``DEBUG``-level under the ``verbose``
logger namespace.

Managing verbosity
~~~~~~~~~~~~~~~~~~
Verbose messages may be permanently enabled by initializing with ``verbose_logging=True``. To enable temporarily, use
the :meth:`~id_translation.mapping.support.enable_verbose_debug_messages` context.

.. code-block:: python

   from id_translation.mapping import Mapper, support
   with support.enable_verbose_debug_messages():
       Mapper().apply(<values>, <candidates>)

The ``Mapper`` uses this same function internally when the verbose flag is set.

.. code-block:: python
   :caption: Messages from the scoring procedure.

   id_translation.mapping.verbose.filter_functions.require_regex_match: Refuse matching for name='a': Matches pattern=re.compile('.*a.*', re.IGNORECASE).
   id_translation.mapping.verbose.HeuristicScore: Heuristics scores for value='staff_id': ['store': 0.00 -> 0.50 (+0.50), 'payment': 0.07 -> 0.07 (+0.00), 'inventory': 0.00 -> 0.07 (+0.07), 'language': 0.00 -> 0.08 (+0.08), 'category': 0.00 -> 0.04 (+0.04), 'film': 0.05 -> 0.10 (+0.05), 'address': 0.00 -> 0.08 (+0.08), 'rental': 0.00 -> 0.08 (+0.08), 'customer_list': 0.00 -> 0.02 (+0.02), 'staff': 0.00 -> 1.00 (+1.00), 'staff_list': 0.00 -> 0.03 (+0.03), 'city': 0.00 -> 0.10 (+0.10), 'country': 0.00 -> 0.06 (+0.06), 'customer': 0.00 -> 0.04 (+0.04), 'actor': 0.00 -> 0.17 (+0.17)]
   id_translation.mapping.verbose.filter_functions.require_regex_match: Refuse matching for name='return_date': Does not match pattern=re.compile('.*_id$', re.IGNORECASE).

The mapping procedure may emit a large amount of records in verbose mode.
