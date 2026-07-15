"""Sphinx configuration."""

import os
from datetime import UTC, datetime
from zipfile import ZipFile

from docutils.nodes import Text, reference

if True:  # E402 hack
    os.environ["SPHINX_BUILD"] = "true"

# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
import shutil
from importlib import metadata

from rics._internal_support import make_toc_tree_titles_shorter, myst_parser_markdown_doc_refs
from rics._internal_support.changelog import split_changelog

import id_translation
from id_translation.fetching import AbstractFetcher

myst_parser_markdown_doc_refs.patch()
make_toc_tree_titles_shorter.patch()

if not os.path.exists("api"):
    os.mkdir("api")
shutil.copyfile("translator.rst", "api/translator.rst")


def callback(_app, _env, node, _contnode):  # noqa
    reftarget = node.get("reftarget")

    dio = {
        "id_translation.dio.default._sequence.SequenceT": "id_translation.dio.default.SequenceIO",
    }

    for type_var, owner in dio.items():
        if reftarget == type_var:
            name = reftarget.rpartition(".")[-1]
            reftarget = owner + "." + name
            ans_hax = reference(refuri="id_translation.dio.default.html#" + reftarget, reftitle=reftarget)
            ans_hax.children.append(Text(name))
            return ans_hax

    return None


def skip_member(app, what, name, obj, skip, options):
    if obj is AbstractFetcher._initialize_sources:
        return False
    return skip or name.startswith("_")


def forbid_downstream_unresolvable_references(app, env):
    """Warn on py-domain references that may resolve here, but not in downstream projects.

    Docstrings are inherited, copied, and wrapped by downstream projects (see e.g. the id-translation-project
    template). There, relative references such as ``:class:`.Format``` (including bare exception names in ``Raises:``
    sections) can only be resolved by intersphinx, which requires an exact fully-qualified match against a documented
    name. Enforce that invariant for all py-domain references in docstrings; narrative documents are only rendered
    here, and may use ``py:currentmodule``-relative references. The build runs with ``-W``, so violations fail it.
    """
    import builtins

    from sphinx import addnodes
    from sphinx.ext.intersphinx import InventoryAdapter
    from sphinx.util.logging import getLogger

    logger = getLogger(__name__)

    domain = env.get_domain("py")
    external = {name for objects in InventoryAdapter(env).main_inventory.values() for name in objects}

    def is_exact_match(target):
        return target in domain.objects or target in domain.modules or target in external

    def source_of(node):
        while node is not None:
            if node.source:
                return node.source
            node = node.parent
        return ""

    for docname in sorted(env.found_docs):
        for node in env.get_doctree(docname).findall(addnodes.pending_xref):
            if node.get("refdomain") != "py":
                continue
            if "docstring of " not in source_of(node):
                continue
            target = node.get("reftarget", "")
            if is_exact_match(target) or hasattr(builtins, target):
                continue
            msg = f"Reference {target!r} does not exactly match any documented name, so it will not resolve in"
            logger.warning(msg + " downstream projects. Use a fully qualified name.", location=node)


def setup(app):  # noqa
    app.connect("missing-reference", callback)
    app.connect("autodoc-skip-member", skip_member)
    app.connect("build-finished", publish_jsonschema)
    app.connect("env-check-consistency", forbid_downstream_unresolvable_references)
    add_custom_lexer()


def publish_jsonschema(app, exception):
    """Publish the config JSON schemas to the doc root.

    Emits the main, fetcher and metaconf schemas at clean, versioned URLs
    (``.../en/<version>/<name>.schema.json``) that config files reference via
    SchemaStore / ``#:schema`` / a JSON Schema mapping. The fetcher schema is derived
    from the main one (single source); see ``id_translation.toml._schema``.
    """
    if exception is not None:
        return
    import json

    from id_translation.toml._schema import published_schemas

    for filename, schema in published_schemas().items():
        with open(os.path.join(app.outdir, filename), "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
            f.write("\n")


def add_custom_lexer():
    """For `dvdrental-info-messages.log`.

    The lexer itself doesn't make (much) sense.
    """
    from log_lexer import LogLexer
    from sphinx.highlighting import lexers

    lexers["log"] = LogLexer()


# If extensions (or modules to document with autodoc) are in another
# directory, add these directories to sys.path here. If the directory is
# relative to the documentation root, use os.path.abspath to make it
# absolute, like shown here.
#


# -- Project information -------------------------------------------------------

# General information about the project.

_metadata = metadata.metadata(id_translation.__name__)
project = _metadata["Name"]
copyright = _metadata["Author"] + f", {datetime.now(UTC).year}"
author = _metadata["Author"]
# The version info for the project you're documenting, acts as replacement
# for |version| and |release|, also used in various other places throughout
# the built documents.
#
# The full version, including alpha/beta/rc tags.
release = id_translation.__version__
# The short X.Y version.
version = ".".join(release.split(".")[:2])

rics_docs = f"https://rics.readthedocs.io/en/{'latest' if 'dev' in release else 'stable'}/"
# -- General configuration -----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosectionlabel",
    "nbsphinx",
    "sphinx.ext.mathjax",
    "myst_parser",
    "sphinx_llm.txt",
]
# Summary line for the generated llms.txt index. Without this, the extension falls back to the
# package metadata Description (the full README), which bloats the top of the index.
llms_txt_description = (
    "Translate opaque database IDs (int, str, UUID) into human-readable labels. Configurable via TOML, "
    "with pluggable fetchers for SQL and file/in-memory sources, automatic name-to-source and placeholder "
    "mapping, and integrations for pandas, polars, pyarrow, and dask."
)
autosummary_ignore_module_all = True
autosummary_imported_members = True
# autoclass_content = "both"  # Add __init__ doc (ie. params) to class summaries
html_show_sourcelink = False  # Remove 'view source code' from top of page (for html, not python)
autodoc_inherit_docstrings = True  # If no docstring, inherit from base class
set_type_checking_flag = True  # Enable 'expensive' imports for sphinx_autodoc_typehints
nbsphinx_allow_errors = True  # Continue through Jupyter errors
# autodoc_typehints = "description" # Sphinx-native method. Not as good as sphinx_autodoc_typehints
add_module_names = False  # Remove namespaces from class/method signatures

