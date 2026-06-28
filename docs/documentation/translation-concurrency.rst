.. _thread-safety:

Thread safety
=============
Most functions and classes are thread safe. Notable exceptions are documented here.

.. list-table::
   :header-rows: 1

   * - Not thread safe
     - Comment
   * - :func:`.enable_verbose_debug_messages`
     - This function modifies global state.
   * - :meth:`.AbstractFetcher.fetch_all`
     - When ``selective_fetch_all=True`` (default), a temporary :class:`.Mapper` instance may be used. All built-in
       fetchers (e.g. the :class:`.SqlFetcher`) inherit from this class.
   * - :meth:`.Fetcher.initialize_sources`
     - Invoked implicitly before all translation tasks. Results are cached when using a :class:`.MultiFetcher` or
       :class:`.AbstractFetcher` subtype, after which ``initialize_sources`` is thread-safe for these types.
   * - :meth:`.Translator.translated_names`
     - Reflects the most recent :meth:`.Translator.translate` call on the instance. The ``translate`` call itself is
       thread safe (when ``copy=True``), but the recorded names are not. Use :meth:`.Translator.map` in multi-threaded
       contexts.
   * - :meth:`.Translator.go_offline`
     - Performs :class:`.Fetcher` teardown. Once offline, the ``Translator`` is safe to share.

Transformers
------------
The :attr:`.Translator.transformers` are reused for all translation tasks. Bundled :class:`.Transformer` types are
thread safe. Transformers are inherited by any :class:`.TranslationMap` instances created by the ``Translator``, including
the :attr:`.Translator.cache` created by :meth:`.Translator.go_offline`.

Fetchers
--------
Some thread-unsafe :class:`.Fetcher` operations emit a :class:`.ConcurrentOperationWarning` on a best-effort basis when
entered from multiple threads at once. This detection is cheap and lock-free, so it may miss races; absence of a warning
does not prove correctness.
