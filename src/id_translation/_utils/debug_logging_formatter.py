"""Handler which pretty-prints (color) logger output to stdout.

Used by :func:`.enable_verbose_debug_messages`.
"""

import logging
from datetime import datetime
from enum import StrEnum
from random import shuffle
from re import Match, compile
from threading import Lock
from types import TracebackType
from typing import TypeAlias

ExcInfo: TypeAlias = tuple[type[BaseException], BaseException, TracebackType | None] | tuple[None, None, None]


class Color(StrEnum):
    """Colors used for highlighting."""

    reset = "\033[0m"
    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    blue = "\033[34m"
    magenta = "\033[35m"
    cyan = "\033[36m"
    gray = "\033[37m"
    orange = "\033[93m"


LEVEL_TO_COLOR: dict[int, Color] = {
    logging.DEBUG: Color.magenta,
    logging.INFO: Color.green,
    logging.WARNING: Color.orange,
    logging.ERROR: Color.red,
}

PATTERN_TO_COLOR: tuple[tuple[str, Color], ...] = (
    # Strings
    (r"'.*?'", Color.green),
    (r'".*?"', Color.green),
    # Numerics
    (r"(?:0x)[abcdef\d]+", Color.magenta),  # Hex string
    (r"(?:0b)[01]+", Color.magenta),  # Bin string
    (r"[+-]?\d+(?:.\d+)?", Color.magenta),  # Numbers; includes things like 3.2 or 3x2.
    (r"[+-]?(?:NaN|inf|∞)", Color.magenta),  # Infinity/NaN
    # Misc
    ("None|True|False", Color.gray),  # Constants
    (r"\w+=", Color.red),  # Keyword argument
)


class DebugLoggingFormatter(logging.Formatter):
    """Helper class used to display debug out.

    Args:
        less: If ``True``, abbreviate output.
        indent_style: Indentation prefix. Empty=disabled.
    """

    def __init__(
        self,
        *,
        less: bool = False,
        indent_style: str = "  ",
    ) -> None:
        super().__init__()

        self._less = less

        pattern_to_color = PATTERN_TO_COLOR
        if less:
            pattern_to_color = tuple((p, c) for p, c in pattern_to_color if c == Color.magenta)
        self._pattern_to_color = pattern_to_color
        self._pattern = compile("|".join(f"({pattern})" for i, (pattern, _) in enumerate(pattern_to_color)))

        self._indent_style = indent_style
        self._indent: dict[str, int] = {}

        self._task_id_styles: list[tuple[str, Color]] = [
            ("🦋", Color.yellow),
            ("🍏", Color.green),
            ("🫚", Color.orange),
            ("🎷", Color.yellow),
            ("🎃", Color.orange),
            ("🦄", Color.magenta),
            ("🫎", Color.gray),
            ("🪻", Color.magenta),
            ("🐳", Color.blue),
        ]

        shuffle(self._task_id_styles)
        self._task_id_style: dict[int, tuple[str, Color]] = {}

        self._lock = Lock()

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        """Emit pretty-printed log record."""
        task_id = self._task_id(record)
        created = self._created(record)
        indentation = self._indentation(record)
        level = self._level(record)
        logger = self._logger(record)
        message = self._message(record)
        parts = [task_id, created, indentation, level, logger, message]

        return " ".join(filter(bool, parts))

    def formatException(self, ei: ExcInfo) -> str:  # noqa: N802
        """Emit exception with highlighting."""
        s = super().formatException(ei)
        s = self._highlight(s)
        return s

    def _indentation(self, record: logging.LogRecord) -> str:
        task_id = getattr(record, "task_id", None)
        if task_id is None or self._less or self._indent_style == "":
            return ""

        stage = ""
        if event_key := getattr(record, "event_key", ""):
            stage = event_key.rpartition(":")[2]

        self._indent.setdefault(task_id, 0)  # Just in case; enter should come first.

        if stage == "exit":
            self._indent[task_id] -= 1

        indentation = self._indent_style * self._indent[task_id]

        if stage == "enter":
            self._indent[task_id] += 1

        return indentation

    def _task_id(self, record: logging.LogRecord) -> str:
        task_id = getattr(record, "task_id", None)
        if task_id is None:
            return "[-- ------]"

        with self._lock:
            symbol, color = self._select_task_id_style(task_id)

        return f"[{color}{symbol} {hex(task_id):0<6}{Color.reset}]"

    def _select_task_id_style(self, task_id: int) -> tuple[str, Color]:
        if task_id in self._task_id_style:
            return self._task_id_style[task_id]

        index = len(self._task_id_style) % len(self._task_id_styles)
        symbol = self._task_id_styles[index]
        self._task_id_style[task_id] = symbol
        return symbol

    def _created(self, record: logging.LogRecord) -> str:
        date = "" if self._less else f"{Color.gray}%d %b{Color.reset} "
        time = f"{Color.orange}%H:%M:%S{Color.yellow}.%f{Color.reset}"
        created = datetime.fromtimestamp(record.created)
        return "[" + created.strftime(f"{date}{time}") + "]"

    def _level(self, record: logging.LogRecord) -> str:
        if self._less:
            return f"[{record.levelname}]"
        color = LEVEL_TO_COLOR.get(record.levelno, Color.reset)
        return f"[{color}{record.levelname}{Color.reset}]"

    @classmethod
    def _logger(cls, record: logging.LogRecord) -> str:
        if event_key := getattr(record, "event_key", ""):
            meth, _, stage = event_key.rpartition(":")
            stage = {"enter": "🚀", "exit": "✅"}.get(stage, stage)
            name = f"{stage} {Color.blue}{meth}{Color.reset}"
        else:
            name = Color.gray + record.name + Color.reset

        return f"[{name}]"

    def _message(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        return self._highlight(message)

    def _highlight(self, s: str) -> str:
        return self._pattern.sub(self._highlight_match, s)

    def _highlight_match(self, match: Match[str]) -> str:
        assert match.lastindex is not None  # noqa: S101
        color = self._pattern_to_color[match.lastindex - 1][1]
        return color + match.group(0) + color.reset
