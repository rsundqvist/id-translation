# Contributing <!-- omit in toc -->

First of all, thank you for using and contributing to `id-translation`! Any and all contributions are welcome.

## Creating issues
Issues are tracked on [GitHub](https://github.com/rsundqvist/id-translation/issues). Issue
reports are appreciated, but please use a succinct title and add relevant tags.
Please include a [**Minimal reproducible example**][minimal-reproducible-example]
if reporting an issue, or sample snippet if requesting a new feature or change 
which demonstrates the (desired) usage.

[minimal-reproducible-example]: https://stackoverflow.com/help/minimal-reproducible-example

## PR guidelines
To be merged, all tests (including generating documentation), must be successful.

## Code requirements
General requirements which applies to all code in the library.

This is still a **pre-release library** (`version ~ 0.y.z`), meaning that breaking changes [are allowed](https://semver.org/#spec-item-4)
without a major version bump. But ***be nice to downstream users*** anyway. Don't make major and hard-to-adapt-to
breaking changes unless it makes sense and is needed.

### Unchecked requirements
These requirements are *not* verified in CI/CD.

* User-facing changes should be recorded in the [changelog](https://github.com/rsundqvist/id-translation/blob/master/CHANGELOG.md).
* Summarize the changes being made, and why they're made.
* Expensive operations (especially related to logging) should only be done if the result is needed.
* Coverage exceptions should be minimal.

### Checked requirements
These requirements are verified in CI/CD.

* Coverage must remain at 100% (after ignores).
* Public methods and classes must be documented.
* Use the commit hooks to format and lint the code.

## Getting started
Follow these steps to begin local development. I use Ubuntu LTS and PyCharm 
(both are kept updated), so such environments will usually work without too much
trouble.

1. **Installing [Poetry](https://python-poetry.org/docs/) and Invoke**
   
   Poetry is an alternative to tools like Pipenv.
   ```bash
   curl -sSL https://install.python-poetry.org/ | python -
   pip install invoke
   ```

2. **Installing the project**
   
   Clone and install the virtual environment used for development. Some material
   is placed in submodules, so we need to clone recursively.
   ```bash
   git clone --recurse-submodules git@github.com:rsundqvist/id-translation.git
   cd id-translation
   git submodule update --init --recursive
   poetry install --all-extras --with=docs,notebooks
   ```
   
   Generating documentation has a few dependencies which may need to be installed
   manually.
   ```bash
   sudo apt-get update
   sudo apt-get install pandoc tree
   ```
   
3. **Install commit hooks (optional)**
   
   If this step is skipped, use `inv hooks` to run hooks manually.
   ```bash
   poetry run inv install-hooks
   ```
   
4. **Verify installation (optional)**

   This is similar to what the CI/CD pipeline will run for a single OS and major
   Python version. It also skips the additional isolation provided by `nox`,
   which may hide some dependency-gotchas.
   ```bash
   ./run-docker-dvdrental.sh
   ./run-invocations.sh
   ```


### Running GitHub Actions locally
Relying on GitHub actions for new CI/CD features is quite slow. An alternative is to use 
[act](https://github.com/nektos/act) instead, which allows running pipelines locally (with some limitations, see `act` 
docs). For example, running

```shell
act -j tests
```

will execute the [tests](https://github.com/rsundqvist/id-translation/blob/master/.github/workflows/tests.yml) workflow.

## Branching point
Branched from [rics@v1.0.0](https://github.com/rsundqvist/rics/tree/v1.0.0).

## Source template
Originally created with [Cookiecutter] and the [fedejaure/cookiecutter-modern-pypackage]
template. The repo has changed quite a lot since creation, but some linked
resources linked are still useful.

[Cookiecutter]: https://github.com/cookiecutter/cookiecutter
[fedejaure/cookiecutter-modern-pypackage]: https://github.com/fedejaure/cookiecutter-modern-pypackage
