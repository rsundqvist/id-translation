"""Translation of IDs with flexible formatting and name matching.

For an introduction to translation, see :ref:`translation-primer` and :ref:`mapping-primer`.


Environment variables
---------------------
.. envvar:: ID_TRANSLATION_DISABLED

    Global switch. When ``true``, the :meth:`Translator.translate`-method returns immediately.
"""

import logging as _logging

from ._translator import Translator

__all__ = [
    "Translator",
    "__version__",  # Make MyPy happy
]

__version__ = "0.10.1"

_logging.getLogger(__name__).addHandler(_logging.NullHandler())
