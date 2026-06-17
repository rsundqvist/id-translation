"""Nox sessions."""

import platform

import nox
from nox.sessions import Session

nox.options.default_venv_backend = "uv"
nox.options.sessions = ["tests", "mypy"]
python_versions = ["3.11", "3.12", "3.13", "3.14"]


def install(session: Session) -> None:
    """Install the project using uv."""
    session.run_install(
        "uv",
        "sync",
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
    )
    session.run_always("uv", "sync", "--active", "--all-extras", external=True)
    session.install(".")


def run_invoke(session: Session, *args: str, env: dict[str, str] | None = None) -> None:
    """Run an ``inv`` task with the session venv as uv's project environment.

    Without this, the inner ``uv run`` calls in ``tasks.py`` default to ``.venv`` and ignore the
    ``VIRTUAL_ENV`` that nox sets to the session venv, emitting a mismatch warning.
    """
    session.run("inv", *args, env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location, **(env or {})})


@nox.session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite."""
    install(session)
    try:
        run_invoke(
            session,
            "tests",
            env={
                "COVERAGE_FILE": f".coverage.{platform.system()}.{platform.python_version()}",
            },
        )
    finally:
        if session.interactive:
            session.notify("coverage")


@nox.session(python="3.14t")
def free_threading(session: Session) -> None:
    """Run the free-threaded (GIL-less) race tests on a Py_GIL_DISABLED build.

    Not part of the default sessions: requires a free-threaded interpreter (``3.14t``). Uses a
    minimal dependency set instead of the full ``--all-extras`` sync of the ``tests`` session, since
    several test/DB extras (e.g. ``pymssql``) have no free-threaded wheels yet.
    """
    session.install(".[fetching]", "pytest")
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
