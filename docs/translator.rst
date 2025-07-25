﻿=========================
id_translation.Translator
=========================
.. currentmodule:: id_translation

For an introduction to translation, see the :ref:`translation-primer` page.

The recommended way of initializing ``Translator`` instances is the :meth:`~Translator.from_config` method, unless your
setup is very simple. For configuration file details, please refer to the :ref:`translator-config` page.

Constructor
~~~~~~~~~~~
.. autosummary::
   :toctree:
   :template: autosummary/no-member-class.rst

   Translator

.. autosummary::
   :toctree:

   Translator.from_config

.. rubric:: Related attributes

.. autosummary::
   :toctree:

   Translator.config_metadata

Daily drivers
~~~~~~~~~~~~~
You'll be using these a lot.

.. autosummary::
   :toctree:

   Translator.map
   Translator.translate
   Translator.fetch

.. rubric:: Related methods

.. autosummary::
   :toctree:

   Translator.initialize_sources
   Translator.map_scores
   Translator.translated_names

.. rubric:: Related attributes

.. autosummary::
   :toctree:

   Translator.mapper
   Translator.online
   Translator.fetcher
   Translator.sources
   Translator.placeholders

Working offline
~~~~~~~~~~~~~~~
.. autosummary::
   :toctree:

   Translator.go_offline
   Translator.restore
   Translator.load_persistent_instance

.. rubric:: Related attributes
.. autosummary::
   :toctree:

   Translator.cache

Configuration
~~~~~~~~~~~~~
Most ``Translator`` attributes are read-only. To change the attributes below, use the ``copy`` method with attribute
overrides.

.. rubric:: Methods

.. autosummary::
   :toctree:

   Translator.copy

.. rubric:: Attributes
.. autosummary::
   :toctree:

   Translator.fmt
   Translator.default_fmt
   Translator.enable_uuid_heuristics
   Translator.transformers
