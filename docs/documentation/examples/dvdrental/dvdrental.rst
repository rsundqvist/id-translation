.. _dvdrental:

==========================
Sakila DVD Rental Database
==========================
This example translates a query against the `DVD Rental Sample Database`_. Click :download:`here <dvdrental.zip>`
to download.

Start the database
------------------
Using Docker, start the database by running:

.. code-block::

   docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres

For details about this image, see https://hub.docker.com/r/rsundqvist/sakila-preload.

.. literalinclude:: dvdrental.py
   :start-at: # Credentials
   :lines: 1-3

Query
-----
.. literalinclude:: query.sql
   :language: sql
   :linenos:

The query above will tell us who rented what and when, what store they rented from and from whom.

.. literalinclude:: dvdrental.py
   :start-at: # Download data to translate
   :end-at: print

.. csv-table:: Randomly sampled rows from the query. The first column is the record index in the query.
   :file: expected.csv
   :header-rows: 1

Configuration files
-------------------
The database has a few quirks, which are managed by configuration. See the :ref:`translator-config` page to learn
more about config files.

.. literalinclude::  translation.toml
   :caption: Translation configuration, mapping, and definition of the categories.

.. literalinclude:: sql-fetcher.toml
   :caption: Configuration for fetching SQL data.

To create a ``Translator``, pass the configuration files to :meth:`.Translator.from_config`.

.. literalinclude:: dvdrental.py
   :start-at: # Create a Translator
   :end-at: print

.. code-block::
   :caption: String representation of the ``Translator``.

   Translator(online=True: fetcher=MultiFetcher(max_workers=2, fetchers=[
     MemoryFetcher(sources=['category'])
     SqlFetcher(
       Engine(postgresql+pg8000://postgres:***@localhost:5002/sakila),
       blacklist={'category', 'store', 'inventory', 'rental', 'payment'}
     )
   ]))

Translating
-----------
Date columns should not be translated, so let's make sure.

.. literalinclude:: dvdrental.py
   :start-at: translator.map
   :lines: 1

.. code-block::
   :caption: Output of :meth:`.Translator.map`.

   {
       'customer_id': 'customer',
       'film_id': 'film',
       'category_id': 'category',
       'staff_id': 'staff',
   }

Result
------
All that's left now is to translate the data.

.. literalinclude:: dvdrental.py
   :start-at: translator.translate
   :end-at: print

.. csv-table:: Translated data.
   :file: translated.csv
   :header-rows: 1

.. _DVD Rental Sample Database:
    https://neon.com/postgresql/postgresql-getting-started/postgresql-sample-database/
