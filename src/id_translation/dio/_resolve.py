from typing import Any, Type

from . import DataStructureIO
from ._dict import DictIO
from ._pandas import PandasIO
from ._sequence import SequenceIO
from ._set import SetIO
from ._single_value import SingleValueIO
from .exceptions import UntranslatableTypeError


def resolve_io(arg: Any) -> Type[DataStructureIO]:
    """Get an IO instance for `arg`.

    Args:
        arg: An argument to get IO for.

    Returns:
        A data structure IO instance for `arg`.

    Raises:
        UntranslatableTypeError: If not IO could be found.
    """
    for tio_class in DictIO, SetIO, PandasIO, SequenceIO, SingleValueIO:
        if tio_class.handles_type(arg):
            return tio_class

    raise UntranslatableTypeError(type(arg))
