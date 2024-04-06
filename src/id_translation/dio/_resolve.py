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
        index = RESOLUTION_ORDER.index(io_class)
        LOGGER.debug(f"Using rank-{index} implementation {pretty_class} for translatable of type='{pretty_arg}'.")
    return io


def get_resolution_order(*, real: bool = False) -> list[type[AnyDataStructureIO]]:
    """Returns known :class:`.DataStructureIO` implementations.

    Args:
        real: If ``True``, return the actual list instead of a copy.

    Returns:
        A list of IO implementations.
    """
    return RESOLUTION_ORDER if real else list(RESOLUTION_ORDER)


def register_io(io: type[AnyDataStructureIO]) -> None:
    """Register a new IO implementation.

    Classes are polled through :meth:`.DataStructureIO.handles_type` in reverse insertion order (new implementations are
    polled first). Re-registering an implementation again will move it to the first position in the search order.

    Args:
        io: A :class:`.DataStructureIO` type.
    """
    if io in RESOLUTION_ORDER:
        RESOLUTION_ORDER.remove(io)

    RESOLUTION_ORDER.insert(0, io)
    if LOGGER.isEnabledFor(logging.DEBUG):
        LOGGER.debug(f"Registered custom IO implementation: '{_pretty_io_name(io)}'.")


def _pretty_io_name(io: type[AnyDataStructureIO]) -> str:
    return get_public_module(io, resolve_reexport=True) + "." + tname(io, prefix_classname=True)
