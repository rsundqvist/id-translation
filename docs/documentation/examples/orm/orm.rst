.. _orm_example:

=================================
An ``ORM`` fetcher implementation
=================================
A :class:`.Fetcher` solution that uses SQLAlchemy :doc:`ORM <sqlalchemy:tutorial/orm_related_objects>` models.

Using ORM models enables rich formatting such as ``'{id}:{name} (parent={parent.name})'``. A regular
:class:`.SqlFetcher` will only have access to the raw ``parent_id`` column.

.. warning::

   Note that ``f"{obj[key]}"`` and ``"{obj[key]}".format(obj=obj)`` are *not* equivalent.

   While f-strings support arbitrary expressions in braces, the :py:meth:`str.format`-method uses a
   `mini-language <https://docs.python.org/3/library/string.html#format-string-syntax>`_
   with more limited indexing capabilities.

Implementation
--------------
Click :download:`here <orm_fetcher.py>` to see the full implementation of the ``MyOrmFetcher`` class.

Lazy-loaded relations
~~~~~~~~~~~~~~~~~~~~~
SQLAlchemy ORM relations are lazy-loaded by default. The :attr:`~.FetchInstruction.placeholder_attributes` property is a
``dict`` on the form ``{placeholder: {attribute, ...}}``, containing information about attribute access and indexing
operations that are required by the format.

The ``MyOrmFetcher`` is a *naive* implementation built to handle this. The placeholder object (e.g. an ``Actor``
instance) must be traversed to trigger loading of lazy relations before
the ephemeral parent :class:`~sqlalchemy.orm.Session` of the ``orm_object`` is closed.

.. literalinclude:: orm_fetcher.py
   :caption: Placeholder extraction.
   :pyobject: MyOrmFetcher._to_record
   :dedent:

The `'films'` placeholder will have ``path='[0].title'``. The traversal logic is shown below.

.. literalinclude:: orm_fetcher.py
   :caption: Traversal logic for a single placeholder object.
   :pyobject: MyOrmFetcher._traverse
   :dedent:

Configuration
-------------
Creating a :class:`~id_translation.Translator` for the :ref:`dvdrental`.

.. literalinclude:: main.py
   :caption: Using ORM models as sources.
   :start-at: orm_fetcher =
   :end-at: print

The ``MyOrmFetcher.from_base_model()`` utility method was used to derive suitable model classes.

.. code-block::

   MyOrmFetcher(sources=['Actor', 'Inventory', 'Film', 'Customer', 'Staff', 'Rental'])

Click :download:`here <dvdrental_models.py>` for ORM models.

Translating
-----------
Let's use a few overly-complicated :class:`~id_translation.offline.Format` specs to show the capabilities of the
``MyOrmFetcher`` class.

.. literalinclude:: main.py
   :caption: Translating ``Rental`` and ``Actor`` IDs.
   :start-at: print

Output.

.. code-block::

   Rental=[20, 19]:
   * Jon rented SCISSORHANDS SLUMS (2006) to ROBERTA on 2005-05-25.
   * Mike rented HOLLOW JEOPARDY (2006) to RONNIE on 2005-05-25.

   Actor=[5, 11]:
   * 5: JOHNNY LOLLOBRIGIDA (first film='AMADEUS HOLY')
   * 11: ZERO CAGE (first film='CANYON STOCK')

This concludes the example. Click :download:`here <orm.zip>` to download the complete example.
