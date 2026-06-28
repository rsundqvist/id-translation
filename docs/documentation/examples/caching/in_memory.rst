.. _in_memory_caching_example:

===========================================
An in-memory ``CacheAccess`` implementation
===========================================
A :class:`.CacheAccess` that accumulates translations in process memory, keyed by ID, with a per-ID TTL. Click
:download:`here <in_memory.py>` to download the full script.

This is the **no-pickle, stays-online** alternative to :meth:`.Translator.load_persistent_instance`. Compared to that
method, it:

* has no ``pickle`` dependency -- ``load_persistent_instance`` serializes the whole :class:`.Translator` to disk using
  :mod:`pickle`, and
* keeps the ``Translator`` :attr:`~.Translator.online`, fetching unseen IDs on demand.

Unlike the :ref:`on-disk example <caching_example>`, which caches whole :attr:`~.Fetcher.fetch_all` tables, this caches
the *hot subset* of IDs as they are translated -- the access pattern of a typical online service. The trade-off is that
the cache lives only as long as the process.

.. seealso::

   :ref:`choosing-a-cache` for how this compares to :meth:`.Translator.go_offline` and
   :meth:`.Translator.load_persistent_instance`.

The all-or-nothing contract
---------------------------
The :class:`.AbstractFetcher` treats :meth:`.CacheAccess.load` as all-or-nothing: whatever it returns is taken as the
complete result, and there is no "fetch the missing IDs" step. A by-ID cache must therefore return an entry **only when
every requested ID is present** (and unexpired); otherwise it returns ``None`` and the fetcher re-fetches -- and
re-caches -- the whole request.

.. note::

   This example assumes a source is always fetched with the same placeholders. It stores one row per ID for the most
   recent placeholder layout and resets a source's cache if those placeholders change. A cache that mixes placeholder
   sets per source would instead key rows by layout and verify coverage in :meth:`~.CacheAccess.load`.

Design goals
------------
1. Cache individual IDs as they are translated (no :attr:`~.Fetcher.fetch_all` required).
2. Hold data in process memory.
3. Expire entries after a per-ID TTL, and cap the number of cached IDs per source.

Implementation
--------------
State is a per-source record of the placeholder layout plus an ``id -> (timestamp, row)`` mapping.

.. literalinclude:: in_memory.py
   :caption: The ``__init__`` method.
   :pyobject: InMemoryCacheAccess.__init__
   :dedent:

:meth:`~.CacheAccess.store` indexes each returned row by its ID. If the source's placeholder layout changed, the cache
is reset first (see the note above); oldest entries are dropped once the per-source cap is exceeded.

.. literalinclude:: in_memory.py
   :caption: The ``InMemoryCacheAccess.store()`` method.
   :pyobject: InMemoryCacheAccess.store
   :dedent:

:meth:`~.CacheAccess.load` returns a hit only when every requested ID is cached and unexpired -- otherwise ``None``.
``fetch_all`` requests always miss, since an accumulated cache cannot prove that it holds every ID.

.. literalinclude:: in_memory.py
   :caption: The ``InMemoryCacheAccess.load()`` method.
   :pyobject: InMemoryCacheAccess.load
   :dedent:

Creating a cached fetcher
-------------------------
All :class:`.AbstractFetcher` implementations accept an optional `cache_access` keyword argument.

.. literalinclude:: in_memory.py
   :caption: Creating a :class:`.Translator` with a cached fetcher.
   :pyobject: create

.. hint::

   To configure caching using TOML, add a ``[fetching.cache]``-section. The ``type`` key is required; other keys are
   forwarded to the implementation.

.. code-block:: toml
   :caption: Equivalent caching section of a TOML fetcher config.

   [fetching.cache]
   type = "__main__.InMemoryCacheAccess"
   ttl = 3600

See the :ref:`translator-config` page for more information.
