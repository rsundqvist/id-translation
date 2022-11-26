"""Offline (in-memory) translation classes."""
from ._format import Format
from ._format_applier import DefaultFormatApplier, FormatApplier
from ._magic_dict import MagicDict
from ._translation_map import TranslationMap

__all__ = [
    "Format",
    "FormatApplier",
    "DefaultFormatApplier",
    "TranslationMap",
    "MagicDict",
]
