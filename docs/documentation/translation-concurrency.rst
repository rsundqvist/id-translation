.. _thread-safety:

Thread safety
=============
Most functions and classes are thread safe. Notable exceptions are documented here.

A :class:`.Translator` may be shared as soon as it is configured. Its first use runs source discovery and settles the
:ref:`transformers <transformation-primer-settling>` under a per-instance lock: however many threads race to use it, a
successful first use runs once. The exception is a fetcher shared between instances; see :ref:`thread-safety-fetchers`.

Configuring an instance, such as registering transformers or assigning properties and attributes, is not thread safe.
Finish configuring it before sharing it.

.. list-table::
   :header-rows: 1

   * - Not thread safe
     - Comment
   * - :func:`.enable_verbose_debug_messages`
     - This function modifies global state.
   * - :meth:`.Fetcher.initialize_sources`
     - Called implicitly, possibly more than once. :class:`.AbstractFetcher` and :class:`.MultiFetcher` cache a
       successful result, making later calls thread-safe no-ops; a direct ``Fetcher`` subclass should do the same.
       See :ref:`thread-safety-fetchers`.
   * - :meth:`.Translator.translated_names`
     - Reflects the last :meth:`~.Translator.translate` call on the instance that translated at least one name. The call
       itself is thread safe (when ``copy=True``), but the recorded names are not. Use :meth:`.Translator.map` in
       multi-threaded contexts.
   * - :meth:`.TranslationHelper.name_to_source`
     - Read from :meth:`.Translator.translated_names` after each :meth:`~.TranslationHelper.apply` call, so the same
       applies when the ``Translator`` is shared.
   * - :meth:`.Translator.initialize_sources`
     - Thread safe for a ``Translator`` with its own fetcher. Not when the fetcher is shared with another instance;
       see :ref:`thread-safety-fetchers`.
   * - :meth:`.Translator.go_offline`
     - Closes the :class:`.Fetcher`, which other instances may share. Once offline, the ``Translator`` is safe to share.
   * - :meth:`.Translator.copy`, :func:`copy.deepcopy` and :mod:`pickle`
     - See :ref:`thread-safety-copying`.

Transformers
------------
The :attr:`.Translator.transformers` are reused for all translation tasks. Bundled :class:`.Transformer` types are
thread safe. Every :class:`.TranslationMap` the ``Translator`` creates inherits them, including the
:attr:`.Translator.cache` from :meth:`.Translator.go_offline`. Once :ref:`settled <transformation-primer-settling>`,
they cannot be changed underneath a shared instance.

.. _thread-safety-fetchers:

Fetchers
--------
The first :meth:`.Fetcher.initialize_sources` call is not thread safe. A ``Translator`` makes it under its own lock, so
this is safe as long as the fetcher serves only that instance, as intended. Sharing a fetcher is a compromise that
:meth:`.Translator.copy` offers for fetchers that cannot or should not be copied: ``fetcher='keep'`` shares it, and so
does the default ``fetcher='auto'`` when copying fails. :func:`copy.copy` shares it too. Passing the same fetcher to
more than one ``Translator`` also shares it. Instances that share a fetcher have separate locks, and may make the first
call concurrently.

Call :meth:`.Translator.initialize_sources` before copying, or on one instance before the others use the fetcher; a
copy of an initialized ``Translator`` never repeats discovery.

An :class:`.AbstractFetcher` emits a :class:`.ConcurrentOperationWarning` when it sees two threads make that first call.
This detection is cheap and lock-free, so it may miss races; absence of a warning does not prove correctness.

.. _thread-safety-copying:

Copying and pickling
--------------------
Only :meth:`.Translator.copy` takes the instance's lock, and only until the instance is settled. Call
:meth:`.Translator.initialize_sources` before deep-copying or pickling an instance that other threads may be using.

``copy()``, :func:`copy.deepcopy` and :mod:`pickle` each deep-copy the transformers and the fetcher, including its
:class:`.CacheAccess`, while other threads may be using them. To copy an instance that serves other threads, use
``copy(fetcher='keep')``; the transformers are still deep-copied.
