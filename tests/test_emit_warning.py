"""Tests for `id_translation._utils.emit_warning`.

`add_skip_file_prefix` is public API aimed at adopters of the sibling `id-translation-project` cookiecutter
template (internal libraries built on top of it register their own package directory so that warnings raised
through their wrappers are attributed to the *caller's* code, not the wrapper itself).
"""

from collections.abc import Callable
from typing import Any, cast

import pytest

from id_translation._utils import emit_warning as ew


@pytest.fixture(autouse=True)
def _clean_user_prefixes():
    """`_USER_PREFIXES` is a module-level mutable set; never let a test leak entries into it."""
    before = set(ew._USER_PREFIXES)
    try:
        yield
    finally:
        ew._USER_PREFIXES.clear()
        ew._USER_PREFIXES.update(before)


def _make_function(filename: str, source: str, name: str) -> Callable[..., Any]:
    """Compile `source` as if it lived in a file at `filename`, and return the `name` function it defines.

    This lets us fabricate a call site in an arbitrary "package" without writing real files to disk -- the
    stack-walking logic in `emit_warning`/`_find_stack_level` only ever looks at `frame.f_code.co_filename`.
    """
    code = compile(source, filename, "exec")
    namespace: dict[str, object] = {}
    exec(code, namespace)  # noqa: S102
    return cast("Callable[..., Any]", namespace[name])


def test_add_skip_file_prefix_is_reflected_in_package_dirs():
    prefix = "/fake/adopter/pkg"
    assert prefix not in ew._get_package_dirs()

    ew.add_skip_file_prefix(prefix)

    assert prefix in ew._USER_PREFIXES
    assert prefix in ew._get_package_dirs()


def test_add_skip_file_prefix_affects_emit_warning_attributed_location():
    """Registering a prefix moves the reported warning source past a wrapper living under that prefix.

    Holds on both implementations: `warnings.warn(skip_file_prefixes=...)` on 3.12+, `_find_stack_level` below it.
    """
    fake_dir = "/fake/adopter/pkg"
    fake_file = f"{fake_dir}/wrapper.py"
    call_emit_warning = _make_function(
        fake_file,
        "def call_emit_warning(emit_warning, msg):\n    emit_warning(msg)\n",
        "call_emit_warning",
    )

    # Baseline: the wrapper's own file is not skipped, so it is reported as the warning's source.
    with pytest.warns(UserWarning) as record:
        call_emit_warning(ew.emit_warning, "unregistered")
    assert record.list[-1].filename == fake_file

    # After registering its directory, the wrapper is skipped and attribution moves to *our* call site.
    ew.add_skip_file_prefix(fake_dir)
    with pytest.warns(UserWarning) as record:
        call_emit_warning(ew.emit_warning, "registered")
    assert record.list[-1].filename == __file__


class TestFindStackLevel:
    """`_find_stack_level` is the < 3.12 fallback, but it is importable and testable independent of Python version."""

    def test_direct_call_returns_one(self):
        # Only `_find_stack_level`'s own frame (inside the package) precedes our (non-package) frame.
        assert ew._find_stack_level() == 1

    def test_counts_frames_under_the_package_dir(self):
        # A fabricated caller living "inside" the real package directory should be skipped too, adding one level.
        import id_translation

        assert id_translation.__file__ is not None
        package_dir = str(__import__("pathlib").Path(id_translation.__file__).parent)
        fake_file = f"{package_dir}/fake_internal_caller.py"
        nested = _make_function(
            fake_file,
            "def nested(find_stack_level):\n    return find_stack_level()\n",
            "nested",
        )

        assert nested(ew._find_stack_level) == 2

    def test_counts_frames_under_a_registered_user_prefix(self):
        fake_dir = "/fake/adopter/pkg"
        fake_file = f"{fake_dir}/helper.py"
        nested = _make_function(
            fake_file,
            "def nested(find_stack_level):\n    return find_stack_level()\n",
            "nested",
        )

        # Not registered yet: the helper frame is not skipped, so only `_find_stack_level`'s own frame counts.
        assert nested(ew._find_stack_level) == 1

        ew.add_skip_file_prefix(fake_dir)

        # Now registered: the helper frame is skipped too.
        assert nested(ew._find_stack_level) == 2
