from collections.abc import Mapping
from threading import Lock
from typing import Any

from ..types import IdType, NameType, SourceType, TranslatableT
from ._data_structure_io import DataStructureIO
from ._repository import ENTRYPOINT_GROUP, AnyIoType, Repository

_INSTANCE_LOCK = Lock()
_INSTANCE: Repository | None = None


def _get_repository(*, reset: bool = False) -> Repository:
    global _INSTANCE  # noqa: PLW0603

    with _INSTANCE_LOCK:
        if reset or _INSTANCE is None:
            _INSTANCE = Repository()

    return _INSTANCE


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
    return _get_repository().resolve_io(arg, io_kwargs, task_id)


def get_resolution_order(*, real: bool = False) -> list[AnyIoType]:
    """Returns known :class:`.DataStructureIO` implementations in the correct resolution order.

    Args:
        real: If ``True``, return the actual list instead of a copy.

    Returns:
        A list of IO implementations sorted by rank.
    """
    # TODO(2.0.0): Copy only.
    repo = _get_repository()
    return repo._enabled if real else repo.enabled_ios


def register_io(io: AnyIoType) -> None:
    """Register a new IO implementation.

    Classes are polled through :meth:`.DataStructureIO.handles_type` in based on :attr:`DataStructureIO.priority`.

    Args:
        io: A :class:`.DataStructureIO` type
    """
    _get_repository().register(io)


def is_registered(io: AnyIoType) -> bool:
    """Return IO implementation registration status.

    Implementations should register themselves using :meth:`.DataStructureIO.register`.

    Args:
        io: A :class:`.DataStructureIO` type.
    """
    return _get_repository().is_registered(io)


def load_integrations() -> None:
    """Discover, load, and register entrypoint integrations.

    Reset the registry, then load entrypoints in the
    :const:`{_ENTRYPOINT_GROUP!r} <id_translation.dio.ENTRYPOINT_GROUP>`
    entrypoint group (see :py:func:`importlib.metadata.entry_points` for details).

    Will skip integrations that raise :class:`ImportError` when loaded (except circular imports).

    Raises:
        TypeError: If an integration does not inherit from :class:`.DataStructureIO`.

    Notes:
        Called automatically when :mod:`id_translation` is imported.
    """
    # TODO(2.0.0): Rename to reload_integrations, or similar.
    # TODO(2.0.0): Expose repo class init params, e.g. for keeping manually registered IOs.
    _get_repository(reset=True)


if load_integrations.__doc__:
    load_integrations.__doc__ = load_integrations.__doc__.format(_ENTRYPOINT_GROUP=ENTRYPOINT_GROUP)
