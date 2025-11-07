from time import perf_counter
from typing import TYPE_CHECKING, Generic

from rics.misc import get_public_module

from ..logging import generate_task_id

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
        task_id: int | None = None,
    ) -> None:
        self.caller = caller

        self.translatable = translatable

        self._io: DataStructureIO[Translatable[NameType, IdType], NameType, SourceType, IdType]
        self._start = perf_counter()
        self._task_id = generate_task_id(self._start) if task_id is None else task_id

        self._io = resolve_io(translatable, task_id=self.task_id)
        self._type_name: str | None = None
        self._full_type_name: str | None = None

        self._timings: dict[str, float] = {}

        if caller.online:
            caller.fetcher.initialize_sources(self.task_id)

    def add_timing(self, key: str, value: float, /) -> None:
        """Add timing."""
        # assert key not in self._timings, f"duplicate {key=}"
        self._timings[key] = value

    def get_timings_ms(self) -> dict[str, float]:
        """Retrieve timings."""
        return {k: round(1000 * v, 3) for k, v in self._timings.items()}

    @property
    def io(self) -> DataStructureIO[Translatable[NameType, IdType], NameType, SourceType, IdType]:
        """Initialized :class:`DataStructureIO` instance."""
        return self._io

    @property
    def type_name(self) -> str:
        """Stylized type name, e.g. `'DataFrame'`."""
        if self._type_name is None:
            self._type_name = repr(type(self.translatable).__name__)
        return self._type_name

    @property
    def full_type_name(self) -> str:
        """Canonical type name, e.g. `pandas.DataFrame`."""
        if self._full_type_name is None:
            self._full_type_name = get_public_module(type(self.translatable), resolve_reexport=True, include_name=True)
        return self._full_type_name

    @property
    def task_id(self) -> int:
        """Generated ID for this task. Used for logging."""
        return self._task_id
