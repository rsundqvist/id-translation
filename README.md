<div align="center">
  <img src="https://github.com/rsundqvist/rics/raw/master/docs/logo-text.png"><br>
</div>

-----------------

# Convert IDs to human-readable labels. <!-- omit in toc -->
[![PyPI - Version](https://img.shields.io/pypi/v/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![Tests](https://github.com/rsundqvist/id-translation/workflows/tests/badge.svg)](https://github.com/rsundqvist/id-translation/actions?workflow=tests)
[![Codecov](https://codecov.io/gh/rsundqvist/id-translation/branch/main/graph/badge.svg)](https://codecov.io/gh/rsundqvist/id-translation)
[![Read the Docs](https://readthedocs.org/projects/id-translation/badge/)](https://id-translation.readthedocs.io/)
[![PyPI - License](https://img.shields.io/pypi/l/id-translation.svg)](https://pypi.python.org/pypi/id-translation)
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](https://github.com/pre-commit/pre-commit)

## What is it?

A package suite for translating integer IDs typically found in databases. Translation is highly configurable and tested
for multiple different SQL dialects and schema naming paradigms. This is configurable using TOML, allowing power users
to specify shared configurations that "just work" for regular users. See the example snippet below.

```python
from id_translation import Translator

def get_singleton() -> Translator:
  """Returns pre-built Translator instance."""
  return Translator.load_persistent_instance(
    "/company/translation/config.toml",
    extra_fetchers=["/company/translation/customer-database-config.toml"],
    # Singleton is updated by a CRON job; regular users don't have write access.
    max_age=None,  # None = never update
  )
```
_A function to create [Translator][translate] instances that "just work"._

## Highlighted Features

- A highly configurable translation [format] strings.
- Powerful automated [Name-to-source][n2s-mapping] and format [placeholder][pm-mapping] mapping, backed by the 
  [RiCS](https://rics.readthedocs.io/) library.
- Prebuilt fetchers for [SQL][sql-fetcher] and [file-system][pandas-fetcher] sources.
- Configure using [TOML][translator-config].
- Support for [persistent] instances stored on disk.

[translate]: https://id-translation.readthedocs.io/en/latest/_autosummary/id_translation.html#id_translation.Translator.translate
[format]: https://id-translation.readthedocs.io/en/latest/_autosummary/id_translation.offline.html#id_translation.offline.Format
[n2s-mapping]: https://id-translation.readthedocs.io/en/latest/documentation/translation-primer.html#name-to-source-mapping
[pm-mapping]: https://id-translation.readthedocs.io/en/latest/documentation/translation-primer.html#placeholder-mapping
[persistent]: https://id-translation.readthedocs.io/en/latest/_autosummary/id_translation.html#id_translation.Translator.load_persistent_instance
[sql-fetcher]: https://id-translation.readthedocs.io/en/latest/_autosummary/id_translation.fetching.html#id_translation.fetching.SqlFetcher
[pandas-fetcher]: https://id-translation.readthedocs.io/en/latest/_autosummary/id_translation.fetching.html#id_translation.fetching.PandasFetcher
[translator-config]: https://id-translation.readthedocs.io/en/latest/documentation/translator-config.html


## Installation
The package is published through the [Python Package Index (PyPI)]. Source code
is available on GitHub: https://github.com/rsundqvist/id-translation

```sh
pip install -U id-translation
```

This is the preferred method to install ``id-translation``, as it will always install the
most recent stable release.

If you don't have [pip] installed, this [Python installation guide] can guide
you through the process.

## License
[MIT](LICENSE.md)

## Documentation
Hosted on Read the Docs: https://id-translation.readthedocs.io

## Contributing

All contributions, bug reports, bug fixes, documentation improvements, enhancements, and ideas are welcome. To get 
started, see the [Contributing Guide](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md).

[Python Package Index (PyPI)]: https://pypi.org/project/id-translation
[pip]: https://pip.pypa.io
[Python installation guide]: http://docs.python-guide.org/en/latest/starting/installation/
