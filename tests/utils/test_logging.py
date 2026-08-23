import logging

import pytest

import id_translation.logging as id_translation_logging
from id_translation.logging import LOGGER, enable_verbose_debug_messages
from id_translation.mapping import Mapper
from id_translation.mapping.exceptions import UnmappedValuesWarning


def test_not_serializable_fails():
    logger = logging.getLogger(f"id_translation.{test_not_serializable_fails.__name__}")
    extra = dict(bad_key={"sets aren't serializable"})

    with pytest.raises(AssertionError, match=logger.name):
        logger.info("This should fail!", extra=extra)


class TestEmitLoggedWarnings:
    def test_true(
        self,
        mapper: Mapper[int, int, None],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("id_translation.logging.EMIT_LOGGED_WARNINGS", True)

        with pytest.warns(UnmappedValuesWarning, match="Could not map {1}"):
            mapper.apply([1], [0])

        self._validate_logs(caplog)

    def test_false(
        self,
        mapper: Mapper[int, int, None],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("id_translation.logging.EMIT_LOGGED_WARNINGS", False)

        mapper.apply([1], [0])

        self._validate_logs(caplog)

    @pytest.fixture
    def mapper(self) -> Mapper[int, int, None]:
        return Mapper[int, int, None]("equality", on_unmapped="warn")

    @classmethod
    def _validate_logs(cls, caplog: pytest.LogCaptureFixture) -> None:
        record = caplog.records[-1]
        assert record.name == "id_translation.mapping.Mapper"
        assert record.levelno == logging.WARNING
        assert record.message.startswith("Could not map {1}")


class TestEnableVerboseDebugMessages:
    """Covers `enable_verbose_debug_messages` config paths not hit by its default-configuration use elsewhere."""

    @pytest.fixture(autouse=True)
    def restore_logging_state(self):
        """Snapshot and restore all global state this function is documented to mutate.

        Used as a safety net in addition to (not instead of) using the function as a context manager: if an
        assertion fails mid-test before `undo()` runs, this still restores everything so later tests don't see
        leaked state.
        """
        level_before = LOGGER.level
        propagate_before = LOGGER.propagate
        handlers_before = list(LOGGER.handlers)
        verbose_before = id_translation_logging.ENABLE_VERBOSE_LOGGING
        emit_before = id_translation_logging.EMIT_LOGGED_WARNINGS

        try:
            yield
        finally:
            LOGGER.setLevel(level_before)
            LOGGER.propagate = propagate_before
            LOGGER.handlers[:] = handlers_before
            id_translation_logging.ENABLE_VERBOSE_LOGGING = verbose_before
            id_translation_logging.EMIT_LOGGED_WARNINGS = emit_before

    def test_level_as_int_in_verbose_range(self):
        # 0 < level < DEBUG(10) => verbose=True, distinct from the level="verbose" string path.
        with enable_verbose_debug_messages(level=5, use_custom_handler=False):
            assert id_translation_logging.ENABLE_VERBOSE_LOGGING is True
            assert LOGGER.level == 5

    def test_level_as_plain_int(self):
        # A regular level int (not in the 0..DEBUG "verbose" range) should not enable verbose mode.
        with enable_verbose_debug_messages(level=logging.INFO, use_custom_handler=False):
            assert id_translation_logging.ENABLE_VERBOSE_LOGGING is False
            assert LOGGER.level == logging.INFO

    def test_auto_custom_handler_used_when_logger_has_no_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(LOGGER, "hasHandlers", lambda: False)

        handlers_before = len(LOGGER.handlers)
        with enable_verbose_debug_messages(use_custom_handler="auto"):
            assert len(LOGGER.handlers) == handlers_before + 1
            assert LOGGER.propagate is False

        # undo() removed the handler and restored propagate.
        assert len(LOGGER.handlers) == handlers_before

    def test_style_minimal(self, capsys: pytest.CaptureFixture[str]) -> None:
        with enable_verbose_debug_messages(level="info", use_custom_handler=True, style="minimal"):
            LOGGER.info("hello minimal")

        assert capsys.readouterr().out.strip() == "hello minimal"

    def test_style_basic(self, capsys: pytest.CaptureFixture[str]) -> None:
        with enable_verbose_debug_messages(level="info", use_custom_handler=True, style="basic"):
            LOGGER.info("hello basic")

        assert capsys.readouterr().out.strip() == "[id_translation:INFO] hello basic"

    def test_undo_removes_handler_only_when_one_was_installed(self):
        handlers_before = list(LOGGER.handlers)
        propagate_before = LOGGER.propagate

        # Regular function call (no `with`): changes persist until undo() is invoked explicitly.
        cm = enable_verbose_debug_messages(use_custom_handler=True, style="minimal")
        assert len(LOGGER.handlers) == len(handlers_before) + 1

        cm.__exit__(None, None, None)

        assert LOGGER.handlers == handlers_before
        assert LOGGER.propagate == propagate_before

    def test_undo_is_noop_for_handlers_when_none_was_installed(self):
        handlers_before = list(LOGGER.handlers)
        propagate_before = LOGGER.propagate

        cm = enable_verbose_debug_messages(use_custom_handler=False)
        cm.__exit__(None, None, None)

        assert LOGGER.handlers == handlers_before
        assert LOGGER.propagate == propagate_before
