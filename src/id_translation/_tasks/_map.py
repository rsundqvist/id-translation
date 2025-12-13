import logging
import warnings
from time import perf_counter
from typing import TYPE_CHECKING

from rics.strings import format_seconds as fmt_sec

from .. import logging as _logging
from ..mapping.exceptions import MappingError, MappingWarning
from ..mapping.matrix import ScoreMatrix
from ..mapping.types import UserOverrideFunction
from ..types import IdType, Names, NameToSource, NameType, NameTypes, SourceType, Translatable
from ._names import NamesTask

if TYPE_CHECKING:
    from .._translator import Translator
    from ..mapping import DirectionalMapping


LOGGER = logging.getLogger("id_translation.Translator.map")


class MappingTask(NamesTask[NameType, SourceType, IdType]):
    """Internal type; not part of the public API."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        task_id: int | None = None,
    ) -> None:
        super().__init__(
            caller,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
            task_id=task_id,
        )

        # Task outputs
        self._name_to_source: NameToSource[NameType, SourceType] | None = None

    @property
    def name_to_source(self) -> NameToSource[NameType, SourceType]:
        """Name-to-source mapping."""
        if self._name_to_source is None:
            self._name_to_source = self._map()
        return self._name_to_source

    @property
    def names_to_translate(self) -> list[NameType]:
        """Keys of :attr:`name_to_source`."""
        return list(self.name_to_source)

    def _map(self) -> NameToSource[NameType, SourceType]:
        start = perf_counter()

        values = self.mapper_input_names
        type_name = self.type_name
        names_from_user = self.names_from_user

        if names_from_user is not None and not self.mapper_input_names:
            msg = f"Translation aborted; no names to translate in {type_name}{self._format_params()}."
            warnings.warn(msg, MappingWarning, stacklevel=2)
            LOGGER.warning(msg, extra={"task_id": self.task_id})
            return {}

        sources = self.caller.sources
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(
                f"Begin name-to-source mapping of names={values} in {type_name} against {sources=}.",
                extra=dict(
                    task_id=self.task_id,
                    event_key=_logging.get_event_key(self.caller.map, "enter"),
                    translatable_type=self.full_type_name,
                    values=values,
                    candidates=sources,
                ),
            )

        result: DirectionalMapping[NameType, SourceType]
        result = self.caller.mapper.apply(values, sources, None, self.override_function, task_id=self.task_id)
        name_to_source = result.flatten()
        seconds = perf_counter() - start

        if LOGGER.isEnabledFor(logging.INFO):
            with_nones = {name: name_to_source.get(name) for name in self.mapper_input_names}
            display = with_nones if LOGGER.isEnabledFor(logging.DEBUG) else name_to_source
            LOGGER.info(
                f"Finished mapping of {len(name_to_source)}/{len(self.mapper_input_names)} names in {type_name} "
                f"in {fmt_sec(seconds)}: {display}.",
                extra=dict(
                    task_id=self.task_id,
                    event_key=_logging.get_event_key(self.caller.map, "exit"),
                    seconds=seconds,
                    translatable_type=self.full_type_name,
                    values=values,
                    candidates=sources,
                    mapping=with_nones,
                ),
            )

        if not name_to_source:
            tail = f"could not be mapped to {sources=}{self._format_params()}"

            if names_from_user is None:
                # We're only concerned with mapping here. The NamesTask manages the no-names-at-all case.
                if self.mapper_input_names:
                    msg = (
                        f"Translation aborted; none of the derived names {self.mapper_input_names}"
                        f" in the {type_name}-type data could be mapped to available {sources=}"
                        f"{self._format_params()}."
                    )
                    warnings.warn(msg, MappingWarning, stacklevel=2)
                    LOGGER.warning(msg, extra={"task_id": self.task_id})
                return {}

            unmapped = set(names_from_user).difference(name_to_source)
            if unmapped:
                # Fail if any of the explicitly given names fail to map to a source.
                msg = f"Required names {unmapped} {tail}."
                LOGGER.error(msg, extra={"task_id": self.task_id})
                raise MappingError(msg)

        if result.cardinality.many_right:  # pragma: no cover
            for value, candidates in result.left_to_right.items():
                if len(candidates) > 1:
                    raise MappingError(
                        f"Name-to-source mapping {name_to_source} is ambiguous; {value} -> {candidates}."
                        f"\nHint: Choose a different cardinality such that Mapper.cardinality.many_right is False."
                    )

        self.add_timing("map", seconds)
        return name_to_source

    def compute_scores(self) -> ScoreMatrix[NameType, SourceType]:
        """Compute name-to-source match scores."""
        return self.caller.mapper.compute_scores(
            self.mapper_input_names,
            self.caller.sources,
            override_function=self.override_function,
            task_id=self.task_id,
        )

    def _format_params(self) -> str:
        ignore_names = self.ignore_names
        override_function = self.override_function

        params = []
        if ignore_names is not None:
            params.append(f"{ignore_names=}")
        if override_function is not None:
            params.append(f"{override_function=}")
        return f". Parameters: ({', '.join(params)})" if params else ""
