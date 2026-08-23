import re
from datetime import timedelta

import pytest

from id_translation import Translator
from id_translation.toml.meta import BaseMetadata, ConfigMetadata

from .conftest import ROOT
from .test_optional_dependencies import hide_module


@pytest.fixture
def pandas_missing(monkeypatch):
    hide_module(monkeypatch, "pandas")


@pytest.fixture
def metadata():
    return ConfigMetadata.from_toml_paths(str(ROOT / "config.toml"), [], Translator)


class TestDeltaFromString:
    """The ``pandas``-free fallback parser; ``pandas`` is installed in all CI jobs."""

    @pytest.mark.parametrize(
        ("max_age", "expected"),
        [
            ("1s", timedelta(seconds=1)),
            ("30S", timedelta(seconds=30)),
            ("2m", timedelta(minutes=2)),
            ("45M", timedelta(minutes=45)),
            ("3h", timedelta(hours=3)),
            ("12H", timedelta(hours=12)),
            ("4d", timedelta(days=4)),
            ("365D", timedelta(days=365)),
            ("0s", timedelta(0)),
            # Only the first alpha character matters; int() tolerates the trailing space.
            ("90 minutes", timedelta(minutes=90)),
            ("0 days", timedelta(0)),
        ],
    )
    @pytest.mark.usefixtures("pandas_missing")
    def test_fallback(self, max_age, expected):
        assert BaseMetadata._delta_from_string(max_age) == expected

    @pytest.mark.parametrize("max_age", ["", "12", "-1"])
    @pytest.mark.usefixtures("pandas_missing")
    def test_fallback_without_unit(self, max_age):
        with pytest.raises(ValueError, match=re.escape(f"bad {max_age=}")):
            BaseMetadata._delta_from_string(max_age)

    @pytest.mark.parametrize("max_age", ["2W", "1y", "5ns"])
    @pytest.mark.usefixtures("pandas_missing")
    def test_fallback_unknown_unit(self, max_age):
        with pytest.raises(ValueError, match=re.escape(f"bad {max_age=}")):
            BaseMetadata._delta_from_string(max_age)

    def test_pandas_handles_more_units(self):
        # Contrast with test_fallback_unknown_unit; verifies that the fixture really does disable the pandas branch.
        assert BaseMetadata._delta_from_string("2W") == timedelta(days=14)


class TestUseCached:
    def test_no_metadata(self, metadata, tmp_path):
        actual = metadata.use_cached(tmp_path / "does-not-exist.json", None)
        assert actual == (False, "no cache metadata found", "metadata-missing")

    def test_never_expires(self, metadata, tmp_path):
        path = tmp_path / "metadata.json"
        path.write_text(metadata.to_json())
        assert metadata.use_cached(path, None) == (True, "does not expire", None)

    @pytest.mark.parametrize("max_age", [timedelta(hours=10), "10h"])
    def test_not_expired(self, metadata, tmp_path, max_age):
        path = tmp_path / "metadata.json"
        path.write_text(metadata.to_json())

        use_cached, reason, reason_type = metadata.use_cached(path, max_age)
        assert use_cached is True
        assert reason.startswith("expires at ")
        assert reason_type is None

    @pytest.mark.usefixtures("pandas_missing")
    def test_string_max_age_without_pandas(self, metadata, tmp_path):
        path = tmp_path / "metadata.json"
        path.write_text(metadata.to_json())

        use_cached, reason, reason_type = metadata.use_cached(path, "10h")
        assert use_cached is True
        assert reason.startswith("expires at ")
        assert reason_type is None

        use_cached, reason, reason_type = metadata.use_cached(path, "0s")
        assert use_cached is False
        assert reason.startswith("expired at ")
        assert reason_type == "too-old"
