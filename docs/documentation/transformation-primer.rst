.. _transformation-primer:

Transformation primer
=====================
Transformers hook into the translation of a single `source`, adjusting the IDs sent for fetching and the translations
that come back. Use them for what a plain ``{id: translation}`` mapping can't easily express, e.g. composite/bitmask
fields, unit conversions, and similar translation-time computations. A transformer is attached in one of three ways:
provided by the fetcher, declared in TOML, or registered in code; :ref:`transformation-primer-choosing` compares them.

.. seealso::
   If you haven't already, consider checking out the :ref:`translation-primer` before continuing.

Transformer lifecycle
---------------------
A :class:`.Transformer` is called at three points during translation. All three are traced by the bundled
:class:`.BitmaskTransformer`:

.. code-block:: python

   from id_translation import Translator
   from id_translation.transform import BitmaskTransformer

   transformer = BitmaskTransformer(
     joiner=" AND ",
     overrides={0: "NOT_SET", 0b1000: "OVERFLOW"},
   )
   transformers = {"<source>": transformer}
   translator = Translator(fetcher, transformers=transformers)

See :ref:`translator-config-transform` for the equivalent TOML declaration.

* :meth:`~.Transformer.update_ids`: called just before IDs are fetched (:attr:`~.Translator.online` only). Translating
  ``(0, 5, 8)`` also fetches ``1`` and ``4``, since ``5`` decomposes into them.
* :meth:`~.Transformer.update_translations`: called once translations are back, but before use. Here that's just
  ``overrides`` stamping ``0`` and ``8``. ``5`` has no row of its own, so it's still missing at this point.
* :meth:`~.Transformer.try_add_missing_key`: called per lookup for an ID with no translation yet. ``5`` is looked up
  here: its ``1``/``4`` parts are already known, so they're joined on demand.

.. code-block:: python

   translator.translate((0, 5, 8), names="<source>")
   ("NOT_SET", "1:name-of-1 AND 4:name-of-4", "OVERFLOW")

Transformers are **persistent** (they outlive individual calls) and should be **idempotent**, since these methods are
not necessarily called in pairs.

.. important::

   ``update_ids`` is **not** called while :meth:`working offline <.Translator.go_offline>`. Both
   ``try_add_missing_key`` and ``update_translations`` are called offline as well, and should produce a correct
   result from :attr:`cached <.Translator.cache>` components.

For example, the ``BitmaskTransformer`` relies on the ``update_ids()`` step to
:meth:`decompose <.BitmaskTransformer.decompose_bitmask>` IDs into the base-2 components it needs. To translate bitmasks
offline, call :meth:`.Translator.go_offline` with the IDs that will be translated, or nothing to fetch everything. A
transformer added after ``go_offline()``, e.g. through ``copy(transformers=...)``, misses that fetch.

.. _transformation-primer-chaining:

Chaining transformers
---------------------
A source may have more than one translation-time concern (a bitmask to decompose, a label to redact), so it may have any
number of transformers. The :class:`.Translator` runs them as one :class:`chained stack <.TransformerStack>`.

Run order
~~~~~~~~~
Members come from three places, first to last:

1. The fetcher that serves the `source`: :meth:`.Fetcher.get_transformer`, then its
   :ref:`[fetching.transform] section <translator-config-transform>`. These run first, collected once by the first
   :meth:`~.Translator.initialize_sources` call.
2. The main file's :ref:`[transform] section <translator-config-transform>`, in declaration order.
3. Code, via the ``transformers`` constructor argument or :meth:`~.Translator.register_transformer`, in the order the
   calls are made. Use ``on_existing='append'`` to build a stack.

Each lifecycle method delegates to every member in turn: *all* members' ``update_ids`` run before *any* member's
``update_translations``. Within a method, each member sees what came before, and may overwrite it.

.. note::

   The same transformer may run twice: duplicates (matched by identity, then ``__eq__``) aren't collapsed when
   chaining, and a warning is emitted.

Continuing the ``BitmaskTransformer`` example above, chain on a second transformer that redacts one translation:

.. code-block:: python

   from id_translation.transform.types import Transformer

   class RedactOverflow(Transformer[int]):
       # update_ids()/try_add_missing_key(): inherited no-ops.
       def update_translations(self, translations: dict[int, str]) -> None:
           for id, value in translations.items():
               if value == "OVERFLOW":
                   translations[id] = "REDACTED"

Give both to a new ``Translator``, in order:

.. code-block:: python

   translator = Translator(
       fetcher,
       transformers={"<source>": [transformer, RedactOverflow()]},
   )

``RedactOverflow`` runs second and overwrites the result:

.. code-block:: python

   translator.translate((0, 5, 8), names="<source>")
   ("NOT_SET", "1:name-of-1 AND 4:name-of-4", "REDACTED")

:meth:`~.Translator.register_transformer` with ``on_existing='append'`` builds the same stack on an instance that has
not :ref:`settled <transformation-primer-settling>` yet. It cannot be used on the ``translator`` above: translating it
closed registration.

.. _transformation-primer-settling:

