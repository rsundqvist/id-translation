import logging
import warnings
from collections import defaultdict
from collections.abc import Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any, get_args

from numpy import isnan, unique
from rics.misc import tname
from rics.performance import format_seconds

from .. import _uuid_utils
from ..exceptions import TooManyFailedTranslationsError
from ..mapping.types import UserOverrideFunction
from ..offline import Format, TranslationMap
from ..settings import logging as settings
from ..types import IdType, IdTypes, Names, NameToSource, NameType, NameTypes, SourceType, Translatable
from ..utils.logging import cast_unsafe
from ._map import MappingTask

LOGGER = logging.getLogger("id_translation.Translator.translate")

NUM_SAMPLE_IDS = 10

if TYPE_CHECKING:
    from .._translator import Translator


class TranslationTask(MappingTask[NameType, SourceType, IdType]):
    """Ephemeral class for performing a single translation task on a `translatable`."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
        fmt: Format,
        names: NameTypes[NameType] | NameToSource[NameType, SourceType] | None = None,
        *,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] | None = None,
        inplace: bool = False,
        maximal_untranslated_fraction: float = 1.0,
        reverse: bool = False,
        enable_uuid_heuristics: bool = False,
    ) -> None:
        super().__init__(
            caller,
            translatable,
            names,
            ignore_names=ignore_names,
            override_function=override_function,
        )

        if not (0.0 <= maximal_untranslated_fraction <= 1):
            raise ValueError(f"Argument {maximal_untranslated_fraction=} is not a valid fraction")

        self.fmt = fmt
        self.inplace = inplace
        self.maximal_untranslated_fraction = maximal_untranslated_fraction
        self.reverse = reverse
        self.parent: Translatable[NameType, IdType] | None = None

        self.enable_uuid_heuristics = enable_uuid_heuristics

        self.key_event_level = settings.TRANSLATE_ONLINE if self.caller.online else settings.TRANSLATE_OFFLINE

        self._names_without_ids: set[NameType] = set()

    @property
    def io_names(self) -> list[NameType]:
        """Names for which IDs should be extracted from the `translatable`."""
        # Preserve input order for names, if given. These names may be repeated.
        if self.names_from_user is None:
            names = self.names_to_translate
        else:
            names = self.names_from_user

        return [n for n in names if n not in self._names_without_ids]

    def extract_ids(self) -> dict[SourceType, set[IdType]]:
        """Extract IDs to fetch from the translatable."""
        name_to_source = self.name_to_source
        source_to_ids: dict[SourceType, set[IdType]] = defaultdict(set)

        float_names: list[NameType] = []
        num_coerced = 0
        ids: Sequence[IdType]
        for name, ids in self._extract_ids().items():
            if len(ids) == 0:
                continue

            if isinstance(ids[0], float):
                float_names.append(name)
                # Float IDs aren't officially supported, but is common when using Pandas since int types cannot be NaN.
                # This is sometimes a problem for the built-in set (see https://github.com/numpy/numpy/issues/9358), and
                # for several database drivers.
                arr = unique(ids)
                keep_mask = ~isnan(arr)
                num_coerced += keep_mask.sum()  # Somewhat inaccurate; includes repeat IDs from other names
                source_to_ids[name_to_source[name]].update(arr[keep_mask].astype(int, copy=False))
            else:
                if self.enable_uuid_heuristics:
                    ids = _uuid_utils.try_cast_many(ids)  # noqa: PLW2901

                source_to_ids[name_to_source[name]].update(ids)

        if num_coerced > 100:  # pragma: no cover  # noqa: PLR2004
            types = f"({', '.join(t.__name__ for t in get_args(IdTypes))})"
            warnings.warn(
                f"To ensure proper fetcher operation, {num_coerced} float-type IDs have been coerced to int. "
                f"Enforcing supported data types {types} for IDs in your {self.type_name}-data may improve performance."
                f" Affected names ({len(float_names)}): {float_names}.",
                stacklevel=3,
            )
        return source_to_ids

    def log_key_event_enter(self) -> None:
        """Emits the ``TRANSLATOR:TRANSLATE.ENTER`` message."""
        if not LOGGER.isEnabledFor(self.key_event_level.enter):
            return

        type_name = self.type_name
        names = self.names_from_user
        ignore_names = self.ignore_names

        name_info = f"Derive based on type={type_name}" if names is None else repr(names)
        if ignore_names is not None:
            name_info += f", excluding those given by {ignore_names=}"

        LOGGER.log(
            level=self.key_event_level.enter,
            msg=f"Begin translation of {type_name}-type data. Names to translate: {name_info}.",
            extra=dict(
                task_id=self.task_id,
                event_key="TRANSLATOR.TRANSLATE",
                event_stage="ENTER",
                event_title="TRANSLATOR.TRANSLATE.ENTER",
                sources=self.caller.sources,
                online=self.caller.online,
                # Task-specific
                translatable_type=self.full_type_name,
                names=names,
                ignore_names=tname(ignore_names, prefix_classname=True) if callable(ignore_names) else ignore_names,
                inplace=self.inplace,
                reverse=self.reverse,
            ),
        )

    def log_key_event_exit(self) -> None:
        """Emits the ``TRANSLATOR:TRANSLATE.EXIT`` key event message."""
        if not LOGGER.isEnabledFor(self.key_event_level.exit):
            return

        inplace = self.inplace
        n2s = self.name_to_source
        execution_time = perf_counter() - self._start

        LOGGER.log(
            level=self.key_event_level.exit,
            msg=(
                f"Finished translation of {len(n2s)} names in {self.type_name}-type data in "
                f"{format_seconds(execution_time)}, using name-to-source mapping: {n2s}."
            ),
            extra=dict(
                task_id=self.task_id,
                event_key="TRANSLATOR.TRANSLATE",
                event_stage="EXIT",
                event_title="TRANSLATOR.TRANSLATE.EXIT",
                execution_time=execution_time,
                # Task-specific
                translatable_type=self.full_type_name,
                inplace=inplace,
                reverse=self.reverse,
                name_to_source=n2s,
            ),
        )

    def insert(
        self, translation_map: TranslationMap[NameType, SourceType, IdType]
    ) -> Translatable[NameType, str] | None:
        """Insert translated IDs into the `translatable`, based on data retrieved by the fetcher."""
        inplace = self.inplace

        translation_map.reverse_mode = self.reverse
        try:
            result = self.io.insert(
                self.translatable,
                names=self.io_names,
                tmap=translation_map,
                copy=not inplace,
            )
        finally:
            translation_map.reverse_mode = False

        return None if inplace else result

    def verify(self, tmap: TranslationMap[NameType, SourceType, IdType]) -> None:
        """Verify translations.

        Performs translation with pre-defined formats, counting the number of IDs which are (and aren't) known to the
        translation map.
        """
        if not (self.maximal_untranslated_fraction < 1.0 or LOGGER.isEnabledFor(logging.DEBUG)):
            return

        name_to_ids = self._name_to_ids_in_order()
        translations = tmap.to_translations()

        for name, ids in name_to_ids.items():
            source = tmap.name_to_source[name]
            known = translations[source].real
            if self.reverse != tmap.reverse_mode:
                known = set(known.values())  # type: ignore[assignment]

            is_missing = [idx not in known for idx in ids]
            n_untranslated = sum(is_missing)
            if n_untranslated == 0:
                continue
            n_total = len(ids)
            f_untranslated = n_untranslated / n_total

            sample_ids = self._get_untranslated_ids(name_to_ids[name], is_missing_mask=is_missing)

            extra = {"name_of_ids": name, "source": source, "sample_ids": cast_unsafe(sample_ids)}
            message = (
                f"Failed to translate {n_untranslated}/{n_total} ({f_untranslated:.1%}{{reason}}) of IDs "
                f"for {name=} using source={source!r}. Sample IDs: {sample_ids}."
            )

            if f_untranslated > self.maximal_untranslated_fraction:
                message = message.format(
                    reason=f" > maximal_untranslated_fraction={self.maximal_untranslated_fraction:.1%}"
                )
                LOGGER.error(message, extra=extra)
                raise TooManyFailedTranslationsError(message)
            else:
                message = message.format(reason=", above limit; DEBUG logging is enabled")
                LOGGER.debug(message, extra=extra)

    def _name_to_ids_in_order(self) -> dict[NameType, Sequence[Any]]:
        name_to_ids: dict[NameType, Sequence[Any]] = self._extract_ids()
        if self.enable_uuid_heuristics:
            name_to_ids = {name: _uuid_utils.try_cast_many(name_to_ids[name]) for name in name_to_ids}
        return name_to_ids

    def _extract_ids(self) -> dict[NameType, Sequence[IdType]]:
        name_to_ids: dict[NameType, Sequence[IdType]] = self.io.extract(self.translatable, self.io_names)

        name_to_ids = {name: ids for name, ids in name_to_ids.items() if len(ids) > 0}
        if not self._names_without_ids:
            self._names_without_ids = set(self.io_names).difference(name_to_ids)
        return name_to_ids

    @staticmethod
    def _get_untranslated_ids(ids: Sequence[IdType], *, is_missing_mask: Sequence[bool]) -> list[IdType]:
        seen = set()
        retval = []

        for idx, is_missing in zip(ids, is_missing_mask, strict=True):
            if not is_missing or idx in seen:
                continue

            seen.add(idx)
            retval.append(idx)
            if len(retval) == NUM_SAMPLE_IDS:
                break

        return retval
