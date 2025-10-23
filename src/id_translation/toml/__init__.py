"""Backend for the :meth:`.Translator.from_config` method."""

from . import factories, meta
from ._factory import TranslatorFactory
from ._load_toml import load_toml_file

__all__ = [
    "TranslatorFactory",
    "factories",
    "load_toml_file",
    "meta",
]
