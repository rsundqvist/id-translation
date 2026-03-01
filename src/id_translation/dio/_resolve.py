import logging
from collections.abc import Mapping
from importlib.metadata import entry_points
from inspect import signature
from time import perf_counter
from typing import Any

from rics.misc import tname

from ..types import IdType, NameType, SourceType, TranslatableT
from ._data_structure_io import DataStructureIO
from .exceptions import UntranslatableTypeError

AnyDataStructureIO = DataStructureIO[Any, Any, Any, Any]
_RESOLUTION_ORDER: list[type[AnyDataStructureIO]]
LOGGER = logging.getLogger(__package__)


_ENTRYPOINT_GROUP: str = "id_translation.dio"
"""Alias of the ``__init__.ENTRYPOINT_GROUP`` attribute.

Background:
    https://github.com/sphinx-doc/sphinx/issues/6495#issuecomment-1058033697
    https://github.com/sphinx-doc/sphinx/issues/12020
"""


def resolve_io(
    arg: TranslatableT,
    *,
    io_kwargs: Mapping[str, Any] | None = None,
    task_id: int | None = None,
) -> DataStructureIO[TranslatableT, NameType, SourceType, IdType]:
    """Get an IO instance for `arg`.

    Args:
        arg: An argument to get IO for.
        io_kwargs: Keyword arguments for the IO class (e.g. :class:`~id_translation.dio.integration.pandas.PandasIO`).
        task_id: Used for logging.

    Returns:
        A data structure IO instance for `arg`.

    Raises:
        UntranslatableTypeError: If no suitable IO implementation could be found.

    See Also:
        The :func:`register_io` function.
    """
    eligible_disabled = None
    for io_class in _RESOLUTION_ORDER:
        if io_class.handles_type(arg):
            if io_class.priority < 0 and eligible_disabled is None:
                eligible_disabled = io_class
                continue  # Users may set negative priority to disable implementations after registration.
            return _initialize(arg, io_class, io_kwargs, task_id=task_id)

    exc = UntranslatableTypeError(type(arg))
    if eligible_disabled is not None:
        exc.add_note(f"Hint: Implementation '{_pretty_io_name(eligible_disabled)}' is disabled (priority < 0).")

    raise exc


def _initialize(
    arg: TranslatableT,
    io_class: type[DataStructureIO[TranslatableT, NameType, SourceType, IdType]],
    io_kwargs: Mapping[str, Any] | None = None,
    *,
    task_id: int | None = None,
) -> DataStructureIO[TranslatableT, NameType, SourceType, IdType]:
    if LOGGER.isEnabledFor(logging.DEBUG):
        LOGGER.debug(
            f"Using rank-{_RESOLUTION_ORDER.index(io_class)} (priority={io_class.priority}) implementation"
            f" '{_pretty_io_name(io_class)}' for translatable of type='{tname(arg, include_module=True)}'.",
            extra={"task_id": task_id},
        )

    if "task_id" in signature(io_class).parameters:
        # We don't do this for arbitrary keys, since it would hide incorrect parameters from the caller.
        io_kwargs = {} if io_kwargs is None else {**io_kwargs}
        io_kwargs.setdefault("task_id", task_id)

    if io_kwargs:
        try:
            return io_class(**io_kwargs)
        except Exception as exc:
            # TODO(python-3.13): Use signature(io_class).format() to pretty-print io_class.__init__ parameters.
            LOGGER.warning(
                f"Ignoring {io_kwargs=} since {io_class.__qualname__}(**io_kwargs) raises {type(exc).__name__}.",
                exc_info=exc,
                extra={
                    "task_id": task_id,
                    "io_class": _pretty_io_name(io_class),
                    "io_kwargs": [*io_kwargs],
                },
            )

    return io_class()


