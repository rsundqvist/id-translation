# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.12.1] - 2024-09-28

### Fixed
- Filter children by sources in `MultiFetcher.fetch_all()`.

## [0.12.0] - 2024-09-28

### Added
- Property `TranslationMap.len_per_source`.

### Changes
- Improve `PolarsIO` performance (~4x faster for large datasets).
- Typing updates (notably numpy `2.0`).
- Added `concurrent_operation_action=raise|ignore` to `AbstractFether`. Default is `ignore` for `MemoryFetcher`.
- Implementations that override `SqlFetcher.select_where()` no longer have to call the supermethod to ensure that IDs
  are filtered.

### Fixed
- The `Translator.go_offline(translatable=None)`-method now respects given names arguments.

### Removed
- The `AbstractFetcher` now longer provides a caching implementation. Provides overridable methods instead.

## [0.11.1] - 2024-06-17

### Fixed
- Fix crash when using `deepclone`d `MultiFetcher` instances (again).

## [0.11.0] - 2024-06-16

### Added
- Implemented `SqlFetcher.__deepclone__()`.

### Deprecated
- Parameter `inplace`; use `copy` instead.
- Parameter `maximal_untranslated_fraction`; use `max_fails` instead.

### Fixed
- Fix crash when using `deepclone`d `MultiFetcher` instances.
- Fix crash when object-type ID collections contain `NaN/None` values.

## [0.10.2] - 2024-05-28

### Fixed
- Fix crash on import with `rics>=4.1.0`.

## [0.10.1] - 2024-04-17

