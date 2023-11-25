import logging
import warnings
from collections import defaultdict
from time import perf_counter
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Union

from numpy import isnan, unique
from rics.misc import tname
from rics.performance import format_seconds

from .. import _uuid_utils
from ..dio._dict import DictIO
from ..exceptions import TooManyFailedTranslationsError
from ..mapping.types import UserOverrideFunction
from ..offline import Format, TranslationMap
from ..settings import logging as settings
from ..types import IdType, Names, NameToSource, NameType, NameTypes, SourceType, Translatable
from ..utils.logging import cast_unsafe
from ._map import MappingTask

LOGGER = logging.getLogger("id_translation.Translator.translate")

NUM_SAMPLE_IDS = 10

if TYPE_CHECKING:
    from .._translator import Translator

LOGGER = logging.getLogger("id_translation.Translator.translate")


class TranslationTask(MappingTask[NameType, SourceType, IdType]):
    """Ephemeral class for performing a single translation task on a `translatable`."""

    def __init__(
        self,
        caller: "Translator[NameType, SourceType, IdType]",
        translatable: Translatable[NameType, IdType],
        fmt: Format,
        names: Union[NameTypes[NameType], NameToSource[NameType, SourceType]] = None,
        *,
        ignore_names: Names[NameType] = None,
        override_function: UserOverrideFunction[NameType, SourceType, None] = None,
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

        if not (0.0 <= maximal_untranslated_fraction <= 1):  # pragma: no cover
            raise ValueError(f"Argument {maximal_untranslated_fraction=} is not a valid fraction")

        self.fmt = fmt
        self.inplace = inplace
        self.maximal_untranslated_fraction = maximal_untranslated_fraction
        self.reverse = reverse
        self.parent: Optional[Translatable[NameType, IdType]] = None

        self.enable_uuid_heuristics = enable_uuid_heuristics

        self.key_event_level = settings.TRANSLATE_ONLINE if self.caller.online else settings.TRANSLATE_OFFLINE

    @property
    def io_names(self) -> List[NameType]:
        """Names for which IDs should be extracted from the `translatable`."""
        # Preserve input order for names, if given. These names may be repeated.
        return self.names_to_translate if self.names_from_user is None else self.names_from_user

    def extract_ids(self) -> Dict[SourceType, Set[IdType]]:
        """Extract IDs to fetch from the translatable."""
        name_to_source = self.name_to_source
        source_to_ids: Dict[SourceType, Set[IdType]] = defaultdict(set)

        float_names: List[NameType] = []
        num_coerced = 0
        ids: Sequence[IdType]
        for name, ids in self.io.extract(self.translatable, self.io_names).items():
            if len(ids) == 0:
                continue

            if isinstance(ids[0], float):
                float_names.append(name)
                # Float IDs aren't officially supported, but is common when using Pandas since int types cannot be NaN.
                # This is sometimes a problem for the built-in set (see https://github.com/numpy/numpy/issues/9358), and
                # for several database drivers.
                arr = unique(ids)  # type: ignore[var-annotated]
                keep_mask = ~isnan(arr)
                num_coerced += keep_mask.sum()  # Somewhat inaccurate; includes repeat IDs from other names
                source_to_ids[name_to_source[name]].update(arr[keep_mask].astype(int, copy=False))
            else:
                if self.enable_uuid_heuristics:
                    ids = _uuid_utils.try_cast_many(ids)

                source_to_ids[name_to_source[name]].update(ids)

        if num_coerced > 100:  # pragma: no cover
            warnings.warn(
                f"To ensure proper fetcher operation, {num_coerced} float-type IDs have been coerced to integers. "
                f"Enforcing supported data types for IDs (str and int) in your {self.type_name!r}-data may improve "
                f"performance. Affected names ({len(float_names)}): {float_names}.",
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
    ) -> Optional[Translatable[NameType, str]]:
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

    def verify(self, translation_map: TranslationMap[NameType, SourceType, IdType]) -> None:
        """Verify translations.

        Performs translation with pre-defined formats, counting the number of IDs which are (and aren't) known to the
        translation map.
        """
        if not (LOGGER.isEnabledFor(logging.DEBUG) or self.maximal_untranslated_fraction < 1.0):
            pass

        name_to_mask: Dict[NameType, Sequence[Any]] = self.io.extract(self.translatable, self.io_names)

        if self.enable_uuid_heuristics:
            for name in name_to_mask:
                name_to_mask[name] = _uuid_utils.try_cast_many(name_to_mask[name])

        fmt, default_fmt = translation_map.fmt, translation_map.default_fmt
        try:
            translation_map.fmt = ""  # type: ignore[assignment]
            translation_map.default_fmt = None
            DictIO.insert(
                name_to_mask,
                names=self.io_names,
                tmap=translation_map,
                copy=False,
            )
        finally:
            translation_map.fmt, translation_map.default_fmt = fmt, default_fmt

        name_to_ids: Optional[Dict[NameType, Sequence[IdType]]] = None

        def get_ids(n: NameType) -> Sequence[Any]:
            nonlocal name_to_ids
            if name_to_ids is None:
                # It would be nice to pass just names=[n], but semantics may change depending
                # on the number of names given. Is there a way to do this safely?
                name_to_ids = self.io.extract(self.translatable, names=self.io_names)
                if self.enable_uuid_heuristics:
                    for n in name_to_ids:
                        name_to_ids[n] = _uuid_utils.try_cast_many(name_to_ids[n])
            return name_to_ids[n]

        for name, mask in name_to_mask.items():
            n_untranslated, n_total = sum(t is None for t in mask), len(mask)
            if n_untranslated == 0:
                continue
            f_untranslated = n_untranslated / n_total

            sample_ids = self._get_untranslated_ids(get_ids(name), mask=mask)

            extra = {
                "name_of_ids": name,
                "source": translation_map.name_to_source[name],
                "sample_ids": cast_unsafe(sample_ids),
            }

            message = (
                f"Failed to translate {n_untranslated}/{n_total} ({f_untranslated:.1%}{{reason}}) of IDs "
                f"for {name=} using source={translation_map.name_to_source[name]!r}. Sample IDs: {sample_ids}."
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

    @staticmethod
    def _get_untranslated_ids(
        ids: Sequence[IdType],
        *,
        mask: Sequence[Optional[str]],
    ) -> List[IdType]:
        seen = set()
        retval = []

        for i, idx in enumerate(ids):
            if idx in seen:
                continue

            if mask[i] is None:
                seen.add(idx)
                retval.append(idx)
                if len(retval) == NUM_SAMPLE_IDS:
                    break

        return retval
