.. _translation-logging:

Logging
=======
All messages are emitted by :mod:`id_translation` namespace loggers. The `id_translation` namespace uses the
``logging.WARNING`` log level (similar to
`SQLAlchemy <https://docs.sqlalchemy.org/en/14/core/engines.html#configuring-logging>`__).
To enable logs at the ``ℹ️ INFO`` level and below, you must explicitly configure the log level.

Verbose logging
---------------
Set the global :data:`~.logging.ENABLE_VERBOSE_LOGGING` flag (or use :func:`~.logging.enable_verbose_debug_messages`) to
enable additional ``🪲 DEBUG``-level messages. Use the :envvar:`ID_TRANSLATION_VERBOSE` variable in containers.

.. warning::

   Verbose logging may emit hundreds of messages for a single translation task!

.. hint::

   Click `here <../_static/logging/verbose-rainbow.html>`__ for verbose sample output using ``style="rainbow"``.

Note that `verbose` and ``🪲 DEBUG`` logging are different things; verbose logging can emit hundreds of messages in
cases where regular ``🪲 DEBUG`` logging would only emit a dozen. Verbose messages are typically related to the
:ref:`mapping <translation-primer>` process.

Example
-------
The ``ℹ️ INFO``-level messages emitted for a single :meth:`.Translator.translate` call.

.. literalinclude:: dvdrental-info-messages.log
   :language: log

Since these are :ref:`🔑 key event <Key Event Records>` messages, there are corresponding entry events (the messages
above are all ``'exit'``-records). The ``'enter'``-records are emitted on the ``🪲 DEBUG`` level.

.. _key-events:

Key Event Records
-----------------
Key event messages are emitted at the boundaries of the various stages in the translation process (see the
:ref:`translation-primer` and :ref:`mapping-primer` pages). Common fields are listed below.

.. list-table:: Key Event Record Structure
   :header-rows: 1

   * - Field
     - Type
     - Description
   * - `task_id`
     - ``int``
     - Unique task identifier, e.g. for a single :meth:`~.Translator.translate` call.
   * - `event_key`
     - ``str`` = ``class.method:stage``
     - E.g. `MultiFetcher.fetch_all:enter` (where ``stage='enter'``).
   * - `seconds`
     - ``float``
     - Task duration in seconds. Only when ``stage='exit'``.

All key event methods add additional fields that are relevant to the current task and stage. Fields may be added,
removed, or change values depending on the ``stage`` of the event.

Event-specific fields
~~~~~~~~~~~~~~~~~~~~~
Let's take closer look at the final message. The :class:`~logging.LogRecord` contains additional information that isn't
included in the message itself. The full ``Translator.translate:exit``-record is shown as JSON below.

.. literalinclude:: dvdrental-records.json
   :caption: Translation exit event. Click :download:`here <dvdrental-records.json>` to download.
   :lines: 10432-10484
   :lineno-start: 10432

About 350 messages were emitted since ``ENABLE_VERBOSE_LOGGING=True``. If we were using regular ``🪲 DEBUG``-logging,
about 40 messages would have been emitted instead. The vast majority of the verbose messages relate to mapping and
fetcher initialization.

.. code-block:: python
   :caption: Dummy version of the code that produced the the records.

   from logging import basicConfig, DEBUG
   from id_translation import Translator
   from id_translation.logging import enable_verbose_debug_messages

   basicConfig(handlers=[SomeJsonExporter()])

   translator = Translator.from_config(main_config, [fetcher_configs..])
   with enable_verbose_debug_messages():
       translator.translate(df)

The configs that were used are available `here <examples/dvdrental/dvdrental.html#configuration-files>`_.
