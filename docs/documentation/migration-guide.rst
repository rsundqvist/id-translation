.. _migration-guide:

Adopting in an existing project
===============================
This guide is for **adding id-translation to an application you already have** -- one that already maps IDs in a handful
of ad-hoc ways (hard-coded ``dict``\ s, :meth:`pandas.Series.map`, ``enum`` ladders, ad-hoc SQL ``JOIN``\ s, f-strings)
and has accumulated enough of them to be worth consolidating.

.. note::

   Starting a brand-new, organization-wide translation library? See the
   https://github.com/rsundqvist/id-translation-project/ Cookiecutter template.

.. rubric:: A few terms first

* **source** -- a place labels are fetched from: a database table, a :class:`~id_translation.fetching.MemoryFetcher`
  dataset, a CSV, and so on.
* **placeholder** -- a column a source provides (``id``, ``name``, ``email``, ...). ``fmt`` strings reference these,
  e.g. ``fmt = "{name}"``.
* **name** -- overloaded: in ``translate(names=...)`` a *name* is the **field that holds IDs**
  (e.g. ``customer_id``), *not* the label; the label is usually the ``name`` *placeholder*.

Is it worth it?
---------------
``id-translation`` competes with a ``dict``, not with nothing. For a single, stable mapping in one place, a ``dict`` is
the right answer -- reach for this library only once *translation* has become a cross-cutting concern. Good signs you
are past that line:

* the same mapping is duplicated in more than one place (and has drifted, or will);
* you resolve IDs one row at a time -- an ``N+1`` loop -- over a large structure;
* labels come from a *mix* of sources: a database, a static map, a CSV;
* the label format is copy-pasted across modules.

Below that line, keep the ``dict``.

1. List your sources
--------------------
Inventory the ``id -> label`` mappings scattered through your code, and give each a *source* name. For an order-reporting
app that might be:

=============  =====================================  ============================
Source         Currently resolved by                  Lives in
=============  =====================================  ============================
``customers``  one SQL query per row (an ``N+1``)      your application database
``countries``  a hard-coded ``dict`` *and* a table     drifting between the two
``statuses``   an ``if/elif`` ladder                   a few lines of Python
=============  =====================================  ============================

Pick a single source of truth per mapping now -- the duplication is exactly what you are removing.

2. Point a fetcher at each source
---------------------------------
Each source becomes a :class:`~id_translation.fetching.Fetcher`, configured in TOML so the *what* stays out of your code.

**Your application database.** The built-in :class:`~id_translation.fetching.SqlFetcher` takes a SQLAlchemy connection
string (with optional ``${VAR}`` :ref:`environment-variable interpolation <translator-config>` for secrets):

.. code-block:: toml

   [fetching.SqlFetcher]
   connection_string = "postgresql://reporter:${DB_PASSWORD}@db.internal/app"
   whitelist_tables = ["customers", "countries"]

Interpolation is a plain string substitution, so a password containing URL-reserved characters (``@``, ``:``, ``/``,
``?``) would corrupt the connection string. For those, drop the password from the URL and pass it through the dedicated
``password`` key instead -- it is URL-escaped before being inserted at the ``{password}`` placeholder:

.. code-block:: toml

   [fetching.SqlFetcher]
   connection_string = "postgresql://reporter:{password}@db.internal/app"
   password = "${DB_PASSWORD}"

To reuse an engine your application already manages, subclass ``SqlFetcher`` and override its
:meth:`~id_translation.fetching.SqlFetcher.create_engine` classmethod. ``connection_string`` is passed to it verbatim,
so it can be any identifier (e.g. a per-environment database *slug*) rather than a literal URL:

.. code-block:: python

   from id_translation.fetching import SqlFetcher

   class AppFetcher(SqlFetcher):
       @classmethod
       def create_engine(cls, connection_string, password, engine_kwargs):
           from myapp.db import get_engine  # your existing per-environment engine
           return get_engine(connection_string)

