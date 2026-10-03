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
from .exceptions import DataStructureIOError, RegistryReentryError, UntranslatableTypeError

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
    enabled: dict[AnyIoType, int]  # Implementation -> priority when registered. Best rank first.
    disabled: dict[AnyIoType, tuple[str, int]]  # Implementation -> (reason, priority when disabled).


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
        enabled: dict[AnyIoType, int] = {}
        disabled: dict[AnyIoType, tuple[str, int]] = {}
        for io_class in sorted(self._discovered, key=pretty_io_name):  # Ties among discovered: by name.
            if io_class.priority < 0:
                disabled[io_class] = ("opt-in", io_class.priority)
            else:
                enabled[io_class] = io_class.priority

        # Writers hold the lock and swap in a new state instead of mutating this one. Readers take one reference and
        # need no lock, since the collections it holds never change.
        self._lock = Lock()
        self._state = _State(_rank(enabled), disabled)

    @property
    def enabled_ios(self) -> list[AnyIoType]:
        """List of enabled IO implementations, best rank first."""
        state = self._state
        _verify_priorities(state)
        return [*state.enabled]

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
        priority = io_class.priority  # Read once; a later change raises until the next `register` or `unregister`.
        with self._lock:
            enabled, disabled = self._state
            enabled = _rank({io_class: priority, **{other: p for other, p in enabled.items() if other is not io_class}})
            disabled = {other: value for other, value in disabled.items() if other is not io_class}
            self._state = _State(enabled, disabled)

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Registered IO implementation '{pretty_io_name(io_class)}' at rank-{[*enabled].index(io_class)}"
                f" ({priority=})."
            )

    def unregister(self, io_class: AnyIoType) -> None:
        """Disable `io_class`. A discovered implementation stays known; any other is forgotten."""
        priority = io_class.priority  # Read once, like `register` does.
        with self._lock:
            enabled, disabled = self._state
            enabled = {other: p for other, p in enabled.items() if other is not io_class}
            disabled = {other: value for other, value in disabled.items() if other is not io_class}
            if io_class in self._discovered:
                disabled[io_class] = ("unregistered", priority)
            self._state = _State(enabled, disabled)

    def is_registered(self, io_class: AnyIoType) -> bool:
        """Return `io_class` registration status."""
        state = self._state
        _verify_priorities(state)
        return io_class in state.enabled

    def resolve_io(
        self,
        arg: TranslatableT,
        io_kwargs: Mapping[str, Any] | None = None,
        task_id: int | None = None,
    ) -> AnyIo:
        """Get an IO instance for `arg` or raise ``UntranslatableTypeError``."""
        state = self._state
        _verify_priorities(state)
        enabled, disabled = state
        for rank, io_class in enumerate(enabled):
            if io_class.handles_type(arg):
                return self._initialize(arg, io_class, rank, io_kwargs, task_id=task_id)

        hints = [
            f"An eligible implementation is disabled ({reason});"
            f" call {pretty_io_name(io_class)}.register() to enable it."
            for io_class, (reason, _) in sorted(disabled.items(), key=lambda item: abs(item[0].priority), reverse=True)
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


def _rank(enabled: dict[AnyIoType, int]) -> dict[AnyIoType, int]:
    # Stable, so ties keep their current order.
    return dict(sorted(enabled.items(), key=lambda item: abs(item[1]), reverse=True))


def _verify_priorities(state: _State) -> None:
    # Implementation -> (priority when read, the call that applies the change).
    changed: dict[AnyIoType, tuple[int, str]] = {}
    for io_class, priority in state.enabled.items():
        if io_class.priority != priority:
            # A v1-style negation means "disable"; register() would do the opposite and enable it at abs(priority).
            changed[io_class] = priority, "unregister" if io_class.priority < 0 <= priority else "register"
    for io_class, (_, priority) in state.disabled.items():
        if priority < 0 <= io_class.priority:
            changed[io_class] = priority, "register"  # The v1 way to enable. Other changes are read at register().
    if not changed:
        return

    io_class, (priority, method) = next(iter(changed.items()))
    name, new = io_class.__name__, io_class.priority
    msg = f"{name}.priority changed from {priority} to {new} since discovery or the last register() or unregister()."
    owner = next(cls for cls in io_class.__mro__ if "priority" in vars(cls))
    if owner is not io_class:
        msg += f" The value is inherited from {owner.__name__}."
    if len(changed) > 1:
        msg += f" Also changed: {', '.join(other.__name__ for other in [*changed][1:])}."

    full_name = pretty_io_name(io_class)
    if method == "unregister":
        hints = [f"A negative priority does not disable a registered implementation; call {full_name}.unregister()."]
    elif io_class in state.disabled:
        hints = [
            f"A non-negative priority does not enable a disabled implementation; call {full_name}.register() to enable"
            " it, or unregister() to keep it disabled."
        ]
    else:
        hints = [f"Call {full_name}.register() to apply the new priority, or unregister() to disable it."]

    if others := [other.__name__ for other, (_, m) in changed.items() if m != method]:
        other_method = "register" if method == "unregister" else "unregister"
        hints.append(f"Call {other_method}() on {', '.join(others)} instead.")
    raise DataStructureIOError(msg, hints=hints, anchor="io-priority")


def reentry_error() -> RegistryReentryError:
    return RegistryReentryError(
        f"The IO registry was used while loading the '{ENTRYPOINT_GROUP}' entrypoint integrations.",
        hints=(
            "Do not call register() or otherwise use the registry at import time in a module loaded as an entrypoint,"
            " or in one of its parent packages. Discovery enables its implementation unless it is opt-in, in which"
            " case the application must call register()."
        ),
        anchor="automatic-integration-discovery",
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
