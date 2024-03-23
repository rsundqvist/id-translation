import logging
import warnings
from time import perf_counter
from typing import TYPE_CHECKING

import pandas as pd

from ..mapping.types import UserOverrideFunction
from ._names import NamesTask

if TYPE_CHECKING:
    from .._translator import Translator
    from ..mapping import DirectionalMapping

from ..mapping.exceptions import MappingError, MappingWarning
from ..settings import logging as settings
from ..types import IdType, Names, NameToSource, NameType, NameTypes, SourceType, Translatable

LOGGER = logging.getLogger("id_translation.Translator.map")


class MappingTask(NamesTask[NameType, SourceType, IdType]):
    """Internal type; not part of the public API."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
    ) -> None:
        super().__init__(
            caller,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
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
            LOGGER.warning(msg)
            return {}

        sources = self.caller.sources
        log_level = settings.MAP
        if LOGGER.isEnabledFor(log_level.enter):
            event_key = f"{self.caller.__class__.__name__.upper()}.MAP"
            type_name = self.type_name
            LOGGER.log(
                log_level.enter,
                f"Begin name-to-source mapping of names={values} in {type_name} against {sources=}.",
                extra=dict(
                    task_id=self.task_id,
                    event_key=event_key,
                    event_stage="ENTER",
                    event_title=f"{event_key}.ENTER",
                    translatable_type=type_name,
                    values=values,
                    candidates=sources,
                    context=None,
                ),
            )

        result: DirectionalMapping[NameType, SourceType]
        result = self.caller.mapper.apply(values, sources, None, self.override_function)
        name_to_source = result.flatten()
        if LOGGER.isEnabledFor(log_level.exit):
            execution_time = perf_counter() - start
            LOGGER.log(
                log_level.exit,
                f"Finished name-to-source mapping of names={values} in {type_name} against {sources=}:"
                f" {name_to_source}.",
                extra=dict(
                    task_id=self.task_id,
                    event_key=event_key,
                    event_stage="EXIT",
                    event_title=f"{event_key}.EXIT",
                    execution_time=execution_time,
                    translatable_type=type_name,
                    mapping=name_to_source,
                    context=None,
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
                    LOGGER.warning(msg)
                return {}

            unmapped = set(names_from_user).difference(name_to_source)
            if unmapped:
                # Fail if any of the explicitly given names fail to map to a source.
                msg = f"Required names {unmapped} {tail}."
                LOGGER.error(msg)
                raise MappingError(msg)

        if result.cardinality.many_right:  # pragma: no cover
            for value, candidates in result.left_to_right.items():
                if len(candidates) > 1:
                    raise MappingError(
                        f"Name-to-source mapping {name_to_source} is ambiguous; {value} -> {candidates}."
                        f"\nHint: Choose a different cardinality such that Mapper.cardinality.many_right is False."
                    )
        return name_to_source

    def compute_scores(self) -> pd.DataFrame:
        """Compute name-to-source match scores."""
        return self.caller.mapper.compute_scores(
            self.mapper_input_names,
            self.caller.sources,
            override_function=self.override_function,
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