Reference a custom fetcher by its fully-qualified name, and feed ``create_engine`` the slug through
``connection_string``. To choose the environment at runtime, interpolate an environment variable -- ``${VAR}`` works
out of the box, with no ``metaconf.toml`` required (that file :ref:`tunes interpolation and equivalence checks
<translator-config>`, both of which have working defaults):

.. code-block:: toml

   [fetching.'myapp.translation.AppFetcher']
   connection_string = "${APP_ENV:dev}"   # falls back to the 'dev' slug

Your factory (next step) sets ``APP_ENV`` before reading the config, so ``create_engine`` receives ``"dev"`` /
``"staging"`` / ``"prod"`` and maps it to the matching engine.

**Bind the** ``id`` **placeholder to your primary key.** Each source must supply an ``id`` placeholder, but your tables'
PKs are usually named ``customer_id``, ``code``, and so on. Map them explicitly with a per-source section:

.. code-block:: toml

   [fetching.mapping.overrides.customers]
   id = "customer_id"

   [fetching.mapping.overrides.countries]
   id = "code"

A column placed *directly* under ``[fetching.mapping.overrides]`` (no source) is a shared default applied to every
source, so a uniform convention needs only one line -- add per-source sections for the exceptions:

.. code-block:: toml

   [fetching.mapping.overrides]
   id = "code"            # default for every source

   [fetching.mapping.overrides.orders]
   id = "order_id"        # ...except this one

The :ref:`mapping primer <mapping-primer>` shows heuristics that can *infer* names like ``customer_id`` from a
``customers`` table, but an irregular PK like ``code`` matches nothing -- so when retro-fitting an existing schema,
explicit overrides are the reliable choice.

.. note::

   Two configuration tables share the word *overrides* but do unrelated jobs.
   ``[fetching.mapping.overrides.<source>]`` (above) maps a **placeholder to a column** inside one source.
   ``[translator.mapping.overrides]`` maps a **field name to a source** -- a persistent, config-file form of the
   ``names={field: source}`` dict in step 4:

   .. code-block:: toml

      [translator.mapping.overrides]       # field (name) -> source
      created_by = "staff"

      [fetching.mapping.overrides.staff]   # placeholder -> column
      id = "staff_id"

**Small static maps.** Use :class:`~id_translation.fetching.MemoryFetcher` -- no database, no file. The simplest form
maps each ID straight to its label:

.. code-block:: toml

   [fetching.MemoryFetcher.data.statuses]
   P = "Pending"
   S = "Shipped"
   D = "Delivered"
   C = "Cancelled"

This scalar form is ideal for string codes like these. For *integer* IDs, use the columnar
``id = [...]`` / ``name = [...]`` form (:ref:`config reference <translator-config>`) instead -- TOML keys are always
strings, so ``101 = "Widget"`` would store the key as the string ``"101"``.

**Tabular files.** Point a :class:`~id_translation.fetching.PandasFetcher` at CSV/Parquet/... sources.

3. One config, one entry point
------------------------------
Wrap construction in a single factory so the rest of your app never sees the wiring:

.. code-block:: python

   import os
   from pathlib import Path

   from id_translation import Translator

   _CONFIG = Path(__file__).parent / "config"

   def create_translator(env: str = "dev") -> Translator:
       os.environ["APP_ENV"] = env  # interpolated into the fetcher's connection_string
       return Translator.from_config(
           _CONFIG / "main.toml",
           extra_fetchers=[_CONFIG / "fetching" / "database.toml"],
       )

:meth:`~id_translation.Translator.from_config` accepts :class:`~pathlib.Path` objects; ``extra_fetchers`` lets each
source live in its own file, and multiple fetchers are composed automatically. Setting ``APP_ENV`` here is what makes
the ``${APP_ENV:dev}`` in the fetcher TOML resolve to the chosen environment -- interpolation happens when
``from_config`` reads the file.

