.. _dvdrental:

===================
DVD Rental Database
===================
This example translates a query from the `DVD Rental Sample Database`_. It covers most of the more advanced features
that have been implemented.

Start the database
------------------
Using Docker, start the database by running:

.. code-block::

   docker run -p 5002:5432 --rm rsundqvist/sakila-preload:postgres

from the terminal. To describe the database, run

.. code-block::

   psql -h localhost -p 5001 -U postgres -d sakila -c "\d+"
   # password: Sofia123!

from a separate terminal window. Leave out the last part (``-c "\d+"``) to query the database manually. For details
about this image, see `rsundqvist/sakila-preload <https://hub.docker.com/r/rsundqvist/sakila-preload>`_ on Docker Hub.

Query to translate
------------------
We will use a small query to describe rental transactions in the database:

.. literalinclude:: ../../../tests/dvdrental/docker/tests/query.sql
   :language: sql
   :caption: Query returning DVD rental transactions.
   :linenos:

The query above shows who rented what and when, what store they rented from and from whom.

.. csv-table:: Randomly sampled rows from the query. The first column is the record index in the query.
   :file: ../../../tests/dvdrental/docker/tests/expected.csv
   :header-rows: 1

Configuration files
-------------------
The database has a few quirks, which are managed by configuration. See the :ref:`translator-config` page to learn
more about config files.

.. literalinclude:: ../../../tests/dvdrental/translation.toml
   :language: toml
   :caption: Translation configuration, mapping, and definition of the categories.
   :linenos:

.. literalinclude:: ../../../tests/dvdrental/sql-fetcher.toml
   :language: toml
   :caption: Configuration for fetching SQL data.
   :linenos:

Translating
-----------
Translating now becomes a simple matter. The following snippet is a test case which translates all of the ~16000 rows
returned by the query, verifying a random sample of 5 rows.

.. literalinclude:: ../../../tests/dvdrental/test_dvdrental.py
   :language: python
   :linenos:

Result
------
Date columns are not translated, nor is the first (row number/index) column.

.. csv-table:: Translated data.
   :file: ../../../tests/dvdrental/translated.csv
   :header-rows: 1

.. _DVD Rental Sample Database:
    https://www.postgresqltutorial.com/postgresql-getting-started/postgresql-sample-database/
