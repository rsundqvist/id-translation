"""Supporting functions for implementations."""
from typing import Collection, List

from ..types import IdType, SourceType
from .types import FetchInstruction as _FetchInstruction


def select_placeholders(instr: _FetchInstruction[SourceType, IdType], known_placeholders: Collection[str]) -> List[str]:
    """Select from a subset of known placeholders.

    Args:
        instr: Instruction object with placeholders.
        known_placeholders: A collection of known placeholders.

    Returns:
        As many known placeholders from `instr` as possible.
    """
    return list(
        known_placeholders if instr.all_placeholders else filter(known_placeholders.__contains__, instr.placeholders)
    )
