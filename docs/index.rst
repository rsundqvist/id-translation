ID Translation
==============
Turn meaningless IDs into human-readable labels.

Getting started
---------------
In real applications, :class:`.Translator` instances are typically created using :meth:`.Translator.from_config`. The
fastest way to get started with ``id-translation`` is the
🍪 `Cookiecutter template <README.html#cookiecutter-template-project>`__,
which wraps this method.

.. toctree::
   :hidden:

   API reference <_autosummary/id_translation>
   documentation/index
   development
   License <LICENSE>
   changelog/index

Basic usage
-----------
Using the :meth:`.Translator.translate` method.

.. code-block::

   tr = Translator(...)
   df = pd.DataFrame([[0, 2], [1991, 1999]], columns=["animals", "people"])
   tr.translate(df, fmt="{id}:{name}[, nice={is_nice}]", copy=False)

The `fmt` argument is optional, but ``copy=False`` is not since the default is ``True``. Let's look at the result:

.. code-block::

   print(df)
                   animals        people
   0  0:Tarzan, nice=False  1991:Richard
   1    2:Simba, nice=True    1999:Sofia

This is a simplified version of an :ref:`example <translator-docstring-example>` from the :class:`.Translator` class
documentation. See the :doc:`API reference <_autosummary/id_translation>` for more.

Shortcuts
---------
Click an image below to get started, or use the top navigation bar.
