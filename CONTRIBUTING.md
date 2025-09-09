# Contributing <!-- omit in toc -->

First of all, thank you for using and contributing to `id-translation`! Any and all contributions are welcome.

## Creating issues
Issues are tracked on [GitHub](https://github.com/rsundqvist/id-translation/issues). Issue
reports are appreciated, but please use a succinct title and add relevant tags.
Please include a [**Minimal reproducible example**][minimal-reproducible-example]
if reporting an issue, or sample snippet if requesting a new feature or change 
which demonstrates the (desired) usage.

[minimal-reproducible-example]: https://stackoverflow.com/help/minimal-reproducible-example

## Getting started
Follow these steps to begin local development.

1. **Installing [Poetry](https://python-poetry.org/docs/)**
   
   See [poetry.lock](https://github.com/rsundqvist/id-translation/blob/master/poetry.lock) for the version used.
   ```bash
   curl -sSL https://install.python-poetry.org/ | python -
   ```

2. **Installing the project**
   
   Clone and install the virtual environment used for development. Some material
   is placed in submodules, so we need to clone recursively.
   ```bash
   git clone git@github.com:rsundqvist/id-translation.git
   cd id-translation
   poetry install --all-extras
   ```
   
   Generating documentation has a few dependencies which may need to be installed
   manually.
   ```bash
   sudo apt-get update
   sudo apt-get install pandoc tree
   ```
   
3. **Verify installation (optional)**
   
   Start the [test databases](https://hub.docker.com/r/rsundqvist/sakila-preload).
   ```bash
   ./run-docker-dvdrental.sh
   ```

   Run all invocations.
   ```bash
   ./run-invocations.sh
   ```
   This is similar to what the CI/CD pipeline does for a single OS and major Python version.

### Running GitHub Actions locally
Relying on GitHub actions for new CI/CD features is quite slow. An alternative is to use 
[act](https://github.com/nektos/act) instead, which allows running pipelines locally (with some limitations, see `act` 
docs). For example, running

```shell
act -j tests --matrix python-version:3.12
```

will execute the [tests](https://github.com/rsundqvist/id-translation/blob/master/.github/workflows/tests.yml) workflow.

## Branching point
Branched from [rics@v1.0.0](https://github.com/rsundqvist/rics/tree/v1.0.0).