suppress_warnings = [
    "autosectionlabel.*",  # https://github.com/sphinx-doc/sphinx/issues/7697
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = [
    "translator.rst",
    "_build",
    "_templates",
    "Thumbs.db",
    ".DS_Store",
    "**.ipynb_checkpoints",
]
# shutil.rmtree("/tmp/example/", ignore_errors=True)  # noqa: 1S108

# -- Options for HTML output ---------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "pydata_sphinx_theme"

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.

html_theme_options = {
    "github_url": "https://github.com/rsundqvist/id-translation",
    "icon_links": [
        {"name": "PyPI", "url": "https://pypi.org/project/id-translation/", "icon": "fa-solid fa-box"},
    ],
    "icon_links_label": "Quick Links",
    "use_edit_page_button": False,
    "navigation_with_keys": False,
    "show_toc_level": 1,
    "navbar_end": ["navbar-icon-links"],  # Dark mode doesn't work properly; disable it
}

# Used by pydata_sphinx_theme. Partially stolen from https://mne.tools/stable/index.html
html_context = {
    "github_user": "rsundqvist",
    "github_repo": "id-translation",
    "github_version": "master",
    "display_github": True,  # Integrate GitHub
    "conf_py_path": "/docs/",  # Path in the checkout to the docs root
    "default_mode": "light",  # Dark mode doesn't work properly; disable it
    "carousel": [
        dict(
            title="Translation primer",
            text="An introduction to the translation process.",
            url="documentation/translation-primer.html",
            img="_images/translation-flow.drawio.png",
        ),
        dict(
            title="Translator Config",
            text="TOML format documentation.",
            url="documentation/translator-config.html",
            img="_static/toml-config.png",
        ),
        dict(
            title="Translator.translate",
            text="Main entry point for translation tasks.",
            url="api/id_translation.Translator.translate.html",
            img="_static/translation.png",
        ),
        dict(
            title="Cookbook",
            text="Like copy-pasting? Me too!",
            url="documentation/examples/notebooks/cookbook/pandas-index.html",
            img="_static/chef.png",
        ),
        dict(
            title="Fetching",
            text="API documentation for SQL and file-system fetching.",
            url="api/id_translation.fetching.html",
            img="https://cdn-icons-png.flaticon.com/512/6486/6486493.png",
        ),
        dict(
            title="RiCS <img src= https://img.shields.io/pypi/v/rics.svg >",
            text=f"Backing library. Original home of the <i>{project}</i> package.",
            url=rics_docs,
            img="https://rics.readthedocs.io/en/stable/_static/logo-text.png",
        ),
    ],
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static", "_images"]
html_css_files = ["style.css"]
html_logo = "logo.png"
html_favicon = "logo-icon.png"

# -- Nitpicky configuration ----------------------------------------------------
nitpicky = True
nitpick_ignore = []
nitpick_ignore_regex = []

# -- Autodoc configuration -----------------------------------------------------
autodoc_typehints = "none"
# Want https://github.com/sphinx-doc/sphinx/issues/10359 to consider setting to
# anything other than none. None might still be better for readability.
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "member-order": "alphabetical",
    "show-inheritance": True,
}

# -- Intersphinx configuration -------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3/", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
    "rics": (rics_docs, None),
    "big_corporation_inc.id_translation": ("https://rsundqvist.github.io/id-translation-project/", None),
    # Integrations
    "pandas": ("http://pandas.pydata.org/pandas-docs/stable/", None),
    "polars": ("https://docs.pola.rs/api/python/stable/", None),
    "dask": ("https://docs.dask.org/en/latest/", None),
}

# -- Gallery configuration -----------------------------------------------------
sphinx_gallery_conf = {
    "sphinx_gallery_conf": "*.png",
    "gallery_dirs": ["_tiles"],
}

# -- Nbsphinx ------------------------------------------------------------------
nbsphinx_execute = "never"
shutil.copytree("../notebooks/demo/", "documentation/examples/notebooks", dirs_exist_ok=True)

# -- Randoms stuff -------------------------------------------------------------
split_changelog("changelog", "../CHANGELOG.md")

root = "documentation/examples/dvdrental"
with ZipFile(f"{root}/dvdrental.zip", "w") as archive:
    archive.write(f"{root}/dvdrental.py", "dvdrental/dvdrental.py")
    archive.write(f"{root}/query.sql", "dvdrental/query.sql")
    archive.write(f"{root}/sql-fetcher.toml", "dvdrental/sql-fetcher.toml")
    archive.write(f"{root}/translation.toml", "dvdrental/translation.toml")

root = "documentation/examples/orm"
with ZipFile(f"{root}/orm.zip", "w") as archive:
    archive.write(f"{root}/main.py", "orm/main.py")
    archive.write(f"{root}/orm_fetcher.py", "orm/orm_fetcher.py")
    archive.write(f"{root}/dvdrental_models.py", "orm/dvdrental_models.py")


def show_first_argument_in_docs():
    from id_translation.toml import TranslatorFactory

    for name in filter(lambda s: s.endswith("_FACTORY"), dir(TranslatorFactory)):
        attr = getattr(TranslatorFactory, name)
        static = staticmethod(attr)
        setattr(TranslatorFactory, name, static)


show_first_argument_in_docs()