Settling: when registration closes
----------------------------------
Transformers are open for registration until the ``Translator`` initializes its sources, and fixed afterwards.
Settling does two things: it drops transformers for sources nothing serves, naming them in a warning, and it closes
the set. :meth:`~.Translator.register_transformer` raises from then on, and :attr:`~.Translator.transformers` raises
until then, since an unsettled set can name sources that will be dropped and lack the ones the fetcher has yet to
provide.

It happens at the first :meth:`~.Translator.initialize_sources` call, including the implicit one in methods that need
the sources, such as :meth:`~.Translator.translate` and :meth:`~.Translator.map`. It also happens at
:meth:`~.Translator.go_offline`, and at construction for a ``Translator`` built from inline data. Concurrent
first calls settle the transformers once, under the instance's lock; see :ref:`thread-safety`.

To register after the fetcher's transformers are in place, for example to replace one, initialize without settling:

.. code-block:: python

   translator.initialize_sources(settle_transformers=False)
   translator.register_transformer("<source>", RedactOverflow(), on_existing="overwrite")

The next ``initialize_sources()`` call settles them, whether explicit or implicit.

:meth:`~.Translator.go_offline` also drops transformers for sources outside its snapshot, without a warning, since
the caller chose that subset.

A copy of a settled ``Translator`` keeps its transformers; ``translator.copy(transformers=...)`` replaces the set on the
copy, which is how to adjust one. The copy of an *offline* instance is settled again on construction.

.. _transformation-primer-choosing:

Fetcher, configuration, or code?
--------------------------------
The three routes are not interchangeable. Pick by what the transformer needs to know, by which fetcher it belongs
to, and by what must remain true once that fetcher is discarded.

The fetcher
~~~~~~~~~~~
Prefer :meth:`.Fetcher.get_transformer` when the transformer is a property of the data itself: a bitmask column stays
a bitmask no matter who reads it. This route and a ``[fetching.transform]`` section follow source conflict resolution,
since a :class:`.MultiFetcher` asks the child that actually serves the `source`. An outranked child's transformer
therefore never touches the winner's data. Overrides need no `source` name, and travel with the fetcher into any composition.

Configuration
~~~~~~~~~~~~~
Prefer a :ref:`[transform] section <translator-config-transform>` for policy that belongs to a deployment rather
than to the code, such as an override table that differs per environment. The declaration then travels with the
configuration, and changes without touching the code that builds the ``Translator``.

There are two scopes. A ``[fetching.transform]`` section belongs to the fetcher declared next to it, and applies only
to sources that fetcher serves: it goes wherever the fetcher goes, so a fetcher that is discarded or loses a source
conflict takes its sections with it. The main file's top-level ``[transform]`` section belongs to the ``Translator``
and applies to the named `source` whichever fetcher serves it.

Two consequences:

* **An auxiliary file cannot transform another fetcher's sources.** Several auxiliary files may each declare a section
  for one `source`; only the fetcher that serves it applies its own. Use the main file for policy that spans fetchers.
* **Interpolation cannot add or remove a section.** ``${VAR}`` reaches section keys and init arguments alike, but a
  policy that is enabled in one environment and disabled in another is not expressible this way.

Code
~~~~
Prefer the ``transformers`` argument or :meth:`~.Translator.register_transformer` when:

* **The policy depends on something only the caller knows**, such as a deployment environment argument or an
  authorization check, resolved after the configuration is read.
* **The sources cannot be named in advance.** A ``[transform.'<source>']`` section needs the name up front, whereas
  a loop over :attr:`~.Translator.sources` does not.
* **It must survive a lost source conflict.** Fetcher-provided transformers and ``[fetching.transform]`` sections are
  scoped to the fetcher that serves the `source`. A registration made in code, like the main file's ``[transform]``,
  is never dropped this way.

A ``create_translator()`` factory in the style of the :ref:`migration-guide` can mask certain values in production only,
reusing ``RedactOverflow`` from above:

.. code-block:: python

   import os

   from id_translation import Translator

   def create_translator(env: str = "dev") -> Translator:
       os.environ["APP_ENV"] = env
       t = Translator.from_config("config/main.toml")
       if env == "production":
           for source in t.sources:
               t.register_transformer(source, RedactOverflow(), on_existing="append")
       return t.initialize_sources()

Reading :attr:`~.Translator.sources` performs source discovery, which is why the loop sees them without a separate
call. The fetcher's own transformers are collected later, by ``initialize_sources()``, and always chain ahead of
code registrations, so registering early does not put a transformer first.

Three details are load-bearing:

* ``initialize_sources()`` settles the transformers, so the returned instance is safe to share and registering on it
  raises. They settle at first use anyway; doing it here means nothing is left for a concurrent first call. It must
  come after the registrations, and it runs the :meth:`.Fetcher.get_transformer` pass before settling, so the fetcher's
  own answer is never locked out.
* ``on_existing`` must be given, since it defaults to ``'raise'``. A `source` already covered by the main file's
  ``[transform]`` would otherwise raise :class:`.TransformerConflictError`. What the fetcher provides, including its
  ``[fetching.transform]`` section, is not registered yet at this point, so it cannot conflict here, and arrives
  ahead of this registration when it does.
* ``RedactOverflow()`` is constructed once per `source`. Hoisting it out of the loop shares a single instance, and
  with it a single piece of state, across every `source`.
