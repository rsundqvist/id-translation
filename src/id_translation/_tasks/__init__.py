from ._map import MappingTask
from ._names import NamesTask, handle_input_names
from ._translate import TranslationTask, check_max_fails

__all__ = [
    "MappingTask",
    "NamesTask",
    "TranslationTask",
    "check_max_fails",
    "handle_input_names",
]
