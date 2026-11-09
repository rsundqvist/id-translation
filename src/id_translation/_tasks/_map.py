import logging
from collections.abc import Mapping
from time import perf_counter
from typing import TYPE_CHECKING, Any

from rics.strings import format_seconds as fmt_sec

from .. import logging as _logging
from .._utils.emit_warning import emit_warning
from ..exceptions import TranslationAbortedWarning
from ..mapping.exceptions import BadOverrideError, MappingError, UnmappedExplicitNamesError, UserMappingError
from ..mapping.matrix import ScoreMatrix
from ..mapping.types import UserOverrideFunction
from ..types import ExplicitNames, IdType, Names, NameToSource, NameType, SourceType, Translatable
from ._names import NamesTask, _UserDefinedNameToSourceMapping

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
        names: ExplicitNames[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        io_kwargs: Mapping[str, Any] | None = None,
        task_id: int | None = None,
    ) -> None:
        super().__init__(
            caller,
            translatable,
            names=names,
            ignore_names=ignore_names,
            override_function=override_function,
            io_kwargs=io_kwargs,
            task_id=task_id,
        )
        # Here, not in BaseTask: extracting names needs only the IO, not sources. Through the Translator, which
        # serializes the first call.
        caller.initialize_sources(task_id=self.task_id)

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
        """Keys of :attr:`~id_translation.offline.TranslationMap.name_to_source`."""
        return list(self.name_to_source)

    def _map(self) -> NameToSource[NameType, SourceType]:
        start = perf_counter()

        values = self.mapper_input_names
        type_name = self.type_name
        names_from_user = self.names_from_user

        if names_from_user is not None and not self.mapper_input_names:
            emit_warning(
                f"Translation aborted; no names to translate in {type_name}{self._format_params()}.",
                TranslationAbortedWarning,
            )
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

        self._check_explicit_sources(sources)
        result: DirectionalMapping[NameType, SourceType]
        result = self.caller.mapper.apply(values, sources, None, self.override_function, task_id=self.task_id)
        name_to_source = result.flatten()
        seconds = perf_counter() - start
        self._check_mapped_sources(name_to_source, sources)

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

        if names_from_user is not None:
            unmapped = sorted(set(names_from_user).difference(name_to_source), key=str)
            if unmapped:
                msg = f"Explicit names {unmapped} could not be mapped to {sources=}{self._format_params()}."
                # Sort of redundant (since we're about to raise), but useful for providing the `task_id` for tracing.
                LOGGER.error(msg, extra={"task_id": self.task_id})
                hints: tuple[str, ...] = ()
                if getattr(self.caller.mapper, "_filters", None):
                    hints = (
                        "Explicit names are subject to Mapper.filter_functions. Pass names={name: source} or use an"
                        " override to bypass them.",
                    )
                raise UnmappedExplicitNamesError(
                    msg,
                    names=names_from_user,
                    unmapped=unmapped,
                    hints=hints,
                )
        elif not name_to_source:
            # We're only concerned with mapping here. The NamesTask manages the no-names-at-all case.
            if self.mapper_input_names:
                emit_warning(
                    f"Translation aborted; none of the derived names {self.mapper_input_names} in the "
                    f"{type_name}-type data could be mapped to available {sources=}{self._format_params()}.",
                    TranslationAbortedWarning,
                )
            return {}

        if result.cardinality.many_right:  # pragma: no cover
            for value, candidates in result.left_to_right.items():
                if len(candidates) > 1:
                    raise MappingError(
                        f"Name-to-source mapping {name_to_source} is ambiguous; {value} -> {candidates}.",
                        hints="Choose a different cardinality such that Mapper.cardinality.many_right is False.",
                    )

        self.add_timing("map", seconds)
        return name_to_source

    def _check_explicit_sources(self, sources: list[SourceType]) -> None:
        if not isinstance(self.override_function, _UserDefinedNameToSourceMapping):
            return
        if self.caller._serves_unlisted_sources():
            return

        explicit = self.override_function.name_to_source
        for name, source in explicit.items():
            if source not in sources:
                msg = f"Explicit names={explicit} maps {name!r} to unknown {source=}. Known sources: {sorted(sources, key=str)}."
                raise UserMappingError(msg, value=name, candidates=sources)

    def _check_mapped_sources(
        self, name_to_source: NameToSource[NameType, SourceType], sources: list[SourceType]
    ) -> None:
        if self.caller._serves_unlisted_sources():
            return

        unknown = {name: source for name, source in name_to_source.items() if source not in sources}
        if not unknown:
            return

        known = sorted(sources, key=str)
        overrides = getattr(self.caller.mapper, "_overrides", None)
        for name, source in unknown.items():
            if isinstance(overrides, dict) and overrides.get(name) == source:
                msg = f"Mapper overrides map {name!r} to unknown {source=}. Known sources: {known}."
                hint = "Fix the override in the Translator's mapping configuration."
                raise BadOverrideError(msg, value=name, candidate=source, candidates=sources, hints=hint)

        name, source = next(iter(unknown.items()))
        raise MappingError(f"The Mapper maps {name!r} to unknown {source=}. Known sources: {known}.")

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
