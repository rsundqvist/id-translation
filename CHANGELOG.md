# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Add handling of attributes of retrieved translation elements (e.g. `UUID.int`).
- The `AbstractFetcher.selective_fetch_all`-flag now restricts the columns retrieved by `SqlFetcher`.

### Fixed
- Translation of `pandas.MultiIndex` is now properly supported, as indicated by `resolve_io` not throwing.
- Preserve `format_spec` and `conversion` in `Format` positional arguments.
- Ensure deterministic match selection when scores are equal due to overrides.

### Removed
- The now unused module `fetching.support`, and the function `SqlFetcher.TableSummary.select_columns()`.

## [0.4.0] - 2023-06-16

### Added
- The `uuid.UUID`-type has been added to `IdType`s.
- Add the `Translator.enable_uuid_heuristics` flag (default=`False`).
- The `Translator.translate()`-method now accepts an optional `fmt`-argument (had to use 
  `Translator.copy(fmt=fmt).translate(...)` before).
- Improved support and added documentation for override-only mapping.

### Changed
- Clean up and rename a large number of heuristic and filter functions.
- Changed the default score function of the `Mapper` from `equality` to `disabled`.
- The `TranslatorFactory` now makes an effort to include the source file of config issues.

### Fixed
- Duplicate explicit names are now supported for most types (closes #4).
- Duplicate column names for the `pandas.DataFrame` translatable type are now supported.
- The `AbstractFetcher` class now uses a warning to inform the user about consequences when 
  `unmapped_values_action='raise'` is used.
- Instead of silently failing, the `SqlFetcher` now raises when ID column mapping fails for a whitelisted table.
- Fixed a performance issue when translating large `pandas.Series` instances (including `pandas.DataFrame` columns).

### Removed
- The `FormatApplier` class is no longer abstract. Removed `DefaultFormatApplier`.
- The `Mapper.context_sensitive_overrides` property. Plain overrides are now treated as shared/default overrides when a
  context is given. The type check in `AbstractFetcher` has been removed (config-based fetching will work as before).

## [0.3.1] - 2023-03-19

### Changed
- Convert `rics.mapping` into an internal package. ID translation now uses `id_translation.mapping`.
- Reduce the amount of records emitted in non-verbose mode.
- Structure mapping log messages by use case; `*.mapping.name-to-source` and `*.mapping.name-to-source.placeholders`.
- Fetchers inheriting from `AbstractFetcher` now include the primary cache key in the logger name (config filename).

## [0.3.0] - 2023-03-10
Release 0.3.0, require `rics>=3.0.0`. Add the [id-translation-project](https://github.com/rsundqvist/id-translation-project)
cookiecutter template.

### Added
- New optional `schema` argument for `SqlFetcher`.
- Finished `Translator.load_persistent_instance()` implementation (no longer experimental).
- The `SqlFetcher.finalize_statement()` method, used to customize fetching behavior programmatically.
- New INFO-level begin/end log messages for `Translator.translate()`.
- Raise `ConcurrentOperationError` in `AbstractFetchers.fetch()` to prevent race conditions.
- Limit `AbstractFetcher.fetch_all()` to sources that contain the required placeholders (after mapping) by default.
- A large number of new debug messages with `extra`-dict values set. These all have keys `event_key` and `event_stage`
  as well as an `executon_time` argument when `event_stage='EXIT'`. Additional extras depend on context.
- Caching logic to `AbstractFetcher`. Only active when explicitly enabled and `AbstractFetcher.online` is `False`.
- Environment variable interpolation is now possible anywhere TOML config files. Key points:
  * Cache logic does NOT consider actual values (only names)
  * By default, simple interpolation is enabled.
  * TOML config metaconfig can be placed in `metaconf.toml`, next to main config.
  * Interpolation can be configured under `[env]` in metaconf.

### Changed
- Improve error reporting for unmapped required placeholders; warn about potential override issues.
- Default `MultiFetcher.duplicate_source_discovered_action` increased from _'ignore'_ to _'warn'_.
- Allow specifying `MultiFetcher` init arguments from the main TOML configuration file.
- Set default value of `MultiFetcher.max_workers` to 1.
- Set default value of `SqlFetcher.include_views` to `False`.

### Fixed
- Minimum install requirement is now correctly set to `SQLAlchemy>=1.4`.
- Now correctly always fetches all placeholders when performing a _FETCH_ALL_-operation.
- Copy `allow_name_inheritance` in `Translator.copy()`.

### Removed
- Redundant alias `types.ExtendedOverrideFunction` and related code.
- The `PandasFetcher.read_function_args` init argument, since `read_function_kwargs` is much less error-prone.
- Custom handling of environment variables in `SqlFetcher`.

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
- Branch from [rics@v1.0.0](https://github.com/rsundqvist/rics/blob/v1.0.0/CHANGELOG.md).

### Changed
- Move out of `rics` namespace.
- Switch to relative imports.
- Fix some intersphinx issues.

[Unreleased]: https://github.com/rsundqvist/id-translation/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/rsundqvist/id-translator/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/rsundqvist/id-translator/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/rsundqvist/id-translator/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/rsundqvist/id-translator/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rsundqvist/id-translation/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rsundqvist/id-translation/compare/v0.0.0...v0.1.0
