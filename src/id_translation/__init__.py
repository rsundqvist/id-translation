"""Translation of IDs with flexible formatting and name matching.

For an introduction to translation, see :ref:`translation-primer` and :ref:`mapping-primer`.

Environment variables
---------------------
.. envvar:: ID_TRANSLATION_DISABLED

   Global switch. When ``true``, the :meth:`Translator.translate`-method returns immediately.

   .. warning:: When set, IDs are not converted to :py:class:`str`. Type hints may be wrong.

.. envvar:: ID_TRANSLATION_SUPPRESS_OPTIONAL_FETCHER_INIT_ERRORS

   Global switch. Set to ``true`` (not recommended) to allow the :meth:`~id_translation.toml.TranslatorFactory` to
   discard `optional` fetchers that raise when imported or initialized.
   See the `documentation <../documentation/translator-config.html#optional-fetchers>`__ for details.

.. envvar:: ID_TRANSLATION_VERBOSE

   Global switch. Set to ``true`` to overwrite the default :data:`~.logging.ENABLE_VERBOSE_LOGGING` value. Note that
   this variable is only read once (on module import). See the :doc:`documentation </documentation/translation-logging>`
   for details.
"""

from ._translator import Translator

__all__ = [
    "Translator",
    "__version__",  # Make MyPy happy
]

__version__ = "1.0.4"
