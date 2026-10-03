import logging
from collections.abc import Iterable, Mapping
from importlib.metadata import entry_points
from inspect import signature
from threading import Lock
from time import perf_counter
from typing import Any, NamedTuple

from rics.env.read import read_bool
from rics.misc import tname

from ..types import TranslatableT
from ._data_structure_io import DataStructureIO
from ._util import pretty_io_name
from .exceptions import RegistryReentryError, UntranslatableTypeError

AnyIo = DataStructureIO[Any, Any, Any, Any]
AnyIoType = type[AnyIo]

ENTRYPOINT_GROUP: str = "id_translation.dio"
"""Alias of the ``__init__.ENTRYPOINT_GROUP`` attribute.

Background:
    https://github.com/sphinx-doc/sphinx/issues/6495#issuecomment-1058033697
    https://github.com/sphinx-doc/sphinx/issues/12020
"""

SUPPRESS_IO_KWARGS_ERRORS = "ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS"
"""See the :envvar:`ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS` variable."""

_LOGGER = logging.getLogger(__package__)


class _State(NamedTuple):
    enabled: list[AnyIoType]  # Best rank first.
    disabled: dict[AnyIoType, str]  # Implementation -> reason.


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
            from .default import DictIO, ScalarIO, SequenceIO, SetIO  # noqa: PLC0415
            from .default import __all__ as all_default_ios  # noqa: PLC0415

            defaults = [DictIO, SetIO, SequenceIO, ScalarIO]
            ios.extend(defaults)  # type: ignore[arg-type]
            assert len(defaults) == len(all_default_ios)  # noqa: S101

        if load_integrations:
            integrations = self._load_integrations()
            ios.extend(integrations)

        # Implementations known without a `register` call. Anything else is forgotten again by `unregister`.
        self._discovered = frozenset(ios)
        # The sign of `priority` decides the initial state only; after that, the last `register` or `unregister` wins.
        enabled: list[AnyIoType] = []
        disabled: dict[AnyIoType, str] = {}
        for io_class in sorted(self._discovered, key=pretty_io_name):  # Ties among discovered: by name.
            if io_class.priority < 0:
                disabled[io_class] = "opt-in"
            else:
                enabled.append(io_class)

        # Writers hold the lock and swap in a new state instead of mutating this one. Readers take one reference and
        # need no lock; the collections it holds never change.
        self._lock = Lock()
        self._state = _State(_rank(enabled), disabled)

    @property
    def enabled_ios(self) -> list[AnyIoType]:
        """List of enabled IO implementations, best rank first."""
        return [*self._state.enabled]

    @property
    def disabled_ios(self) -> list[AnyIoType]:
        """List of known implementations that are not currently eligible."""
        return [*self._state.disabled]

    @property
    def all_ios(self) -> list[AnyIoType]:
        """List of all known IO implementations."""
        enabled, disabled = self._state
        return [*enabled, *disabled]

    def register(self, io_class: AnyIoType) -> None:
        """Enable `io_class`, ahead of any other implementation with the same ``abs(priority)``."""
        with self._lock:
            enabled, disabled = self._state
            enabled = _rank([io_class, *(other for other in enabled if other is not io_class)])
            disabled = {other: reason for other, reason in disabled.items() if other is not io_class}
            self._state = _State(enabled, disabled)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Registered IO implementation '{pretty_io_name(io_class)}' at rank-{enabled.index(io_class)}"
                f" (priority={io_class.priority})."
            )

    def unregister(self, io_class: AnyIoType) -> None:
        """Disable `io_class`. A discovered implementation stays known; any other is forgotten."""
        with self._lock:
            enabled, disabled = self._state
            enabled = _rank([other for other in enabled if other is not io_class])
            disabled = {other: reason for other, reason in disabled.items() if other is not io_class}
            if io_class in self._discovered:
                disabled[io_class] = "unregistered"
            self._state = _State(enabled, disabled)

    def is_registered(self, io_class: AnyIoType) -> bool:
        """Return `io_class` registration status."""
        return io_class in self._state.enabled

    def resolve_io(
        self,
        arg: TranslatableT,
        io_kwargs: Mapping[str, Any] | None = None,
        task_id: int | None = None,
    ) -> AnyIo:
        """Get an IO instance for `arg` or raise ``UntranslatableTypeError``."""
        enabled, disabled = self._state
        for rank, io_class in enumerate(enabled):
            if io_class.handles_type(arg):
                return self._initialize(arg, io_class, rank, io_kwargs, task_id=task_id)

        hints = [
            f"An eligible implementation is disabled ({reason});"
            f" call {pretty_io_name(io_class)}.register() to enable it."
            for io_class, reason in sorted(disabled.items(), key=lambda item: abs(item[0].priority), reverse=True)
            if io_class.handles_type(arg)
        ]
        raise UntranslatableTypeError(type(arg), hints=hints)

    @staticmethod
    def _initialize(
        arg: TranslatableT,
        io_class: AnyIoType,
        rank: int,
        io_kwargs: Mapping[str, Any] | None = None,
        *,
        task_id: int | None = None,
    ) -> AnyIo:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Using rank-{rank} (priority={io_class.priority}) implementation"
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
                if read_bool(SUPPRESS_IO_KWARGS_ERRORS):
                    _LOGGER.warning(
                        f"Ignoring {io_kwargs=} since {io_class.__qualname__}(**io_kwargs) raises"
                        f" {type(exc).__name__}.",
                        exc_info=exc,
                        extra={
                            "task_id": task_id,
                            "io_class": pretty_io_name(io_class),
                            "io_kwargs": [*io_kwargs],
                        },
                    )
                else:
                    exc.add_note(
                        f"Hint: Set {SUPPRESS_IO_KWARGS_ERRORS}=true to ignore this and construct"
                        f" {pretty_io_name(io_class)}() without io_kwargs instead."
                    )
                    raise

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


def _rank(ios: list[AnyIoType]) -> list[AnyIoType]:
    # Stable, so ties keep their current order. This is also when changes to `priority` take effect.
    return sorted(ios, key=lambda io_class: abs(io_class.priority), reverse=True)


def reentry_error() -> RegistryReentryError:
    return RegistryReentryError(
        f"The IO registry was used while loading the '{ENTRYPOINT_GROUP}' entrypoint integrations.",
        hints=(
            "Do not call register() or otherwise use the registry at import time in a module loaded as an entrypoint,"
            " or in one of its parent packages. Discovery enables its implementation unless it is opt-in, in which"
            " case the application must call register()."
        ),
    )


def _load_integrations() -> tuple[list[AnyIoType], int]:
    n_total = 0
    integrations: list[AnyIoType] = []
    for ep in entry_points(group=ENTRYPOINT_GROUP):
        n_total += 1

        try:
            cls = ep.load()
        except ModuleNotFoundError as e:
            # Circular import raises plain ImportError, not ModuleNotFoundError.
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(f"Failed to import entrypoint={ep!r}: {e!r}.")
            continue
        except Exception as e:
            e.add_note(f"entrypoint={ep!r}")
            raise

        if not issubclass(cls, DataStructureIO):
            msg = f"Bad entrypoint={ep!r}: {cls} is not a subtype of {DataStructureIO.__name__}. "
            raise TypeError(msg)

        integrations.append(cls)

    return integrations, n_total
