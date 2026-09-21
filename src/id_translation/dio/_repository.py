import logging
from collections.abc import Iterable, Mapping
from importlib.metadata import entry_points
from inspect import signature
from time import perf_counter
from typing import Any

from rics.env.read import read_bool
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

SUPPRESS_IO_KWARGS_ERRORS = "ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS"
"""See the :envvar:`ID_TRANSLATION_SUPPRESS_IO_KWARGS_ERRORS` variable."""

_LOGGER = logging.getLogger(__package__)


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
        self._enabled: list[AnyIoType] = []
        self._disabled: dict[AnyIoType, str] = {}  # Implementation -> reason.
        for io_class in sorted(self._discovered, key=pretty_io_name):  # Ties among discovered: by name.
            if io_class.priority < 0:
                self._disabled[io_class] = "opt-in"
            else:
                self._enabled.append(io_class)
        self._rank()

    @property
    def enabled_ios(self) -> list[AnyIoType]:
        """List of enabled IO implementations, best rank first."""
        return [*self._enabled]

    @property
    def disabled_ios(self) -> list[AnyIoType]:
        """List of known implementations that are not currently eligible."""
        return [*self._disabled]

    @property
    def all_ios(self) -> list[AnyIoType]:
        """List of all known IO implementations."""
        return [*self.enabled_ios, *self.disabled_ios]

    def register(self, io_class: AnyIoType) -> None:
        """Enable `io_class`, ahead of any other implementation with the same ``abs(priority)``."""
        self._disabled.pop(io_class, None)
        if io_class in self._enabled:
            self._enabled.remove(io_class)
        self._enabled.insert(0, io_class)
        self._rank()

        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                f"Registered IO implementation '{pretty_io_name(io_class)}' at rank-{self._enabled.index(io_class)}"
                f" (priority={io_class.priority})."
            )

    def unregister(self, io_class: AnyIoType) -> None:
        """Disable `io_class`. A discovered implementation stays known; any other is forgotten."""
        if io_class in self._enabled:
            self._enabled.remove(io_class)
        if io_class in self._discovered:
            self._disabled[io_class] = "unregistered"
        else:
            self._disabled.pop(io_class, None)
        self._rank()

    def _rank(self) -> None:
        # Stable, so ties keep their current order. This is also when changes to `priority` take effect.
        self._enabled.sort(key=lambda io_class: abs(io_class.priority), reverse=True)

    def is_registered(self, io_class: AnyIoType) -> bool:
        """Return `io_class` registration status."""
        return io_class in self._enabled

    def resolve_io(
        self,
        arg: TranslatableT,
        io_kwargs: Mapping[str, Any] | None = None,
        task_id: int | None = None,
    ) -> AnyIo:
        """Get an IO instance for `arg` or raise ``UntranslatableTypeError``."""
        for io_class in self._enabled:
            if io_class.handles_type(arg):
                return self._initialize(arg, io_class, io_kwargs, task_id=task_id)

        hints = [
            f"Eligible implementation '{pretty_io_name(io_class)}' is disabled ({reason});"
            f" call {io_class.__qualname__}.register() to enable it."
            for io_class, reason in sorted(self._disabled.items(), key=lambda item: abs(item[0].priority), reverse=True)
            if io_class.handles_type(arg)
        ]
        raise UntranslatableTypeError(type(arg), hints=hints)

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
