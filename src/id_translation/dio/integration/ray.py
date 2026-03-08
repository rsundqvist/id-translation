"""Integration for `Ray <https://docs.ray.io/en/latest/data/data.html>`_ types."""

import logging as _l
import typing as _t
from collections import abc as _abc

import ray.data as _rd
from rics.misc import tname as _tname

from id_translation import dio as _dio
from id_translation import types as _tt
from id_translation.dio.exceptions import NotInplaceTranslatableError as _NotInplaceTranslatableError
from id_translation.offline import TranslationMap as _TranslationMap

if _t.TYPE_CHECKING:
    import numpy
    import pandas
    import pyarrow  # type: ignore[import-untyped]

RayT = _t.TypeVar("RayT", bound=_rd.Dataset)
"""Supported ``ray`` types."""
RayBatchT = _t.TypeVar("RayBatchT", "dict[str, numpy.typing.NDArray[_t.Any]]", "pandas.DataFrame", "pyarrow.Table")
"""Supported ``ray`` batch types."""


class RayIO(_dio.DataStructureIO[RayT, str, _tt.SourceType, _tt.IdType]):
    """Optional IO implementation for ``ray`` types.

    Translation is performed using :meth:`ray.data.Dataset.map_batches`, delegating to :func:`translate_batch` using
    appropriate arguments.

    .. note::

       Available features are determined by the batch-level IO implementation. For example, to use a feature provided
       by the :class:`.PandasIO`, you may pass ``batch_format="pandas"``.

    Args:
        copy: Set to ``False`` to perform in-place translation in :func:`translate_batch`.
        batch_size: Number of rows in each batch; see :meth:`~ray.data.Dataset.map_batches`.
        batch_format: Data format used; see :meth:`~ray.data.Dataset.map_batches`. Determines valid `io_kwargs`.
        task_id: Used for logging.
        **io_kwargs: Forwarded to the underlying IO implementation.

    See Also:
        The :class:`.PandasIO` and :class:`.ArrowIO` classes.
    """

    def __init__(
        self,
        *,
        copy: bool = True,
        batch_size: int | None | _t.Literal["default"] = None,
        batch_format: _t.Literal["default", "numpy", "pandas", "pyarrow"] | None = "default",
        task_id: int | None = None,
        **io_kwargs: _t.Any,
    ) -> None:
        self._copy = copy

        self._batch_size = batch_size
        self._batch_format = batch_format

        self._task_id = task_id
        self._io_kwargs = io_kwargs

        self._logger = _l.getLogger(_tname(self, include_module=True))

    priority = -1970

    @property
    def logger(self) -> _l.Logger:
        """Logger used by this instance."""
        return self._logger

    @classmethod
    def handles_type(cls, arg: _t.Any) -> bool:
        return isinstance(arg, (_rd.dataset.Dataset, _rd.dataset.MaterializedDataset))

    @classmethod
    def names(cls, translatable: RayT) -> list[str] | None:
        return translatable.columns(fetch_if_missing=True)  # type: ignore[no-any-return]

    @classmethod
    def extract(cls, translatable: RayT, names: list[str]) -> dict[str, _abc.Sequence[_tt.IdType]]:
        return {name: translatable.unique(name, ignore_nulls=True) for name in names}

    def insert(
        self,
        translatable: RayT,
        names: list[str],
        tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
        copy: bool,
    ) -> _rd.Dataset:  # MaterializedDataset.map_batches() -> Dataset. TODO: Translator.translate() overload?
        if not copy:
            exc = _NotInplaceTranslatableError(translatable)
            if self._copy:
                io_kwargs = {"copy": False}
                exc.add_note(f"Hint: Pass `{io_kwargs=}` to perform in-place translation on batches.")
            raise exc

        # TODO(ray) Implement TranslationMap.__hash__?
        tmap.__hash__ = lambda tmap_self: hash(id(tmap_self))  # type: ignore[misc, assignment]

        io = self._resolve_io(translatable)
        return translatable.map_batches(
            translate_batch,  # type: ignore[arg-type]
            fn_args=(io, names, tmap, self._copy),
            batch_size=self._batch_size,
            batch_format=self._batch_format,
            udf_modifying_row_count=False,
        )

    def _resolve_io(self, translatable: RayT) -> _dio.DataStructureIO[RayBatchT, str, _tt.SourceType, _tt.IdType]:
        batch = translatable.take_batch(batch_size=1, batch_format=self._batch_format)

        io: _dio.DataStructureIO[RayBatchT, str, _tt.SourceType, _tt.IdType]
        io = _dio.resolve_io(batch, io_kwargs=self._io_kwargs, task_id=self._task_id)

        if self._logger.isEnabledFor(_l.DEBUG):
            self._logger.debug(
                f"Derived io={_tname(io, include_module=True)} based on batch_format={self._batch_format!r}.",
                extra={"task_id": self._task_id},
            )

        return io


def translate_batch(
    batch: RayBatchT,
    io: _dio.DataStructureIO[RayBatchT, str, _tt.SourceType, _tt.IdType],
    names: list[str],
    tmap: _TranslationMap[str, _tt.SourceType, _tt.IdType],
    copy: bool,
) -> RayBatchT:
    """Translate a single Ray batch."""
    result = io.insert(batch, names, tmap, copy)
    return batch if result is None else result
