.. _transformation-primer:

Transformation primer
=====================
Transformers hook into the translation of a single `source`, adjusting the IDs sent for fetching and the translations
that come back. Use them for what a plain ``{id: translation}`` mapping can't easily express, e.g. composite/bitmask
fields, unit conversions, and similar translation-time computations.

.. seealso::
   If you haven't already, consider checking out the :ref:`translation-primer` before continuing.

Transformer lifecycle
---------------------
A :class:`.Transformer` is called at three points during translation. All three are traced by the bundled
:class:`.BitmaskTransformer`:

.. code-block:: python

   from id_translation.transform import BitmaskTransformer

   transformer = BitmaskTransformer(
     joiner=" AND ",
     overrides={0: "NOT_SET", 0b1000: "OVERFLOW"},
   )
   transformers = {"<source>": transformer}

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

.. _transformation-primer-chaining:

Chaining transformers
---------------------
A source may have more than one translation-time concern (a bitmask to decompose, a label to redact), so it may have any
number of transformers. The :class:`.Translator` runs them as one :class:`chained stack <.TransformerStack>`.

Run order
~~~~~~~~~
Members come from three places, first to last:

1. The fetcher, via :meth:`.Fetcher.get_transformer`. These run first, collected once by the first
   :meth:`~.Translator.initialize_sources` call.
2. Configuration, via :ref:`[transform] sections <translator-config-transform>`. Sections run in declaration order
   within a file; auxiliary fetcher files run before the main file.
3. Code, via the ``transformers`` constructor argument or :meth:`~.Translator.register_transformer`, in the order the
   calls are made. Use ``on_existing='append'`` to build a stack.

Each lifecycle method delegates to every member in turn: *all* members' ``update_ids`` run before *any* member's
``update_translations``. Within a method, each member sees what came before, and may overwrite it.

.. note::

   The same transformer may run twice: duplicates (matched by identity, then ``__eq__``) aren't collapsed when
   chaining, and a warning is emitted. A fetcher-provided transformer is the exception; one that is already in the
   chain is not added a second time.

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
       fetcher, transformers={"<source>": [transformer, RedactOverflow()]}
   )

``RedactOverflow`` runs second and overwrites the result:

.. code-block:: python

   translator.translate((0, 5, 8), names="<source>")
   ("NOT_SET", "1:name-of-1 AND 4:name-of-4", "REDACTED")

:meth:`~.Translator.register_transformer` with ``on_existing='append'`` builds the same stack on an existing instance.

Every route above already normalizes what it's given through :func:`.as_transformer`. Reach for it directly only if you
need the combined transformer itself.

.. _transformation-primer-window:

Registration window
-------------------
Transformers stay open for registration for the lifetime of the ``Translator``.
:meth:`~.Translator.register_transformer` works before the first translation and after it, and on an instance that has
gone :meth:`offline <.Translator.go_offline>`. A registration naming a `source` that nothing serves is kept, and warns.

That freedom is not thread safe. :meth:`~.Translator.register_transformer` mutates state the instance shares with every
caller, including the :attr:`~.Translator.cache` that :meth:`~.Translator.go_offline` leaves behind, so finish
registering before the instance is shared. See :ref:`thread-safety` for the wider picture.

.. _transformation-primer-choosing:

Choosing a route
----------------
The three routes are not interchangeable. Pick by what the transformer needs to know, by which fetcher it belongs
to, and by what must remain true once that fetcher is discarded.

The fetcher
~~~~~~~~~~~
Prefer :meth:`.Fetcher.get_transformer` when the transformer is a property of the data itself: a bitmask column stays
a bitmask no matter who reads it. This is the only route that follows source conflict resolution, since a
:class:`.MultiFetcher` asks the child that actually serves the `source`. An outranked child's transformer therefore
never touches the winner's data. Overrides need no `source` name, and travel with the fetcher into any composition.

Configuration
~~~~~~~~~~~~~
Prefer a :ref:`[transform] section <translator-config-transform>` for policy that belongs to a deployment rather
than to the code, such as an override table that differs per environment. The declaration then travels with the
configuration, and changes without touching the code that builds the ``Translator``.

A section belongs to the ``Translator``, not to the file it was read from: it applies to the named `source`
whichever fetcher serves it, so the file decides when it runs, not whether it applies. The exception is the
:ref:`initialization discard <optional-fetchers>`, where a fetcher that fails to build takes its sections with it.

Three consequences:

* **Two auxiliary files may both claim one `source`.** Their sections chain, in the order the files are read.
  Auxiliary files run before the main file.
* **A lost source conflict does not drop the section.** When the declaring file's own fetcher claimed the `source`
  and was outranked, the section still applies, to the winner's data. Declare it beside the fetcher you mean to
  describe, or in the main file.
* **Interpolation cannot add or remove a section.** ``${VAR}`` reaches section keys and init arguments alike, but a
  policy that is enabled in one environment and disabled in another is not expressible this way.

Code
~~~~
Prefer the ``transformers`` argument or :meth:`~.Translator.register_transformer` when:

* **The policy depends on something only the caller knows**, such as a deployment environment argument or an
  authorization check, resolved after the configuration is read.
* **The sources cannot be named in advance.** A ``[transform.'<source>']`` section needs the name up front, whereas
  a loop over :attr:`~.Translator.sources` does not.
* **It must not be tied to one fetcher.** A fetcher-provided transformer is scoped to the fetcher that serves the
  `source`, and goes when that fetcher does. A registration made in code outlives any single fetcher.

Continuing the ``APP_ENV`` factory from the :ref:`migration-guide`, mask certain values in production only:

.. code-block:: python

   def create_translator(env: str = "dev") -> Translator:
       os.environ["APP_ENV"] = env
       t = Translator.from_config(...)
       if env == "production":
           for source in t.sources:
               t.register_transformer(source, RedactOverflow(), on_existing="append")
       return t

Two details are load-bearing:

* ``on_existing`` must be given, since it defaults to ``'raise'``. A `source` already covered by configuration would
  otherwise raise :class:`.TransformerConflictError`. What the fetcher provides is not registered yet at this point,
  so it cannot conflict here, and arrives ahead of this registration when it does.
* ``RedactOverflow()`` is constructed once per `source`. Hoisting it out of the loop shares a single instance, and
  with it a single piece of state, across every `source`.

Reading :attr:`~.Translator.sources` performs source discovery, which is why the loop sees them without a separate
call. Registering before that pass runs does not put the transformer first: a fetcher describes the source it
serves, so its own answer is chained ahead whenever it arrives.

.. warning::

   Register before the ``Translator`` is shared (see :ref:`thread-safety`), and before it goes offline. Since
   ``update_ids`` never runs offline, a transformer that widens the fetch, as :class:`.BitmaskTransformer` does,
   silently finds nothing to work with unless every component is already cached. A ``go_offline()`` call with no
   `translatable` fetches everything and so qualifies; one given a `translatable` fetches only what it needs.
