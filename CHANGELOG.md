# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- The `Translate.translate()`-method now have overloads for improved typing.
- User-defined ID and translation transformation framework: `id_translation.transform`.
- Bitmask translation support: `id_translation.transform.BitmaskTransformer`.

### Changed
- Make `Translator.translated_names()` optionally return a mapping dict instead of just names.
- Caching data for the `AbstractFether` has been updated.
  * Reduce the amount of excess data stored (now: records only).
  * Store records per source instead of all sources in the same *.pkl*-file.
- Improve handling for `UUID`-like IDs. `Fetcher` implementations now adhere `Translator` settings in regard to UUID 
  mitigations. As special handling UUIDs when `SQLAlchemy<2`.
- Update `SqlFetcher`:
  * No longer uses table sizes. This could be expensive for large tables.
  * Simplify selection filtering; now only uses `SqlFetcher.select_where()` instead of two separate methods.

### Removed
- Attribute translation is no longer support. `Translator.allow_name_inheritance` attribute as been removed, as well as
  the `Translator.translate(attribute)`-argument.
- The `Translator.from_config(clazz)`-argument (always use `cls` instead).

## [0.5.1] - 2023-07-01

### Fixed
- Fix crash in `SqlFetcher.__str__` with bad engine configs.
- Lower excessive log level used when discarding optional fetchers (configuration option added).

## [0.5.0] - 2023-06-29

### Added
- Add `Translator.translated_names()`. Returns the most recent names that were translated by calling instance.
- Ability to mark a fetcher as _optional_. In multi-fetcher mode, optional fetchers are discarded if they raise an error
  the first time a source/placeholder enumeration is requested.
- A name-to-source dict may now be passed in place of the names `'names'`-argument.
- Translation of `set`-type data is now supported.
- Add environment variable `ID_TRANSLATION_DISABLED` to globally disable translation. Emits `TranslationDisabledWarning`
  once.
- New exception type `MissingNamesError`. Raised when names cannot be derived (and not explicitly given) based on the
  data type instead of `AttributeError`.

### Changed
- Add handling of attributes of retrieved translation elements (e.g. `UUID.int`).
- The `AbstractFetcher.selective_fetch_all`-flag now restricts the columns retrieved by `SqlFetcher`.
- Extend `heuristic_functions.like_database_table` to handle more pluralization types.
- Explicit `names` may no longer combined with `ignored_names`.
- Improve support for translation of heterogeneous `dict` value types.

### Fixed
- Translation of `pandas.MultiIndex` is now properly supported (as indicated by not throwing `UntranslatableTypeError`).
- Preserve `format_spec` and `conversion` in `Format.positional_part`. This means that format strings such as 
  `'{uuid!s:.8}:{name!r}'` will now work as expected.
- Ensure deterministic match selection when scores are equal due to overrides.
- Ensure placeholders aren't fetched twice in the same query.
- Prevent crashing when using a non-translatable parent type with the `'attribute'`-argument.

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

[Unreleased]: https://github.com/rsundqvist/id-translation/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/rsundqvist/id-translator/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/rsundqvist/id-translator/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rsundqvist/id-translator/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/rsundqvist/id-translator/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/rsundqvist/id-translator/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/rsundqvist/id-translator/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rsundqvist/id-translation/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rsundqvist/id-translation/compare/v0.0.0...v0.1.0
