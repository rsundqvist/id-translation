.. _thread-safety:

Thread safety
=============
Most functions and classes are thread safe. Notable exceptions are documented here.

Configuring an instance, such as registering transformers or assigning properties and attributes, is not thread safe.
Finish configuring it before sharing it.

.. list-table::
   :header-rows: 1

   * - Not thread safe
     - Comment
   * - :func:`.enable_verbose_debug_messages`
     - This function modifies global state.
   * - :meth:`.Fetcher.fetch_all`
     - When ``selective_fetch_all=True`` (default), an :class:`.AbstractFetcher` may use a temporary :class:`.Mapper`.
       A :class:`.MultiFetcher` calls ``fetch_all`` on its children, and :meth:`.Translator.fetch` and
       :meth:`.Translator.go_offline` may call it.
   * - :meth:`.Fetcher.initialize_sources`
     - Invoked implicitly before all translation tasks. Results are cached when using a :class:`.MultiFetcher` or
       :class:`.AbstractFetcher` subtype, after which ``initialize_sources`` is thread-safe for these types.
   * - :meth:`.Translator.translated_names`
     - Reflects the most recent :meth:`.Translator.translate` call on the instance. The ``translate`` call itself is
       thread safe (when ``copy=True``), but the recorded names are not. Use :meth:`.Translator.map` in multi-threaded
       contexts.
   * - :meth:`.TranslationHelper.name_to_source`
     - Read from :meth:`.Translator.translated_names` after each :meth:`~.TranslationHelper.apply` call, so the same
       applies when the ``Translator`` is shared.
   * - :meth:`.Translator.initialize_sources`
     - Delegates to ``Fetcher.initialize_sources`` above, so the same "first call is not thread safe" caveat
       applies. The first call also registers fetcher-provided transformers (see :meth:`.Fetcher.get_transformer`),
       mutating the ``Translator`` itself. Methods that need the sources, such as :meth:`~.Translator.translate` and
       :meth:`~.Translator.map`, trigger this implicitly on their first call and inherit the same caveat.
   * - :meth:`.Translator.go_offline`
     - Performs :class:`.Fetcher` teardown. Once offline, the ``Translator`` is safe to share.

Transformers
------------
The :attr:`.Translator.transformers` are reused for all translation tasks. Bundled :class:`.Transformer` types are
thread safe. Transformers are inherited by any :class:`.TranslationMap` instances created by the ``Translator``,
including the :attr:`.Translator.cache` created by :meth:`.Translator.go_offline`. Note that
:meth:`.Translator.register_transformer` mutates shared state (including the cache), so the safe-to-share guarantee
above assumes no registrations are made after going offline. See the :ref:`registration window
<transformation-primer-window>` for details.

Fetchers
--------
Some thread-unsafe :class:`.Fetcher` operations emit a :class:`.ConcurrentOperationWarning` on a best-effort basis when
entered from multiple threads at once. This detection is cheap and lock-free, so it may miss races; absence of a warning
does not prove correctness.
