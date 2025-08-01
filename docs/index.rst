ID Translation
==============
Turn meaningless IDs into human-readable labels.

Getting started
---------------
The fastest way to get started with ``id-translation`` is the 🍪 `id-translation-project`_
Cookiecutter template. It is designed to allow power users to quickly specify shared configurations that "just work" for
other users; see the example below.

.. code-block::

   # Generated by: cookiecutter https://github.com/rsundqvist/id-translation-project.git
   from big_corporation_inc.id_translation import translate
   print(
     "The first employee at Big Corporation Inc. was:",
     translate(1, names="employee_id"),
   )

The template generates an installable ``{your-namespace}.id_translation`` module, with functions such as the one used
above.
Check out the `demo project`_ (and its 📚 `generated documentation`_) to get a preview of what Your generated project
might look like.

.. hint::

   See the :doc:`/documentation/translation-primer` for a high-level overview of the :class:`.Translator` plumbing.


.. _id-translation-project: https://github.com/rsundqvist/id-translation-project/
.. _demo project: https://github.com/rsundqvist/id-translation-project/tree/master/demo/bci-id-translation
.. _generated documentation: https://rsundqvist.github.io/id-translation-project/

.. toctree::
   :hidden:

   API reference <api/id_translation>
   documentation/index
   development
   License <LICENSE>
   changelog/index

Basic usage
-----------
Using the :meth:`.Translator.translate` method.

.. code-block::

   tr = Translator(...)
   df = pd.DataFrame([[1, 1904]], columns=["animals", "people"])
   tr.translate(df, fmt="{id}:{name}[, nice={is_nice}]", copy=False)

The `fmt` argument is optional, but ``copy=False`` is not since the default is ``True``. Let's look at the result:

.. code-block::

   print(df)
                  animals     people
   0  1:Morris, nice=True  1904:Fred

This is a simplified version of an :ref:`example <translator-docstring-example>` from the :class:`.Translator` class
documentation. See the :doc:`API reference <api/id_translation>` for more.

Shortcuts
---------
Click an image below to get started, or use the top navigation bar.
