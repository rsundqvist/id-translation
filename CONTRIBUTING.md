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

1. **Installing [uv](https://docs.astral.sh/uv/getting-started/installation/)**
   
   See [uv.lock](https://github.com/rsundqvist/rics/blob/master/uv.lock) for the version used.
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Installing the project**
   
   Clone and install the virtual environment used for development. Some material
   is placed in submodules, so we need to clone recursively.
   ```bash
   git clone git@github.com:rsundqvist/id-translation.git
   cd id-translation
   uv sync
   ```
   
   Generating documentation has a few dependencies which may need to be installed
   manually.
   ```bash
   sudo apt-get update
   sudo apt-get install pandoc tree
   ```
   
3. **Verify installation (optional)**

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
act -j tests
```

will execute the [tests](https://github.com/rsundqvist/rics/blob/master/.github/workflows/tests.yml) workflow.
