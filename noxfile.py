"""Nox sessions."""

import os
import platform
import re

import nox
from nox.sessions import Session

nox.options.default_venv_backend = "uv"
nox.options.sessions = ["tests", "mypy"]
python_versions = ["3.11", "3.12", "3.13", "3.14"]


def install(session: Session) -> None:
    """Install the project using uv."""
    _assert_session_interpreter(session)  # Before an expensive doomed sync.

    # One sync: it installs the project editable, and a `uv pip install .` on top is undone by the next `uv run`.
    session.run_install(
        "uv",
        "sync",
        f"--python={session.virtualenv.location}",
        "--all-extras",
        # As CI syncs. Note that `uv run nox` bootstraps the *outer* .venv unlocked first, so drift is only
        # refused when the caller pre-synced as CI does, or set UV_LOCKED=1.
        "--locked",
        external=True,
        env=_uv_env(session),
    )

    _assert_session_interpreter(session, post_sync=True)


def run_invoke(session: Session, *args: str, env: dict[str, str] | None = None) -> None:
    """Run an ``inv`` task with the session venv as uv's project environment.

    Without it, the inner ``uv run`` calls in ``tasks.py`` default to ``.venv`` and warn about the ``VIRTUAL_ENV``
    that nox set to the session venv.
    """
    session.run("inv", *args, env={**_uv_env(session), **(env or {})})


@nox.session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite."""
    install(session)
    try:
        run_invoke(
            session,
            "tests",
            env={
                # An explicit env= beats os.environ in nox, so the default must not shadow an outer COVERAGE_FILE.
                "COVERAGE_FILE": os.environ.get("COVERAGE_FILE", f".coverage.{platform.system()}.{session.python}"),
            },
        )
    finally:
        if session.interactive:
            session.notify("coverage")


@nox.session(python="3.14t")
def free_threading(session: Session) -> None:
    """Run the free-threaded (GIL-less) race tests on a Py_GIL_DISABLED build.

    Not a default session: requires a free-threaded interpreter (``3.14t``). Installs a minimal dependency set
    rather than the ``--all-extras`` sync of ``tests``, as extras like ``pymssql`` have no free-threaded wheels.
    """
    _assert_session_interpreter(session)
    session.install(".[fetching]", "pytest")
    _assert_session_interpreter(session, post_sync=True)
    session.run("pytest", "tests/test_free_threading.py", env={"PYTHON_GIL": "0"})


@nox.session
def coverage(session: Session) -> None:
    """Produce the coverage report."""
    install(session)
    args = session.posargs if session.posargs and len(session._runner.manifest) == 1 else []
    run_invoke(session, "coverage", *args)


@nox.session(python=python_versions)
def mypy(session: Session) -> None:
    """Type-check using mypy."""
    install(session)
    run_invoke(session, "mypy")


@nox.session(python="3.11")
def audit(session: Session) -> None:
    """Audit dependencies for known vulnerabilities."""
    install(session)
    run_invoke(session, "audit")


def _uv_env(session: Session) -> dict[str, str]:
    """Point uv at the session venv *and* its interpreter.

    ``UV_PROJECT_ENVIRONMENT`` alone is not enough: uv keeps the path but re-resolves from ``.python-version``,
    collapsing the matrix onto one version. The inner ``uv run`` in tasks.py re-resolves the same way.
    """
    location = session.virtualenv.location
    # The venv directory, not <venv>/bin/python -- Windows keeps the interpreter in Scripts\\.
    return {"UV_PROJECT_ENVIRONMENT": location, "UV_PYTHON": location}


def _assert_session_interpreter(session: Session, *, post_sync: bool = False) -> None:
    """Fail unless the session venv is the interpreter its name promises.

    Checked on both sides of the sync: ``nox -r`` reuses whatever is on disk, and the sync itself may re-resolve
    (uv reads a plain ``3.14`` as ``+freethreaded`` when that is the only managed 3.14). The runners differ because
    ``--install-only`` skips ``run`` and ``--no-install`` skips ``run_install``.
    """
    probe = (
        "import sys, sysconfig;"
        " print('nox-probe', f'{sys.version_info.major}.{sys.version_info.minor}',"
        " sysconfig.get_config_var('Py_GIL_DISABLED') or 0)"
    )
    runner = session.run_install if post_sync else session.run
    out = runner("python", "-c", probe, silent=True, log=False)
    if not isinstance(out, str):
        return  # This runner is disabled by the current flags; the other side covers it.

    # Stdout is shared, so match the exact shape and take the last -- site hooks print before we do. Per line
    # rather than a MULTILINE anchor: the probe's stdout is CRLF-terminated on Windows.
    pattern = re.compile(r"^nox-probe (\d+\.\d+) (\d+)$")
    found = [m.groups() for line in out.splitlines() if (m := pattern.match(line.strip()))]
    if not found:
        session.error(f"could not read the interpreter of {session.virtualenv.location}; probe said {out!r}")
    got, gil_disabled = found[-1]
    want = session.python if isinstance(session.python, str) else None

    if want is not None and got != want.removesuffix("t"):
        session.error(
            f"session python={want} but {session.virtualenv.location} is {got}; "
            + (
                "uv sync replaced it -- check requires-python and UV_PYTHON"
                if post_sync
                else "re-run with --reuse-venv=never to rebuild it"
            )
        )
    free_threaded, wanted_free_threaded = gil_disabled != "0", (want or "").endswith("t")
    if free_threaded != wanted_free_threaded:
        was, expected = ("a free-threaded", "a regular") if free_threaded else ("a regular", "a free-threaded")
        hint = f"; run `uv python install {want}` to provide {expected} one" if want else ""
        session.error(f"{session.virtualenv.location} is {was} build, expected {expected} one{hint}")
