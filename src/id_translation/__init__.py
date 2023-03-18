"""Translation of IDs with flexible formatting and name matching.

For an introduction to translation, see :ref:`translation-primer` and :ref:`mapping-primer`.
"""

import logging

from ._base_metadata import BaseMetadata
from ._config_utils import ConfigMetadata
from ._load_toml import load_toml_file
from ._translator import Translator
from .factory import TranslatorFactory

from .__version__ import __author__  # isort:skip
from .__version__ import __copyright__  # isort:skip
from .__version__ import __title__, __description__, __version__  # isort:skip

__all__ = [
    "Translator",
    "TranslatorFactory",
    "BaseMetadata",
    "ConfigMetadata",
    "load_toml_file",
    "__version__",  # Make MyPy happy
]

logging.getLogger(__name__).addHandler(logging.NullHandler())
