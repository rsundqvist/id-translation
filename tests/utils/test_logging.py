import logging

import pytest

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
