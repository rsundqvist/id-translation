import logging
from typing import Any

from rics.misc import get_public_module, tname

from ..types import IdType, NameType, SourceType, TranslatableT
from ._data_structure_io import DataStructureIO
from ._dict import DictIO
from ._pandas import PandasIO
from ._sequence import SequenceIO
from ._set import SetIO
from ._single_value import SingleValueIO
from .exceptions import UntranslatableTypeError

AnyDataStructureIO = DataStructureIO[Any, Any, Any, Any]

RESOLUTION_ORDER: list[type[AnyDataStructureIO]] = [
    DictIO,
    SetIO,
    PandasIO,
    SequenceIO,
    SingleValueIO,
]
LOGGER = logging.getLogger(__package__)


def resolve_io(arg: TranslatableT, **kwargs: Any) -> DataStructureIO[TranslatableT, NameType, SourceType, IdType]:
    """Get an IO instance for `arg`.

    Args:
        arg: An argument to get IO for.
        **kwargs: Keyword arguments for the IO class.

    Returns:
        A data structure IO instance for `arg`.

    Raises:
        UntranslatableTypeError: If no suitable IO implementation could be found.

    See Also:
        The :func:`register_io` function.
    """
    for io_class in RESOLUTION_ORDER:
        if io_class.handles_type(arg):
            return _initialize(arg, io_class, kwargs)

    raise UntranslatableTypeError(type(arg))


def _initialize(
    arg: TranslatableT,
    io_class: type[DataStructureIO[TranslatableT, NameType, SourceType, IdType]],
    kwargs: dict[str, Any],
) -> DataStructureIO[TranslatableT, NameType, SourceType, IdType]:
    try:
        io = io_class(**kwargs)
        with_kwargs = True
    except TypeError:
        io = io_class()
        with_kwargs = False
    if LOGGER.isEnabledFor(logging.DEBUG):
        from rics.misc import format_kwargs

        pretty_arg = tname(arg, prefix_classname=True)
        pretty_class = f"{_pretty_io_name(io_class)}({format_kwargs(kwargs)})" if with_kwargs else ""
        LOGGER.debug(f"Using {pretty_class} for translatable of type='{pretty_arg}'.")
    return io


def register_io(io: type[AnyDataStructureIO]) -> None:
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


def _pretty_io_name(io: type[AnyDataStructureIO]) -> str:
    return get_public_module(io, resolve_reexport=True) + "." + tname(io, prefix_classname=True)
