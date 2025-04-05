.. _caching_example:

================================
A ``CacheAccess`` implementation
================================
A caching solution that stores data locally on disk. Click :download:`here <caching.py>` to download the full script.

Design goals
------------
We've arbitrarily decided on the following requirements:

1. Data should only be cached if the fetcher is performing a :attr:`~.Fetcher.fetch_all`-operation.
2. Cached data should be stored on disk using the `feather <https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_feather.html>`_ format.
3. Cached data should have a timeout (TTL), measured in seconds.

We'll create a new class, ``MyCacheAccess``, to meet these requirements.

Implementation
--------------
The new class needs to know where to store data and how long to keep it.

.. literalinclude:: caching.py
   :caption: The  ``__init__`` method.
   :pyobject: MyCacheAccess.__init__

We can now start implementing the abstract methods in :class:`.CacheAccess`. We'll start with
:meth:`.CacheAccess.store`:

.. literalinclude:: caching.py
   :caption: The  ``MyCacheAccess.store()`` method.
   :pyobject: MyCacheAccess.store

**Requirement 1**: If :attr:`.FetchInstruction.fetch_all` is ``False``, data should not be stored.

Otherwise, we use source as the file name and we convert the translations to a :class:`~.pandas.DataFrame` using
:meth:`.PlaceholderTranslations.to_dataframe`. **Requirement 2**: The frame is witten to disk using
:meth:`pandas.DataFrame.to_feather`.

We're now ready to implement :meth:`.CacheAccess.load`, which will read, verify, and convert the stored data.

.. literalinclude:: caching.py
   :caption: The  ``MyCacheAccess.load()`` method.
   :pyobject: MyCacheAccess.load

As per **Requirement 3**, we should only return data that is newer than `ttl` seconds. We'll use the
:py:data:`modification time <stat.ST_MTIME>` of the serialized data that is reported by the operating system.

.. literalinclude:: caching.py
   :caption: The ``MyCacheAccess.age_in_seconds()`` method.
   :pyobject: MyCacheAccess.age_in_seconds

If the data is stale, we return ``None``.

.. hint::

   Returning  ``None`` signals to the caller that data should be retrieved some other way; typically by using
   :meth:`.AbstractFetcher.fetch_translations` instead.

The data is read using :func:`pandas.read_feather`, then converted using :meth:`.PlaceholderTranslations.from_dataframe`.

Creating a cached fetcher
-------------------------
All :class:`.AbstractFetcher` implementations accept an optional `cache_access` keyword argument.

.. literalinclude:: caching.py
   :caption: Creating ``Translator`` with a cached fetcher.
   :pyobject: create

Using a :class:`.CacheAccess` with a :class:`.MemoryFetcher` doesn't make much sense, but the caching procedure works
just the same as it would for e.g. a :class:`.SqlFetcher`.

.. hint::

   To configure caching using TOML, add a ``[fetching.cache]``-section.

The ``type`` key is required. Other keys are determined by the implementation.

.. code-block:: toml
   :caption: Equivalent caching section of a TOML fetcher config.

   [fetching.cache]
   type = "__main__.MyCacheAccess"
   root = "./cache/"
   ttl = 3600

See the :ref:`translator-config` page for more information.

Caching in action
-----------------
We'll use the ``create()`` function defined above to initialize new :class:`.Translator` instances.

.. code-block:: python
   :caption: Step 1

   translator = create()
   print("person=", translator.translate(1904, "people"))


Initial creation. Data is retrieved from the source. There's only one ID in the fetcher, but the cache implementation
doesn't know that. It refuses to store the data as per **Requirement 1**.

.. code-block::
   :caption: Output

   Cache at path='cache/people.ftr' does not exist.
   Refuse caching of source='people' since FetchInstruction.fetch_all=False.
   person= 1904:Fred

Using :meth:`.Translator.go_offline` without any explicit IDs will call :class:`~id_translation.fetching.Fetcher.fetch_all`.

.. code-block:: python
   :caption: Step 2

   translator.go_offline()
   print("person=", translator.translate(1904, "people"))

When going offline, the ``Translator`` will store translation data in-memory as a :class:`.TranslationMap`.

.. code-block::
   :caption: Output

   Cache at path='cache/people.ftr' does not exist.
   Store cache at path='cache/people.ftr'.
   person= 1904:Fred

By definition, a translator that is offline does not have a fetcher attached. The effects of this can be seen above: The
cache was updated, but it wasn't loaded again for the :meth:`~.Translator.translate` call. There is no way to reconnect
an offline ``Translator``, so this instance will be limited to using it's :attr:`~.Translator.cache` until it is destroyed.

Of course, deleting the ``MyCacheAccess`` instance doesn't remove the files on disk.

.. code-block:: python
   :caption: Step 3

   print("person=", create().translate(1904, "people"))

If we create a new ``Translator`` and use it right away (or within `ttl = 3600 seconds = 1 hour`), the cached data will
be used.

.. code-block::
   :caption: output

   Load cache (age=0 <= 3600=ttl) at path='cache/people.ftr'.
   person= 1904:Fred

This concludes the example. Click :download:`here <caching.py>` to download the full script.
