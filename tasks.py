"""Tasks for maintaining the project.

Execute 'invoke --list' for guidance on using Invoke.
"""

import platform
import webbrowser
from pathlib import Path

from invoke import call, task
from invoke.context import Context
from invoke.runners import Result

ROOT_DIR = Path(__file__).parent
DOCS_DIR = ROOT_DIR.joinpath("docs")
DOCS_BUILD_DIR = DOCS_DIR.joinpath("_build")
COVERAGE_FILE = ROOT_DIR.joinpath(".coverage")
COVERAGE_DIR = ROOT_DIR.joinpath("htmlcov")
COVERAGE_REPORT = COVERAGE_DIR.joinpath("index.html")
SOURCE_DIR = ROOT_DIR.joinpath("src/id_translation")
TEST_DIR = ROOT_DIR.joinpath("tests")
NOTEBOOK_DIR = ROOT_DIR.joinpath("notebooks")
PYTHON_TARGETS = [
    SOURCE_DIR,
    TEST_DIR,
    NOTEBOOK_DIR,
    ROOT_DIR.joinpath("noxfile.py"),
    Path(__file__),
]
PYTHON_TARGETS_STR = " ".join([str(p) for p in PYTHON_TARGETS])


def _run(c: Context, command: str, env: dict[str, str] | None = None) -> Result:
    print(f"Command: {command}")
    return c.run(command, pty=platform.system() != "Windows", env=env)


@task
def clean_build(c: Context) -> None:
    """Clean up files from package building."""
    _run(c, "rm -fr build/")
    _run(c, "rm -fr dist/")
    _run(c, "rm -fr .eggs/")
    _run(c, "find . -name '*.egg-info' -exec rm -fr {} +")
    _run(c, "find . -name '*.egg' -exec rm -f {} +")


@task
def clean_python(c: Context) -> None:
    """Clean up python file artifacts."""
    _run(c, "find . -name '*.pyc' -exec rm -f {} +")
    _run(c, "find . -name '*.pyo' -exec rm -f {} +")
    _run(c, "find . -name '*~' -exec rm -f {} +")
    _run(c, "find . -name '__pycache__' -exec rm -fr {} +")


@task
def clean_tests(c: Context) -> None:
    """Clean up files from testing."""
    _run(c, f"rm -f {COVERAGE_FILE}")
    _run(c, f"rm -fr {COVERAGE_DIR}")
    _run(c, "rm -fr .pytest_cache")


@task
def clean_docs(c: Context) -> None:
    """Clean up files from documentation builds."""
    _run(c, f"rm -fr {DOCS_BUILD_DIR}")

    dirs = "_autosummary", "changelog", "auto_examples", "gen_modules", "documentation/examples/notebooks"
    more_dirs = " ".join(map(str, map(DOCS_DIR.joinpath, dirs)))
    _run(c, f"rm -fr {more_dirs}")


@task
def clean_ruff(c: Context) -> None:
    """Clean ruff cache (linter)."""
    _run(c, "ruff clean")


@task(pre=[clean_build, clean_python, clean_ruff, clean_tests, clean_docs])
def clean(_: Context) -> None:
    """Run all clean sub-tasks."""


@task(name="format")
def format_(c: Context, check: bool = False) -> None:
    """Format code."""
    format_options = ["--check", "--diff"] if check else []
    _run(c, f"poetry run ruff format {' '.join(format_options)} {PYTHON_TARGETS_STR}")
    if not check:
        _run(c, f"poetry run ruff check --fix-only {' '.join(format_options)} {PYTHON_TARGETS_STR}")


@task
def flake8(c: Context, check: bool = False) -> None:
    """Run flake8."""
    lint_options = ["--no-fix"] if check else []
    _run(c, f"poetry run ruff check {' '.join(lint_options)} {PYTHON_TARGETS_STR}")


@task
def spelling(c: Context) -> None:
    """Run spell check."""
    _run(c, f"poetry run codespell {PYTHON_TARGETS_STR}")
    _run(c, f"poetry run codespell {DOCS_DIR} --skip *.html*,*.js,*.map,*.css")


@task
def safety(c: Context) -> None:
    """Run safety."""
    _run(
        c,
        "poetry export --format=requirements.txt --without-hashes | poetry run safety check --stdin --full-report",
    )


@task(pre=[safety, call(flake8, check=True), call(format_, check=True), spelling])
def lint(_: Context) -> None:
    """Run all linting."""


@task
def mypy(c: Context) -> None:
    """Run mypy."""
    _run(c, f"poetry run mypy {SOURCE_DIR} {TEST_DIR}")


@task
def tests(c: Context) -> None:
    """Run tests."""
    pytest_options = [
        "--xdoctest",
        "--cov",
        "--cov-append",
        "--cov-report=",
        "--cov-fail-under=0",
    ]
    _run(c, f"poetry run pytest {' '.join(pytest_options)} {TEST_DIR} {SOURCE_DIR}")


@task(
    help={
        "fmt": "Build a local report: report, html, json, annotate, html, xml.",
        "open_browser": "Open the coverage report in the web browser (requires --fmt html)",
    }
)
def coverage(c: Context, fmt: str = "report", open_browser: bool = False) -> None:
    """Create coverage report."""
    if any(Path().glob(".coverage.*")):
        _run(c, "poetry run coverage combine")
    if fmt != "report":
        # Always print the report
        _run(c, "poetry run coverage report -i")
    _run(c, f"poetry run coverage {fmt} -i")
    if fmt == "html" and open_browser:
        webbrowser.open(COVERAGE_REPORT.as_uri())


@task(
    help={
        "open_browser": "Open the docs in the web browser",
    }
)
def docs(c: Context, open_browser: bool = False) -> None:
    """Build documentation."""
    build_docs = f"sphinx-build -T -E -W --keep-going -a {DOCS_DIR} {DOCS_BUILD_DIR}"
    _run(c, build_docs, env={"SPHINX_BUILD": "true"})
    if open_browser:
        index = DOCS_BUILD_DIR / "index.html"
        webbrowser.open(index.absolute().as_uri())


@task(
    help={
        "part": "Part of the version to be bumped.",
        "dry_run": "Don't write any files, just pretend. (default: False)",
    }
)
def version(c: Context, part: str, dry_run: bool = False) -> None:
    """Bump version."""
    bump_options = ["--dry-run"] if dry_run else []
    _run(c, f"poetry run bump2version {' '.join(bump_options)} {part}")

    if not dry_run and part != "dev":
        print("Add dev suffix..")

        no_dev = ["CHANGELOG.md"]

        part = "dev"
        _run(
            c,
            f"poetry run bump2version {' '.join(bump_options)} {part} --commit-args='--no-verify'",
        )
        print(f"Undo changes to release-only files: {' '.join(map(repr, no_dev))}")
        _run(
            c,
            f"git checkout HEAD^ -- {' '.join(no_dev)} && git commit --amend --no-edit --no-verify --quiet",
        )


@task
def pyupgrade(c: Context, check: bool = False) -> None:
    """Apply ``pyupgrade`` to all .py-files in ``PYTHON_TARGETS``."""
    flags = ["--py311-plus"]
    if not check:
        flags.append("--exit-zero-even-if-changed")

    def apply(*paths: Path) -> None:
        for path in paths:
            if path.is_file() and path.suffix == ".py":
                _run(c, f"pyupgrade {' '.join(flags)} {path}")
            elif path.is_dir():
                apply(*path.rglob("*/*.py"))

    apply(*PYTHON_TARGETS)
