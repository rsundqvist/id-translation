import logging
import warnings
from typing import TYPE_CHECKING

from rics.collections.misc import as_list

from ..mapping.exceptions import MappingWarning

if TYPE_CHECKING:
    from .._translator import Translator

from ..exceptions import MissingNamesError
from ..mapping.types import UserOverrideFunction
from ..types import IdType, Names, NameToSource, NameType, NameTypes, SourceType, Translatable
from ._base_task import BaseTask

LOGGER = logging.getLogger("id_translation.Translator.names")


class NamesTask(BaseTask[NameType, SourceType, IdType]):
    """Internal type; not part of the public API."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        ignore_names: Names[NameType] | None = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
    ) -> None:
        super().__init__(caller, translatable)

        if not (names is None or ignore_names is None):
            raise ValueError(
                f"Required {names=} cannot be used with {ignore_names=}."
                f"\nHint: Set names=None to use automatic name extraction with user-defined ignored names."
            )

        names, override_function = _handle_input_names(names, override_function)

        # Explicit, user-given names
        self.names_from_user: list[NameType] | None = None if names is None else as_list(names)

        # Names to exclude. May not be combined with explicit names (verified above).
        self.ignore_names: Names[NameType] | None = None
        if ignore_names is not None:
            self.ignore_names = ignore_names if callable(ignore_names) else as_list(ignore_names)

        # A callable (NameType) -> bool, if given
        self.override_function = override_function

        # Task outputs
        self._need_name_extraction: bool = True
        self._extracted_names: list[NameType] | None = None
        self._mapper_input_names: list[NameType] | None = None

    @property
    def extracted_names(self) -> list[NameType]:
        """Names extracted from `translatable`, based on ``type(translatable)``."""
        if self._extracted_names is not None:
            return self._extracted_names

        if not self._need_name_extraction:
            # Users should never see this. If they do, something went (very) wrong internally.
            raise MissingNamesError(
                "You're not supposed to see this. Please report this issue at:\n"
                "https://github.com/rsundqvist/id-translation/issues/new"
            )
        self._need_name_extraction = False

        names: list[NameType] | None = self.io.names(self.translatable)
        if names is None:
            raise MissingNamesError(
                f"Failed to derive names for {self.type_name}-type data."
                "\nHint: Use the 'names'-argument to specify names to translate."
            )
        self._extracted_names = names
        return self._extracted_names

    @property
    def mapper_input_names(self) -> list[NameType]:
        """Names that should be mapped to sources."""
        if self._mapper_input_names is None:
            self._mapper_input_names = self._filter_names()
        return self._mapper_input_names

    def _filter_names(self) -> list[NameType]:
        names = self.names_from_user

        if names is not None:
            return as_list(names)

        ignore_names = self.ignore_names  # May not be combined with explicit names; checked earlier.
        names = self.extracted_names
        if LOGGER.isEnabledFor(logging.DEBUG):
            LOGGER.debug(f"Name extraction complete. Found {names=} for {self.type_name}-type data.")

        if names and ignore_names is not None:
            predicate = ignore_names if callable(ignore_names) else set(as_list(ignore_names)).__contains__
            names = [name for name in names if not predicate(name)]

            if not names:
                warnings.warn(
                    f"No names left to translate. All derived names={self.extracted_names} in the {self.type_name}-type"
                    f" data where removed by ignore_names={ignore_names}.",
                    category=MappingWarning,
                    stacklevel=3,
                )

        return names


def _handle_input_names(
    names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None,
    override_function: UserOverrideFunction[NameType, SourceType, None] | None,
) -> tuple[list[NameType] | None, UserOverrideFunction[NameType, SourceType, None] | None]:
    if names is None:
        return None, override_function

    if isinstance(names, dict):
        if override_function is not None:
            raise ValueError(f"Dict-type {names=} cannot be combined with {override_function=}.")

        override_function = _UserDefinedNameToSourceMapping(dict(names))

    return as_list(names), override_function


class _UserDefinedNameToSourceMapping:
    def __init__(self, name_to_source: NameToSource[NameType, SourceType]) -> None:
        for name, source in name_to_source.items():
            if source is None:
                raise ValueError(
                    f"Bad name-to-source mapping: {name!r} -> {source!r}."
                    f"\nHint: Remove None-values from names={name_to_source}."
                )
        self._name_to_source = name_to_source

    def __call__(self, name: NameType, _sources: set[SourceType], _context: None) -> SourceType | None:
        return self._name_to_source.get(name)

    def __repr__(self) -> str:
        return f"UserArgument(names={self._name_to_source})"
