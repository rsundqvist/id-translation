import logging
from collections.abc import Iterable, Mapping
from importlib.metadata import entry_points
from inspect import signature
from threading import Lock
from time import perf_counter
from typing import Any

from rics.misc import tname

from ..types import TranslatableT
from ._data_structure_io import DataStructureIO
from ._util import pretty_io_name
from .exceptions import UntranslatableTypeError

AnyIo = DataStructureIO[Any, Any, Any, Any]
AnyIoType = type[AnyIo]

ENTRYPOINT_GROUP: str = "id_translation.dio"
"""Alias of the ``__init__.ENTRYPOINT_GROUP`` attribute.

Background:
    https://github.com/sphinx-doc/sphinx/issues/6495#issuecomment-1058033697
    https://github.com/sphinx-doc/sphinx/issues/12020
"""

_LOGGER = logging.getLogger(__package__)

_INSTANCE_LOCK = Lock()
_INSTANCE: "Repository | None" = None


def get_repository(*, reset: bool = False) -> "Repository":
    global _INSTANCE  # noqa: PLW0603

    with _INSTANCE_LOCK:
        if reset or _INSTANCE is None:
            _INSTANCE = Repository()

    return _INSTANCE


class Repository:
    def __init__(
        self,
        *,
        ios: Iterable[AnyIoType] = (),
        load_integrations: bool = True,
        load_defaults: bool = True,
    ) -> None:
        ios = [*ios]

        if load_defaults:
            from .default import DictIO, SequenceIO, SetIO, SingleValueIO  # noqa: PLC0415
            from .default import __all__ as all_default_ios  # noqa: PLC0415

            defaults = [DictIO, SetIO, SequenceIO, SingleValueIO]
            ios.extend(defaults)  # type: ignore[arg-type]
            assert len(defaults) == len(all_default_ios)  # noqa: S101

        if load_integrations:
            integrations = self._load_integrations()
            ios.extend(integrations)

        self._enabled, self._disabled = _sort_ios(*ios)

    @property
    def enabled_ios(self) -> list[AnyIoType]:
        """List of enabled (priority >= 0) IO implementations."""
        return [*self._enabled]

    @property
    def disabled_ios(self) -> list[AnyIoType]:
        """List of disabled (priority < 0) IO implementations."""
        return [*self._disabled]

    @property
    def all_ios(self) -> list[AnyIoType]:
        """List of all known IO implementations."""
        return [*self.enabled_ios, *self.disabled_ios]

    def register(self, io_class: AnyIoType) -> None:
        """Register `io_class` in this repository."""
        if io_class.priority < 0:
            self._disabled.add(io_class)
            _LOGGER.warning(f"Registered '{pretty_io_name(io_class)}' with priority={io_class.priority} < 0.")
            return

        self._enabled, self._disabled = _sort_ios(io_class, *self._enabled, *self._disabled)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(f"Registered IO implementation: '{pretty_io_name(io_class)}'.")

    def is_registered(self, io_class: AnyIoType) -> bool:
        """Return `io_class` registration status."""
        return io_class.priority >= 0 and io_class in self._enabled

    def resolve_io(
        self,
        arg: TranslatableT,
        io_kwargs: Mapping[str, Any] | None = None,
        task_id: int | None = None,
    ) -> AnyIo:
        """Get an IO instance for `arg` or raise ``UntranslatableTypeError``."""
        move_to_disabled = []

        for io_class in self._enabled:
            if io_class.priority < 0:
                move_to_disabled.append(io_class)
            elif io_class.handles_type(arg):
                return self._initialize(arg, io_class, io_kwargs, task_id=task_id)

        for io_class in move_to_disabled:
            self._enabled.remove(io_class)
            self._disabled.add(io_class)

        exc = UntranslatableTypeError(type(arg))
        for io_class in sorted(self._disabled, key=lambda io_class: abs(io_class.priority), reverse=True):
            if io_class.handles_type(arg):
                exc.add_note(
                    f"Hint: Eligible implementation '{pretty_io_name(io_class)}' is disabled (priority={io_class.priority} < 0)."
                )

        raise exc

    def _initialize(
        self,
        arg: TranslatableT,
        io_class: AnyIoType,
        io_kwargs: Mapping[str, Any] | None = None,
        *,
        task_id: int | None = None,
    ) -> AnyIo:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Using rank-{self._enabled.index(io_class)} (priority={io_class.priority}) implementation"
                f" '{pretty_io_name(io_class)}' for translatable of type='{tname(arg, include_module=True)}'.",
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
                _LOGGER.warning(
                    f"Ignoring {io_kwargs=} since {io_class.__qualname__}(**io_kwargs) raises {type(exc).__name__}.",
                    exc_info=exc,
                    extra={
                        "task_id": task_id,
                        "io_class": pretty_io_name(io_class),
                        "io_kwargs": [*io_kwargs],
                    },
                )

        return io_class()

    @classmethod
    def _load_integrations(cls) -> list[AnyIoType]:
        start = perf_counter()
        _LOGGER.debug("Importing %s integrations in group='%s'.", DataStructureIO.__name__, ENTRYPOINT_GROUP)

        integrations, n_total = _load_integrations()

        millis = round(1000 * (perf_counter() - start))
        _LOGGER.debug(
            "Imported and registered %i/%i integrations in %i milliseconds.", len(integrations), n_total, millis
        )
        return integrations


def _load_integrations() -> tuple[list[AnyIoType], int]:
    n_total = 0
    integrations: list[AnyIoType] = []
    for ep in entry_points(group=ENTRYPOINT_GROUP):
        n_total += 1

        try:
            cls = ep.load()
        except ImportError as e:
            # TODO(2.0.0): ModuleNotFoundError only -- change docs above + rst as well!
            if "circular import" in str(e):
                e.add_note(f"entrypoint={ep!r}")
                raise

            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(f"Failed to import entrypoint={ep!r}: {e!r}.")
            continue

        if not issubclass(cls, DataStructureIO):
            msg = f"Bad entrypoint={ep!r}: {cls} is not a subtype of {DataStructureIO.__name__}. "
            raise TypeError(msg)

        integrations.append(cls)

    return integrations, n_total


def _sort_ios(*ios: AnyIoType) -> tuple[list[AnyIoType], set[AnyIoType]]:
    enabled: list[AnyIoType] = []
    disabled: set[AnyIoType] = set()

    for dio in set(ios):
        if dio.priority < 0:
            disabled.add(dio)
        else:
            enabled.append(dio)

    enabled.sort(key=lambda io_class: io_class.priority, reverse=True)

    return enabled, disabled
