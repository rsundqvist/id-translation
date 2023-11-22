"""Translation of IDs with flexible formatting and name matching.

For an introduction to translation, see :ref:`translation-primer` and :ref:`mapping-primer`.


Environment variables
---------------------
.. envvar:: ID_TRANSLATION_DISABLED

    Global switch. When ``true``, the :meth:`Translator.translate`-method returns immediately.
"""

import logging

from ._translator import Translator

from .__version__ import __author__  # isort:skip
from .__version__ import __copyright__  # isort:skip
from .__version__ import __title__, __description__, __version__  # isort:skip

__all__ = [
    "Translator",
    "__version__",  # Make MyPy happy
]

logging.getLogger(__name__).addHandler(logging.NullHandler())
