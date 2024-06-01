import re

import pytest
from id_translation import Translator, _compat


class TestInplace:
    MESSAGE = r"Translator.translate(): The `inplace` parameter is deprecated; use `copy` instead."
    MATCH = re.escape(MESSAGE)

    def test_true(self, monkeypatch):
        monkeypatch.setattr(_compat, "WARNED", set())

        translatable = [1]

        with pytest.warns(DeprecationWarning, match=self.MATCH):
            actual = Translator().translate(translatable, inplace=True, names="name")  # type: ignore[call-overload]

        assert actual is None
        assert translatable == ["1:name-of-1"]

    def test_false(self, monkeypatch):
        monkeypatch.setattr(_compat, "WARNED", set())

        translatable = [1]

        with pytest.warns(DeprecationWarning, match=self.MATCH):
            actual = Translator().translate(translatable, inplace=False, names="name")  # type: ignore[call-overload]

        assert actual is not None
        assert actual == ["1:name-of-1"]
        assert translatable == [1]

    def test_emit_only_once(self, monkeypatch):
        monkeypatch.setattr(_compat, "WARNED", set())

        with pytest.warns() as w:
            Translator().translate([1], inplace=False, names="name")  # type: ignore[call-overload]
            Translator().translate([1], inplace=False, names="name")  # type: ignore[call-overload]

        n_matches = sum(self.MESSAGE in str(wm.message) for wm in w.list)
        assert n_matches == 1

    def test_new_and_old(self):
        with pytest.raises(TypeError, match="both `inplace` and `copy`"):
            Translator().translate([1], inplace=False, copy=True, names="name")  # type: ignore[call-overload]


class TestMaximalUntranslatedFraction:
    MESSAGE = (
        r"Translator.translate(): The `maximal_untranslated_fraction` parameter is deprecated; use `max_fails` instead."
    )
    MATCH = re.escape(MESSAGE)

    def test(self, monkeypatch):
        monkeypatch.setattr(_compat, "WARNED", set())

        translatable = [1]

        with pytest.warns(DeprecationWarning, match=self.MATCH):
            actual = Translator().translate(translatable, maximal_untranslated_fraction=0, names="name")  # type: ignore[call-overload]

        assert actual is not None
        assert actual == ["1:name-of-1"]
        assert translatable == [1]

    def test_emit_only_once(self, monkeypatch):
        monkeypatch.setattr(_compat, "WARNED", set())

        with pytest.warns() as w:
            Translator().translate([1], maximal_untranslated_fraction=0, names="name")  # type: ignore[call-overload]
            Translator().translate([1], maximal_untranslated_fraction=0, names="name")  # type: ignore[call-overload]

        n_matches = sum(self.MESSAGE in str(wm.message) for wm in w.list)
        assert n_matches == 1

    def test_new_and_old(self):
        with pytest.raises(TypeError, match="both `maximal_untranslated_fraction` and `max_fails`"):
            Translator().translate([1], maximal_untranslated_fraction=0, max_fails=0, names="name")  # type: ignore[call-overload]
