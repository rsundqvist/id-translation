Thread safety
=============
Most functions and classes are thread safe. Notable exceptions are documented here.

.. list-table::
   :header-rows: 1

   * - Not thread safe
     - Comment
   * - :func:`.enable_verbose_debug_messages`
     - This function modifies global state. Implicit when :attr:`.Mapper.verbose_logging` is set.
   * - :meth:`.AbstractFetcher.fetch_all`
     - When ``selective_fetch_all=True`` (default), a temporary :class:`.Mapper` instance may be used. All built-in
       fetchers (e.g. the :class:`.SqlFetcher`) inherit from this class.
   * - :meth:`.Fetcher.initialize_sources`
     - Invoked implicitly before all translation tasks. Results are cached when using a :class:`.MultiFetcher` or
       :class:`.AbstractFetcher` subtype, after which ``initialize_sources`` is thread-safe for these types.<
