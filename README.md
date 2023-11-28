# ID Translation
**_Convert IDs to human-readable labels._**

-----------------

[![PyPI - Version](https://img.shields.io/pypi/v/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![Tests](https://github.com/rsundqvist/id-translation/workflows/tests/badge.svg)](https://github.com/rsundqvist/id-translation/actions?workflow=tests)
[![Codecov](https://codecov.io/gh/rsundqvist/id-translation/branch/master/graph/badge.svg)](https://codecov.io/gh/rsundqvist/id-translation)
[![Read the Docs](https://readthedocs.org/projects/id-translation/badge/)](https://id-translation.readthedocs.io/)
[![PyPI - License](https://img.shields.io/pypi/l/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)


<div align="center">
  <img src="https://github.com/rsundqvist/id-translation/raw/master/docs/_images/covid-europe-mplcyberpunk-theme.png"><br>
</div>

Country IDs translated using the standard `id:name`-format. Click [here][ecdc] for source.

[ecdc]: https://www.ecdc.europa.eu/en/publications-data/download-todays-data-geographic-distribution-covid-19-cases-worldwide

## What is it?
A package suite for translating integer IDs typically found in databases. Translation is highly configurable and tested
for multiple different SQL dialects and schema naming paradigms. The included TOML configuration format as well as the
support functions make it easy to create and share working configurations with anyone who needs them.

# Cookiecutter template project
The fastest way to get started with `id-translation` is the 🍪[id-translation-project] cookiecutter template. It is
designed to allow power users to quickly specify shared configurations that "just work" for other users; see the example
below.

```python
from big_corporation_inc.id_translation import translate
print(
  "The first employee at Big Corporation Inc. was:", 
  translate(1, names="employee_id"),
)
```

Check out this [demo project](https://github.com/rsundqvist/id-translation-project/tree/master/demo/bci-id-translation)
(and its 📚[generated documentation](https://rsundqvist.github.io/id-translation-project/)) to get a preview of what 
Your generated project might look like, or continue to the next section for a brief feature overview.

[id-translation-project]: https://github.com/rsundqvist/id-translation-project/

# Highlighted Features
- Support for ``int`` and ``string`` IDs, including ``UUID``-like types.
- Translation of [pandas types][pandas-translation], including `pandas.Index` types.
- Intuitive [Format strings][format], with support for optional elements.
- Powerful automated [Name-to-source][n2s-mapping] and [Format placeholder][pm-mapping] mapping.
- Prebuilt fetchers for [SQL][sql-fetcher] and [file-system][pandas-fetcher] sources.
- Configure using [TOML][translator-config], support for [persistent] instances stored on disk.

[pandas-translation]: https://id-translation.readthedocs.io/en/stable/documentation/examples/notebooks/cookbook/pandas-index.html
[translate]: https://id-translation.readthedocs.io/en/stable/_autosummary/id_translation.Translator.translate.html
[format]: https://id-translation.readthedocs.io/en/stable/_autosummary/id_translation.offline.html#id_translation.offline.Format
[n2s-mapping]: https://id-translation.readthedocs.io/en/stable/documentation/translation-primer.html#name-to-source-mapping
[pm-mapping]: https://id-translation.readthedocs.io/en/stable/documentation/translation-primer.html#placeholder-mapping
[persistent]: https://id-translation.readthedocs.io/en/stable/_autosummary/id_translation.Translator.load_persistent_instance.html
[sql-fetcher]: https://id-translation.readthedocs.io/en/stable/_autosummary/id_translation.fetching.html#id_translation.fetching.SqlFetcher
[pandas-fetcher]: https://id-translation.readthedocs.io/en/stable/_autosummary/id_translation.fetching.html#id_translation.fetching.PandasFetcher
[translator-config]: https://id-translation.readthedocs.io/en/stable/documentation/translator-config.html


# Installation
The package is published through the [Python Package Index (PyPI)]. Source code
is available on GitHub: https://github.com/rsundqvist/id-translation

```sh
pip install -U id-translation
```

This is the preferred method to install `id-translation`, as it will always install the
most recent stable release.

# License
[MIT](LICENSE.md)

# Documentation
Hosted on Read the Docs: https://id-translation.readthedocs.io

# Contributing

All contributions, bug reports, bug fixes, documentation improvements, enhancements, and ideas are welcome. To get 
started, see the [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

[Python Package Index (PyPI)]: https://pypi.org/project/id-translation