4. Replace the call sites
-------------------------
Now collapse the scattered lookups into a single call. The ``names`` argument accepts a ``{field: source}`` dict that
binds each ID-bearing field to the source that resolves it -- bypassing name-to-source heuristics entirely, which is
usually what you want when retro-fitting an existing schema:

.. code-block:: python

   translator = create_translator()
   translator.translate(
       df,
       names={"customer_id": "customers", "country_id": "countries",
              "status_code": "statuses"},
       copy=False,  # Perform in-place translation.
   )

This one call replaces the ``.map``, the ``.apply`` ladder, the per-row SQL, *and* the manual f-string. Control the
label shape with the ``fmt`` key under ``[translator]`` (e.g. ``fmt = "{name}"`` for the label only, or ``"{id}:{name}"``
for the default compound form). The ``fmt`` mini-language -- optional ``[...]`` blocks, literal brackets -- is
documented in the :class:`~id_translation.offline.Format` docstring.

5. Let the defaults take over
-----------------------------
The steps above pin every name and placeholder by hand -- the safe choice when retro-fitting a schema you do not
control. Once it works, lean on the behaviour you opted out of: id-translation reads :ref:`names off the translatable
<translation-primer>` (e.g. ``DataFrame`` columns) and :ref:`maps them to sources <mapping-primer>` by heuristic, so a
conventionally-named ``customer_id`` needs no ``names=`` entry. Keep explicit overrides for the irregular cases only.

.. seealso::

   The ``DataFrame`` you just translated is only one of the structures the :mod:`~id_translation.dio` framework handles;
   see the :ref:`table of bundled integrations <io-implementations>` for the full set, from ``dict``\ s and ``list``\ s
   to ``polars`` and ``dask`` frames.

The :doc:`translation-io` system is extensible. You can create your own custom integration, or change how certain
:class:`built-in <.PandasIO>` IO implementations behave by using the `io_kwargs` argument.

Q&A
---
Questions that tend to come up mid-migration.

**What do untranslated IDs look like?**
    Unknown IDs are rendered with a fallback :class:`~id_translation.offline.Format` -- ``'<Failed: id=1>'`` by
    default. Configure it in the :ref:`[unknown_ids] <Section: Unknown IDs>` section, e.g. ``fmt = "Unknown"``, or
    ``fmt = "{id}"`` to leave IDs as-is. Missing IDs (``NaN`` in a ``DataFrame``) are pass-throughs and are never
    translated; a ``None`` in a builtin collection is an ordinary -- unknown -- ID.

**How do I know the migration is complete?**
    Pass :meth:`translate(df, max_fails=0.0) <id_translation.Translator.translate>` while validating;
    :class:`~id_translation.exceptions.TooManyFailedTranslationsError` is raised if any ID fails to resolve. Relax or
    drop the argument (default ``1.0``) once the configuration is trusted.

**A column comes back untranslated -- why?**
    Derived names that fail to map to a source are skipped silently. Call
    :meth:`translator.map(df) <id_translation.Translator.map>` to inspect the name-to-source decision without
    translating, and use :func:`~id_translation.logging.enable_verbose_debug_messages` to see why a match was
    rejected. The :ref:`mapping primer <mapping-primer>` explains the procedure.

**When does fetching happen?**
    On every :meth:`~id_translation.Translator.translate` call, for just the IDs being translated. Read-heavy
    services may prefer :meth:`~id_translation.Translator.go_offline`: it stores a snapshot in memory, after which
    the instance stops fetching entirely and is safe to share between threads.

**The IDs are UUIDs.**
    Set ``enable_uuid_heuristics = true`` under ``[translator]``. IDs that are :class:`~uuid.UUID` in one place and
    strings in another -- or strings in a different case -- will then match anyway.

**A column packs several flags into one ID.**
    Translate composite IDs such as bitmasks with a :class:`~id_translation.transform.BitmaskTransformer`, declared
    in :ref:`config <translator-config-transform>` or passed in code through the ``transformers`` argument of
    :class:`~id_translation.Translator`.
