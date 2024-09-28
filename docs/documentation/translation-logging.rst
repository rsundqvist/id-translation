.. _translation-logging:

Logging
=======
The translation and mapping processes can output vast amounts of information that can be difficult to sift through
manually, especially with loggers working on the ``DEBUG``-level with extra verbose flags enabled. The exact flow of
these processes are discussed in the :ref:`translation-primer` and :ref:`mapping-primer` pages. If you haven't looked at
them already, you may want to do so before continuing.

.. _key-events:

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

These were chosen since translation issue tend to fall clearly within one of these domains.

.. hint::

   All ``event_key``-records also have an ``event_stage`` value. The delimiting values are ``'ENTER'`` (the event just
   started) and ``'EXIT'`` (the event just finished), respectively. This allows selecting other log records that are
   part of the same process that initially emitted the event key.

Finding the first ``event_stage='ENTER'``-record without a corresponding ``'EXIT'``-record is usually a good place to
start when something goes wrong!

Sample record
-------------
A single :meth:`.Translator.translate`-call with **every single debug option enabled** typically produces a few hundred
records (about 300 in this case). The final ``TRANSLATOR.TRANSLATE.EXIT``-event is the only ``ℹ️INFO``-level message,
shown in its entirety as a JSON-record at the bottom.

.. literalinclude:: dvdrental-exit-message.txt
   :language: python
   :caption: Exit message of the :meth:`.Translator.translate`-method.

The event keys aren't included in any user-facing messages, but are useful since they may be used for indexing by log
ingestion frameworks. The event keys associated with the message above are shown in the next snippet. Metadata such as
the names the user wanted to translate is included as well. Here, that value is ``null``, indicating that the user
wanted automatic name selection based on the configuration. This field is populated by the names that were extracted by
the ``Translator`` in the ``EXIT``-record.

.. literalinclude:: dvdrental-records.json
   :caption: Event keys emitted when entering the :meth:`.Translator.translate`-method.
   :start-at: "event_key": "TRANSLATOR.TRANSLATE",
   :end-before: "ignore_names": null,

The exact data that is included varies naturally depending on the message. Any record with ``event_stage='EXIT'`` will
include a ``execution_time``-value in seconds. Messages related to mapping will contain
``(values, candidates, context)``, and so on.

.. literalinclude:: dvdrental-records.json
   :caption: A ``TRANSLATOR.TRANSLATE.EXIT``-record emitted on the ``INFO``-level.
   :lines: 8287-
   :lineno-start: 8287
   :emphasize-lines: 2,5,15,22,25,26,28,30-34,36

A few of the more interesting parts of the record have been highlighted. Click :download:`here <dvdrental-records.json>`
to download. The line numbers shown above are the actual line numbers of this file.

.. code-block:: python
   :caption: Dummy version of the code that produced the the records.

   from id_translation import Translator
   import logging
   from id_translation.mapping.support import enable_verbose_debug_messages

   logging.basicConfig(level=logging.DEBUG, handlers=[SomeJsonExporter()])

   translator = Translator.from_config(main_config, [fetcher_configs..])
   with enable_verbose_debug_messages():
       translator.translate(df)

The configs that were used are available `here <examples/dvdrental.html#configuration-files>`_.

.. _dvdrental: https://github.com/rsundqvist/id-translation/blob/master/tests/dvdrental/
