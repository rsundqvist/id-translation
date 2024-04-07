from time import perf_counter
from typing import TYPE_CHECKING, Generic

from rics.misc import get_public_module, tname

if TYPE_CHECKING:
    from .._translator import Translator

from ..dio import DataStructureIO, resolve_io
from ..types import IdType, NameType, SourceType, Translatable


class BaseTask(Generic[NameType, SourceType, IdType]):
    """Internal type; not part of the public API."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
    ) -> None:
        self.caller = caller

        self.translatable = translatable

        self._io: DataStructureIO[Translatable[NameType, IdType], NameType, SourceType, IdType]
        self._io = resolve_io(translatable)
        self._start = perf_counter()
        self._task_id = generate_task_id(self._start)

        if caller.online:
            caller.fetcher.initialize_sources(self.task_id)

    @property
    def io(self) -> DataStructureIO[Translatable[NameType, IdType], NameType, SourceType, IdType]:
        """Initialized :class:`DataStructureIO` instance."""
        return self._io

    @property
    def type_name(self) -> str:
        """Stylized typename."""
        return repr(tname(self.translatable, prefix_classname=True))

    @property
    def full_type_name(self) -> str:
        """Canonical typename."""
        clazz = type(self.translatable)
        return get_public_module(clazz) + "." + clazz.__qualname__

    @property
    def task_id(self) -> int:
        """Generated ID for this task. Used for logging."""
        return self._task_id


def generate_task_id(start: float | None = None) -> int:
    """Generate a new task ID."""
    return round(1000 * (perf_counter() if start is None else start))
