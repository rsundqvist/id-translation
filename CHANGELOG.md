# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New optional `schema` argument for `SqlFetcher`.
- Finished `Translator.load_persistent_instance()` implementation (no longer experimental).

### Changed
- Improve error reporting for unmapped required placeholders; warn about potential override issues.
- Default `MultiFetcher.duplicate_source_discovered_action` increased from _'ignore'_ to _'warn'_.
- Allow specifying `MultiFetcher` init arguments from the main TOML configuration file.
- Set default value of `MultiFetcher.max_workers` to 1.

### Fixed
- Minimum install requirement is now correctly set to `SQLAlchemy>=1.4`.

## [0.2.1] - 2023-02-04

### Added
- Now compatible with `SQLAlchemy>=2`. Typing has not been updated for SQLAlchemy v2, since this would break backwards
  compatibility with `SQLAlchemy<2`.

### Changed
- Improve some SQL Fetcher log messages.

## [0.2.0] - 2022-11-30

### Fixed
- Fixed a few documentation issues.

### Changed
- Bump requirement from `rics==1.0.0` to `rics>=2`.
- Switch `id_translation.ttypes` back to just `types`.

## [0.1.0] - 2022-11-26
* Branch from [rics@v1.0.0](https://github.com/rsundqvist/rics/blob/v1.0.0/CHANGELOG.md).

### Changed
* Move out of `rics` namespace.
* Switch to relative imports.
* Fix some intersphinx issues.

[Unreleased]: https://github.com/rsundqvist/id-translation/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/rsundqvist/id-translator/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rsundqvist/id-translation/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rsundqvist/id-translation/compare/v0.0.0...v0.1.0
