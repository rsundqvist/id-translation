import re
from pathlib import Path

import pytest

from id_translation.dio import _repository
from id_translation.dio.exceptions import DataStructureIOError
from id_translation.dio.integration.pandas import PandasIO

TRANSLATION_IO = Path(__file__).parents[2] / "docs" / "documentation" / "translation-io.rst"


def _anchors() -> set[str]:
    rst = TRANSLATION_IO.read_text()
    lines = rst.splitlines()
    headings = {
        lines[i - 1].strip().lower().replace(" ", "-")
        for i, line in enumerate(lines)
        if i and len(set(line)) == 1 and line[0] in "-="
    }
    labels = set(re.findall(r"^\.\. _([\w-]+):$", rst, flags=re.MULTILINE))
    return headings | labels


def _priority_error(monkeypatch: pytest.MonkeyPatch) -> DataStructureIOError:
    repository = _repository.Repository(ios=[PandasIO], load_integrations=False, load_defaults=False)
    monkeypatch.setattr(PandasIO, "priority", PandasIO.priority + 1)
    with pytest.raises(DataStructureIOError) as exc_info:
        repository.resolve_io(1)
    return exc_info.value


@pytest.mark.parametrize(
    "make",
    [
        lambda _: DataStructureIOError("default"),
        lambda _: _repository.reentry_error(),
        _priority_error,
    ],
    ids=["default", "reentry", "priority"],
)
def test_hint_links_to_an_existing_section(monkeypatch, make):
    url = make(monkeypatch).__notes__[0].removeprefix("Hint: ")
    page, anchor = url.rsplit("/", 1)[-1].split("#")

    assert page == TRANSLATION_IO.with_suffix(".html").name
    assert anchor in _anchors()
