import logging
from typing import Any

from rics.misc import get_public_module, tname

from . import DataStructureIO
from ._dict import DictIO
from ._pandas import PandasIO
from ._sequence import SequenceIO
from ._set import SetIO
from ._single_value import SingleValueIO
from .exceptions import UntranslatableTypeError

RESOLUTION_ORDER: list[type[DataStructureIO]] = [
    DictIO,
    SetIO,
    PandasIO,
    SequenceIO,
    SingleValueIO,
]
LOGGER = logging.getLogger(__package__)


def resolve_io(arg: Any) -> type[DataStructureIO]:
    """Get an IO instance for `arg`.

    Args:
        arg: An argument to get IO for.

    Returns:
        A data structure IO instance for `arg`.

    Raises:
        UntranslatableTypeError: If not IO could be found.
        NotInplaceTranslatableError: If trying to translate an immutable type in-place.

    See Also:
        The func:`register_io` function.
    """
    for tio_class in RESOLUTION_ORDER:
        if tio_class.handles_type(arg):
            if LOGGER.isEnabledFor(logging.DEBUG):
                pretty = tname(arg, prefix_classname=True)
                LOGGER.debug(f"Using '{_pretty_io_name(tio_class)}' for translatable of type='{pretty}'.")

            return tio_class

    raise UntranslatableTypeError(type(arg))


def register_io(io: type[DataStructureIO]) -> None:
    """Register a new IO implementation.

    This will simply add `io` to the head of the internal list of IOs. The IO framework expects ``DataStructureIO``
    instances to be static and stateless, as they will be used by all ``Translator`` instances across the lifetime of
    the Python interpreter.

    Args:
        io: A :class:`.DataStructureIO` type.
    """
    RESOLUTION_ORDER.insert(0, io)

    if LOGGER.isEnabledFor(logging.DEBUG):
        LOGGER.debug(f"Registered custom IO implementation: '{_pretty_io_name(io)}'.")


def _pretty_io_name(io: type[DataStructureIO]) -> str:
    return get_public_module(io, resolve_reexport=True) + "." + tname(io, prefix_classname=True)
