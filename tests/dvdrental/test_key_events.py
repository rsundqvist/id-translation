import logging
from dataclasses import dataclass
from typing import Literal, cast, get_args

import pytest
from id_translation import Translator

from .conftest import DIALECTS, LINUX_ONLY, get_df, setup_for_dialect

KindType = Literal["translate", "map", "fetch"]
CACHE: dict[str, list["KeyEventDetails"]] = {}

pytestmark = [pytest.mark.parametrize("dialect", DIALECTS), LINUX_ONLY]


@dataclass(frozen=True)
class KeyEventDetails:
    task_id: int
    key: tuple[str, str]
    is_enter: bool
    kind: KindType
    record: logging.LogRecord
    index: int = -1

    @staticmethod
    def get_kind(event_key: str) -> KindType:
        for kind in get_args(KindType):
            if kind in event_key.lower():
                return kind  # type: ignore[no-any-return]
        raise ValueError(f"Bad {event_key=}.")

    def __str__(self) -> str:
        return "<dummy>" if self.record is None else self.record.message

    def __post_init__(self) -> None:
        assert len(self.key) == 2


class TestKeyEvents:
    def test_translate_exit(self, dialect, caplog):
        ked = get_key_event_details(dialect, caplog)[-1]
        assert ked.key == ("TRANSLATOR", "TRANSLATE")
        assert ked.is_enter is False
        assert ked.kind == "translate"
        assert ked.record is not None
        assert ked.record.message.startswith("Finished translation of 4 names in 'DataFrame'-type data in")
        assert ked.record.levelno == logging.INFO

    def test_log_levels(self, dialect, caplog):
        for ked in get_key_event_details(dialect, caplog)[:-1]:
            assert ked.record.levelno == logging.DEBUG, ked

    def test_no_nested_enter_on_same_key(self, dialect, caplog):
        active_keys: set[tuple[str, str]] = set()

        for i, ked in enumerate(get_key_event_details(dialect, caplog)):
            if ked.is_enter:
                assert ked.key not in active_keys, f"{i=}: nested entry on {ked}."
                active_keys.add(ked.key)
            else:
                assert ked.key in active_keys, f"{i=}: exit without entry on {ked}."
                active_keys.remove(ked.key)

    def test_task_id(self, dialect, caplog):
        key_event_details = get_key_event_details(dialect, caplog)
        assert hasattr(key_event_details[-1].record, "task_id")
        expected_task_id = key_event_details[-1].record.task_id

        wrong_id = []
        missing_id = []

        for ked in key_event_details:
            if hasattr(ked.record, "task_id"):
                task_id = ked.record.task_id
                if task_id != expected_task_id:
                    wrong_id.append(f"{ked.index}, {task_id=}: {ked}")
            else:
                missing_id.append(f"{ked.index}: {ked}")

        assert len(wrong_id) == 0, f"{len(wrong_id)=}:" + "\n" + "\n".join(wrong_id)
        assert len(missing_id) == 0, f"{len(missing_id)=}:" + "\n" + "\n".join(missing_id)


def get_key_event_details(dialect, caplog):
    if dialect in CACHE:
        return CACHE[dialect]

    # Called for every function. Would be nice if this could be per parameter.
    translator: Translator[str, str, int] = Translator.from_config(*setup_for_dialect(dialect))
    translator.translate(get_df(dialect), copy=False)

    ret = []
    for i, r in enumerate(caplog.records):
        if not hasattr(r, "event_key"):
            continue

        assert r.event_key.upper() == r.event_key
        assert r.event_stage.upper() == r.event_stage
        assert r.event_title.upper() == r.event_title
        assert r.event_title == f"{r.event_key}.{r.event_stage}"

        ret.append(
            KeyEventDetails(
                task_id=r.task_id,
                key=cast(tuple[str, str], tuple(r.event_key.split("."))),
                is_enter=r.event_stage == "ENTER",
                kind=KeyEventDetails.get_kind(r.event_key),
                index=i,
                record=r,
            )
        )
    CACHE[dialect] = ret
    return ret
