"""Translation of IDs with flexible formatting and name matching.

For an introduction to translation, see :ref:`translation-primer` and :ref:`mapping-primer`.


Environment variables
---------------------
.. envvar:: ID_TRANSLATION_DISABLED

   Global switch. When ``true``, the :meth:`Translator.translate`-method returns immediately.

.. envvar:: ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS

   Global switch. Set to ``true`` (not recommended) to allow the :meth:`~id_translation.toml.TranslatorFactory` to
   discard `optional` fetchers that raise when imported or initialized.
   See the `documentation <../documentation/translator-config.html#optional-fetchers>`__ for details.
"""

import logging as _logging

from ._translator import Translator

__all__ = [
    "Translator",
    "__version__",  # Make MyPy happy
]

__version__ = "0.14.1"

_logging.getLogger(__name__).addHandler(_logging.NullHandler())
del _logging