### Fixed
- Rewrite the [Override-only mapping](https://id-translation.readthedocs.io/en/stable/documentation/mapping-primer.html#override-only-mapping)
  subsection in the mapping primer. Improve clarity and fix some confusing sentences.
- Improved exception handling in the `MultiFetcher`; add notes to identify raising child.

## [0.10.0] - 2024-04-08

### Added
- Added integration for [polars.DataFrame](https://docs.pola.rs/py-polars/html/reference/dataframe/index.html).
- Added integration for [dask.DataFrame](https://docs.dask.org/en/stable/dataframe.html) and Series.

### Changed
- Consume `[transform]`-sections in auxiliary configuration files (#231).
- Added typehints to `dio.DataStructureIO` and other `id_translation.dio` classes and functions.
- Added functions and methods to make creating new `DataStructureIO` implementations easier.

### Fixed
- Verify top-level sections in auxiliary configuration files.

## [0.9.0] - 2024-03-28

### Added
- Added new utility `utils.translation_helper.TranslationHelper`.
- Added several new `TypedDict` types to `translator_typing`.
- Added `Translator.translate` overloads. Catch-all overload for `reverse=True`.
- Added many new in-line examples to class, function and module docstrings. Updated and corrected or clarified several 
  docstrings which were poorly worded or outdated. 

### Changed
- Methods `Translator.fetch()` and `go_offline()` now expose arguments (such as 
  `maximal_untranslated_fraction`) that were previously limited to `translate()`.
- Improve when a `maximal_untranslated_fraction` is in use.
- The `Format` class is now callable for convenience (keyword only).

### Fixed
- Return copy in `TranslationMap.name_to_source` - consistent with similar properties.
- Handle `dict` names properly in `Translator.fetch()` and `go_offline()`.
- Untranslated IDs should now never be `None` - ensure a valid `Format` is always available.
- Raise `ValueError` when using positional placeholders in `Format`. This used to be a silent error.

## [0.8.0] - 2024-03-23

### Added
- Python `3.12` is now fully tested and supported in CI/CD.
- New module `translator_typing`. Useful especially users who which to extend the base `Translator` implementation.
- Added support for simplified `Translator.fetcher` arguments on the form `{source: {id: name}}`.

### Changed
- Python minimum version is now `3.11` (was `3.8`).
- Minimum `pandas` version is now `2.0.3` (was `1.1.0`).
- Minimum `sqlalchemy` version is now `2.0.5` (was `1.4.16`).
- Updated base exceptions for several `id_translation.*.exceptions`-members:
  * `DataStructureIOError`: `RuntimeError` -> `TypeError`
  * `ConfigurationError`: `ValueError` -> `TypeError`
  * `ConnectionStatusError`: `ValueError` -> `ConnectionError`
  * `TranslationError`: `ValueError` -> `Exception`
  * `MappingError`: `ValueError` -> `Exception`
- Make  `unmapped_values_action != 'ignore'` actions more specific: Raise new `UnmappedValuesError(MappingError)` or 
  warn `UnmappedValuesWarning(MappingWarning)` (used to raise parent types directly). Add hints to warning message.

## [0.7.1] - 2024-03-09

### Changed
- Heuristic functions that accept a `plural_to_singular`-argument now also accept a custom transformer.
- Expose read-only attributes `Translator.fmt` and `default_fmt`.

### Fixed
- Fixed an issue which sometimes caused a crash when verifying translations.
- Fixed an issue which sometimes caused a crash when one or more names were empty (zero IDs).
- Fixed plural-to-singular (`NounTransformer`) transforms of nouns such as _'languages'_, '_states_', and many others.
- Fixed a performance issue for large `pandas.Series` and `Index` objects.

## [0.7.0] - 2024-02-09

### Added
- New short-circuiting function `mapping.heuristic_functions.smurf_columns()`.
- New function `dio.register_io()`, allowing users to create their own custom IO implementations.
- New property `Translator.transformers`, allowing users to register new transformers after initialization.

### Changed
- Lower cache hit default log level from INFO to DEBUG.
- Rename `MultiFetcher.fetchers` -> `MultiFetcher.children`.

### Fixed
- Some cosmetic logging and documentation issues.
- The base cache path for fetcher data is now configurable using `CacheAccess.BASE_CACHE_PATH`.
- The `MultiFetcher` will no longer discard required fetchers for any reason.
- Fall back to fetcher reuse in `Translator.clone()` when `deepcopy(Translator.fetcher)` fails.

### Removed
- The ` Translator.get_transformer` method (redundant: use `Translator.transformers.get()` instead). 

## [0.6.0] - 2023-11-29

### Added
- The `Translate.translate()`-method now has overloads for improved typing.
- User-defined ID and translation transformation framework: `id_translation.transform`.
- Bitmask translation support: `id_translation.transform.BitmaskTransformer`.
- Serialization methods for `TranslationMap`: `to_dicts()`, `to_pandas()`, `from_pandas()`. Translations maps are
  returned by `Translator.fetch()` and the `cache` attribute.

### Changed
- Make `Translator.translated_names()` optionally return a mapping dict instead of just names.
- Caching data for the `AbstractFether` has been updated.
  * Reduce the amount of excess data stored (now: records only).
  * Store records per source instead of all sources in the same *.pkl*-file.
- Improve handling for `UUID`-like IDs. `Fetcher` implementations now respect `Translator` settings with regard to UUID 
  mitigations.
- Update `SqlFetcher`:
  * No longer uses table sizes. This could be expensive for large tables.
  * Simplify selection filtering; now only uses `SqlFetcher.select_where()` instead of two separate methods.
  * Add special handling of UUIDs when `SQLAlchemy<2`.
- Renamed `Translator.store()` -> `Translator.go_offline()`.
- Change `Translator.default_fmt` to `Format("<Failed: id={id!r}>")` (was `None`).

### Fixed
- Fixed issues in `Format`:
  - Fixed rendering of `{id}` when used in fallback format.
  - Fixed rendering of escaped curly brackets `{{literal-text}}`.
  - Convert optional blocks without placeholders to literal text.
- The `PandasFetcher` now properly handles remote filesystems.

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

[Unreleased]: https://github.com/rsundqvist/id-translation/compare/v0.12.1...HEAD
[0.12.1]: https://github.com/rsundqvist/id-translator/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/rsundqvist/id-translator/compare/v0.11.1...v0.12.0
[0.11.1]: https://github.com/rsundqvist/id-translator/compare/v0.11.0...v0.11.1
[0.11.0]: https://github.com/rsundqvist/id-translator/compare/v0.10.2...v0.11.0
[0.10.2]: https://github.com/rsundqvist/id-translator/compare/v0.10.1...v0.10.2
[0.10.1]: https://github.com/rsundqvist/id-translator/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/rsundqvist/id-translator/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/rsundqvist/id-translator/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/rsundqvist/id-translator/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/rsundqvist/id-translator/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/rsundqvist/id-translator/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/rsundqvist/id-translator/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/rsundqvist/id-translator/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/rsundqvist/id-translator/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rsundqvist/id-translator/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/rsundqvist/id-translator/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/rsundqvist/id-translator/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/rsundqvist/id-translator/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/rsundqvist/id-translation/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rsundqvist/id-translation/compare/v0.0.0...v0.1.0