def get_resolution_order(*, real: bool = False) -> list[type[AnyDataStructureIO]]:
    """Returns known :class:`.DataStructureIO` implementations in the correct resolution order.

    Args:
        real: If ``True``, return the actual list instead of a copy.

    Returns:
        A list of IO implementations sorted by rank.
    """
    return _RESOLUTION_ORDER if real else [*_RESOLUTION_ORDER]


def register_io(
    io: type[AnyDataStructureIO],
) -> None:
    """Register a new IO implementation.

    Classes are polled through :meth:`.DataStructureIO.handles_type` in based on :attr:`DataStructureIO.priority`.

    Args:
        io: A :class:`.DataStructureIO` type
    """
    if io.priority < 0:
        LOGGER.warning(f"Refusing to register '{_pretty_io_name(io)}' since priority={io.priority} < 0.")
        return

    _RESOLUTION_ORDER.append(io)

    if LOGGER.isEnabledFor(logging.DEBUG):
        LOGGER.debug(f"Registered IO implementation: '{_pretty_io_name(io)}'.")

    _finalize_order()


def _finalize_order() -> None:
    new_order = set()
    for dio in _RESOLUTION_ORDER:
        if dio.priority < 0:
            continue
        new_order.add(dio)

    _RESOLUTION_ORDER.clear()
    _RESOLUTION_ORDER.extend(new_order)
    _RESOLUTION_ORDER.sort(key=lambda io: io.priority, reverse=True)


def _pretty_io_name(io: type[AnyDataStructureIO]) -> str:
    return tname(io, prefix_classname=True, include_module=True)


def is_registered(io: type[AnyDataStructureIO]) -> bool:
    """Return IO implementation registration status.

    Implementations should register themselves using :meth:`.DataStructureIO.register`.

    Args:
        io: A :class:`.DataStructureIO` type.
    """
    return io.priority >= 0 and io in _RESOLUTION_ORDER


def load_integrations() -> None:
    """Discover, load, and register entrypoint integrations.

    Reset the registry, then load entrypoints in the
    :const:`{_ENTRYPOINT_GROUP!r} <id_translation.dio.ENTRYPOINT_GROUP>`
    entrypoint group (see :py:func:`importlib.metadata.entry_points` for details).

    Will skip integrations that raise :class:`ImportError` when loaded.

    Raises:
        TypeError: If an integration does not inherit from :class:`.DataStructureIO`.

    Notes:
        Called automatically when :mod:`id_translation` is imported.
    """
    from .default import DictIO, SequenceIO, SetIO, SingleValueIO  # noqa: PLC0415

    global _RESOLUTION_ORDER  # noqa: PLW0603

    _RESOLUTION_ORDER = [DictIO, SetIO, SequenceIO, SingleValueIO]

    start = perf_counter()

    LOGGER.debug("Initializing %s integrations in group='%s'.", DataStructureIO.__name__, _ENTRYPOINT_GROUP)

    n_total = 0
    n_ok = 0
    for ep in entry_points(group=_ENTRYPOINT_GROUP):
        n_total += 1

        try:
            cls = ep.load()
        except ImportError as e:
            # TODO(2.0.0): ModuleNotFoundError only -- change docs above + rst as well!
            if "circular import" in str(e):
                e.add_note(f"entrypoint={ep!r}")
                raise

            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.debug(f"Failed to import entrypoint={ep!r}: {e!r}.")
            continue

        if not issubclass(cls, DataStructureIO):
            msg = f"Bad entrypoint={ep!r}: {cls} is not a subtype of {DataStructureIO.__name__}. "
            raise TypeError(msg)

        _RESOLUTION_ORDER.append(cls)
        n_ok += 1

    _finalize_order()

    millis = round(1000 * (perf_counter() - start))
    LOGGER.debug("Imported and registered %i/%i integrations in %i milliseconds.", n_ok, n_total, millis)


if load_integrations.__doc__:
    load_integrations.__doc__ = load_integrations.__doc__.format(_ENTRYPOINT_GROUP=_ENTRYPOINT_GROUP)
