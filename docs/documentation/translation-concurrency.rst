.. _thread-safety:

Thread safety
=============
Most functions and classes are thread safe. Notable exceptions are documented here.

A per-instance lock ensures that source discovery and :ref:`transformer settling <transformation-primer-settling>` for a
:class:`.Translator` succeed only once, even when threads race on first use. :class:`.AbstractFetcher` and
:class:`.MultiFetcher` have locks of their own; see :ref:`thread-safety-fetchers`.

Configuring an instance, such as registering transformers or assigning properties and attributes, is not thread safe.
Finish configuring it before sharing it.

.. list-table::
   :header-rows: 1

   * - Not thread safe
     - Comment
   * - :func:`.enable_verbose_debug_messages`
     - Modifies global state.
   * - :meth:`.Fetcher.initialize_sources`
     - Called implicitly, possibly more than once and from several threads. Thread safe in :class:`.AbstractFetcher`
       and :class:`.MultiFetcher`; see :ref:`thread-safety-fetchers`.
   * - :meth:`.Translator.translated_names`
     - Reflects the last :meth:`~.Translator.translate` call on the instance that translated at least one name. The call
       itself is thread safe when ``copy=True``, but the recorded names are not. Use :meth:`.Translator.map` in
       multi-threaded contexts.
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

IO registry
-----------
The :mod:`~id_translation.dio` registry is process-wide. :func:`.register_io` and :func:`.unregister_io` are thread
safe, but assigning :attr:`.DataStructureIO.priority` is not: it can make translating raise in every thread until
``register()`` or ``unregister()`` is called (see the :ref:`priority rules <io-priority>`). Assign priorities before
other threads translate.

.. _thread-safety-fetchers:

Fetchers
--------
:meth:`.Fetcher.initialize_sources` is thread safe in :class:`.AbstractFetcher` and :class:`.MultiFetcher`. Once
discovery has succeeded, every call returns immediately. Until then, a per-fetcher lock lets only one discovery run at a
time. This holds whether the calls come from one ``Translator``, from code using :attr:`.Translator.fetcher` directly,
or from several instances that share the fetcher. A ``MultiFetcher`` makes this guarantee for its own discovery; each
child keeps its own guarantees. The lock covers discovery only.

.. warning::

   Discovery holds the fetcher's lock. Code that discovery calls, such as ``_initialize_sources()``, :class:`.Mapper`
   functions and log handlers, deadlocks if it waits for another thread that needs the same lock.

**Sharing a fetcher is a compromise**: the instances share its state, so :meth:`.Translator.go_offline` on one closes
it for all. :meth:`.Translator.copy` makes this compromise for fetchers that cannot or should not be copied, such as one
whose ``CacheAccess`` other threads are using. ``fetcher='keep'`` shares the fetcher, as do the default
``fetcher='auto'`` when copying fails and :func:`copy.copy`. Passing the same fetcher to more than one ``Translator``
shares it too.

.. _thread-safety-copying:

Copying and pickling
--------------------
Only :meth:`.Translator.copy` takes the instance's lock, and only until the instance is settled. Call
:meth:`.Translator.initialize_sources` before deep-copying or pickling an instance that other threads may be using.

``copy()``, :func:`copy.deepcopy` and :mod:`pickle` each deep-copy the transformers and the fetcher, including its
:class:`.CacheAccess`, while other threads may be using them. To copy an instance that serves other threads, use
``copy(fetcher='keep')``; the transformers are still deep-copied.
