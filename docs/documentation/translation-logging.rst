.. _translation-logging:

Interpreting ``id-translation`` Logs
====================================
The translation and mapping processes can output vast amounts of information that can be difficult to sift through
manually, especially with loggers working on the ``DEBUG``-level with extra verbose flags enabled. The exact flow of
these processes are discussed in the :ref:`translation-primer` and :ref:`mapping-primer` pages. If you haven't looked at
them already, you may want to do so before continuing.

Key Event Records
-----------------
Key event records are emitted on the ``INFO`` and ``DEBUG`` level, see the table below. These messages are structured
for ingestion and will always contain the ``event_key``-key, as well as some other context-dependent data.

.. list-table:: Key Events
   :widths: 15, 25, 60
   :header-rows: 1

   * - Function / log level
     - Event key
     - Domain-specific keys
   * - | :meth:`.Translator.translate`
       | ``INFO`` if :attr:`.Translator.online` else ``DEBUG``.
     - ``TRANSLATOR.TRANSLATE``
     - translatable_type, names, sources
   * - | :meth:`.Translator.map`
       | ``DEBUG``-level event.
     - ``TRANSLATOR.MAP``
     - translatable_type, value, candidates
   * - | :meth:`.MultiFetcher.fetch`
       | ``DEBUG``-level event.
     - ``MULTIFETCHER.FETCH``
     - max_workers, num_fetchers, sources, placeholders
   * - | :meth:`.MultiFetcher.fetch_all`
       | ``DEBUG``-level event.
     - ``MULTIFETCHER.FETCH_ALL``
     - max_workers, num_fetchers, placeholders
   * - | :meth:`.AbstractFetcher.map_placeholders`
       | ``DEBUG``-level event.
     - ``<CLASSNAME>.MAP_PLACEHOLDERS``
     - value, candidates, context
   * - | :meth:`.AbstractFetcher.fetch_translations`
       | ``DEBUG``-level event.
     - ``<CLASSNAME>.FETCH_TRANSLATIONS``
     - fetch_all, source, placeholders, num_ids

These were chosen since they are key events in the translation flow.

.. important::

   All ``event_key``-records also have an ``event_stage`` value. The delimiting values are ``'ENTER'`` (the event just
   started) and ``'EXIT'`` (the event just finished), respectively. This allows selecting other log records that are
   part of the same process that initially emitted the event key.

Finding the first ``event_stage='ENTER'``-record without a corresponding ``'EXIT'``-record is usually a good place to
start when something goes wrong!

Sample record
-------------
Below is the final success message produced by a single :meth:`.Translator.translate`-call with every single debug
option enabled, about 400 records in total. Only 2 of these are non-``DEBUG`` messages; the one shown below and the
corresponding ``'ENTER'``-event. The snippet that produced these logs looks something like this:

.. code-block:: python

   from id_translation import Translator
   import logging
   from rics.mapping.support import enable_verbose_debug_messages

   translator = Translator.from_config(main_config, [extra_fetchers..])
   logging.basicConfig(level=logging.DEBUG, handlers=[SomeJsonExporter()])
   with enable_verbose_debug_messages():
       translator.translate(df)  # Translate a DataFrame

We can of course tell that this is the end from the messages itself:

.. code-block:: python

   Finished translation of 'DataFrame' in 0.26858 sec. Returning a translated
   copy since inplace=False.

But, there are also also keys present that may be used for indexing by log ingestion frameworks:

.. literalinclude:: dvdrental-records.json
   :lines: 7438-7441
   :lineno-start: 7438

The exact data that is included varies naturally depending on the message. Any record with ``event_stage='EXIT'`` will
include a ``execution_time``-value in seconds. Messages related to mapping will contain
``(values, candidates, context)``, and so on. A few of the more interesting parts of the ``TRANSLATOR.TRANSLATE.EXIT``
-event have been highlighted below.

.. literalinclude:: dvdrental-records.json
   :caption: A ``TRANSLATOR.TRANSLATE.EXIT``-record emitted on the ``INFO``-level.
   :lines: 7417-
   :lineno-start: 7417
   :emphasize-lines: 2,5,15,22-25,33-38,44-45

Click :download:`🗒️here <dvdrental-records.json>` to download the entire log file in JSON format. The line numbers shown
above are the actual line numbers of this file.
