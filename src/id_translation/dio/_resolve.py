from collections.abc import Mapping
from threading import RLock
from typing import Any

from ..types import IdType, NameType, SourceType, TranslatableT
from ._data_structure_io import DataStructureIO
from ._repository import ENTRYPOINT_GROUP, AnyIoType, Repository
from .exceptions import RegistryReentryError

_INSTANCE_LOCK = RLock()  # Re-entrant, so that a thread re-entering from entrypoint loading reaches the check below.
_INSTANCE: Repository | None = None
_LOADING = False  # Only read and written while holding _INSTANCE_LOCK.


def _get_repository(*, reset: bool = False) -> Repository:
    global _INSTANCE, _LOADING  # noqa: PLW0603

    with _INSTANCE_LOCK:
        if _LOADING:  # An entrypoint module used the registry at import. Deferring it would hide that from 2.0 too.
            raise RegistryReentryError(
                f"The IO registry was used while loading the '{ENTRYPOINT_GROUP}' entrypoint integrations.",
                hints="Do not call register() or otherwise use the registry at import time in a module loaded as an"
                " entrypoint, or in one of its parent packages. Discovery registers the class the entrypoint names.",
            )

        if reset or _INSTANCE is None:
            _LOADING = True
            try:
                _INSTANCE = Repository()
            finally:
                _LOADING = False

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
        ~id_translation.dio.exceptions.UntranslatableTypeError: If no suitable IO implementation could be found.
        Exception: Whatever the resolved IO class raises, if construction with `io_kwargs` fails. See the
            :envvar:`ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS` variable to downgrade this to a logged warning instead.

    See Also:
        The :func:`~id_translation.dio.register_io` function.
    """
    return _get_repository().resolve_io(arg, io_kwargs, task_id)


def get_resolution_order() -> list[AnyIoType]:
    """Returns known :class:`~id_translation.dio.DataStructureIO` implementations in the correct resolution order.

    Returns:
        A list of IO implementations sorted by rank.
    """
    return _get_repository().enabled_ios


def register_io(io: AnyIoType) -> None:
    """Register a new IO implementation.

    Classes are polled through :meth:`DataStructureIO.handles_type <id_translation.dio.DataStructureIO.handles_type>` in
    based on :attr:`DataStructureIO.priority <id_translation.dio.DataStructureIO.priority>`.

    Args:
        io: A :class:`~id_translation.dio.DataStructureIO` type
    """
    _get_repository().register(io)


def is_registered(io: AnyIoType) -> bool:
    """Return IO implementation registration status.

    Implementations should register themselves using
    :meth:`DataStructureIO.register <id_translation.dio.DataStructureIO.register>`.

    Args:
        io: A :class:`~id_translation.dio.DataStructureIO` type.
    """
    return _get_repository().is_registered(io)


def reload_integrations() -> None:
    """Discard the registry, then discover, load and register entrypoint integrations afresh.

    Reset the registry, then load entrypoints in the
    :const:`{_ENTRYPOINT_GROUP!r} <id_translation.dio.ENTRYPOINT_GROUP>` entrypoint group (see
    :py:func:`importlib.metadata.entry_points` for details).

    Will skip integrations that raise :class:`ModuleNotFoundError` when loaded. Any other :class:`ImportError`
    (e.g. a circular import) propagates instead.

    Raises:
        TypeError: If an integration does not inherit from :class:`~id_translation.dio.DataStructureIO`.
        ~id_translation.dio.exceptions.RegistryReentryError: If an entrypoint module uses the registry at import.

    Notes:
        The registry loads integrations the same way on first use.
    """
    # TODO(2.0.0): Expose repo class init params, e.g. for keeping manually registered IOs.
    _get_repository(reset=True)


if reload_integrations.__doc__:
    reload_integrations.__doc__ = reload_integrations.__doc__.format(_ENTRYPOINT_GROUP=ENTRYPOINT_GROUP)
