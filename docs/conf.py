"""Sphinx configuration."""
import os
from datetime import datetime, timezone
from zipfile import ZipFile

if True:  # E402 hack
    os.environ["SPHINX_BUILD"] = "true"

# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
import shutil
from importlib import import_module, metadata

from docutils.nodes import Text, reference
from rics._internal_support.changelog import split_changelog

import id_translation

type_modules = (
    "id_translation.types",
    "id_translation.fetching",
    "id_translation.fetching.types",
    "id_translation.mapping.types",
    # rics
    "rics.collections.dicts",
    "rics.collections.misc",
)

for tm in type_modules:
    import_module(tm)


if not os.path.exists("_autosummary"):
    os.mkdir("_autosummary")
shutil.copyfile("translator.rst", "_autosummary/translator.rst")


def monkeypatch_autosummary_toc() -> None:
    from sphinx.addnodes import toctree
    from sphinx.ext.autosummary import Autosummary, autosummary_toc

    original = Autosummary.run

    def make_toc_tree_titles_shorter(self: Autosummary):
        # tocnode['entries'] = [(".".join(docn.partition("/")[-1].split(".")[-2:]), docn) for docn in docnames]
        toc: toctree
        nodes = original(self)

        for node in nodes:
            if isinstance(node, autosummary_toc):
                for toc in node.children:
                    entries = toc["entries"]

                    for i, (title, ref) in enumerate(entries):
                        if ref.endswith("id_translation.Translator"):
                            entries[i] = ("Translator", ref)
                        elif title is None and ref.count(".") > 1:
                            title = ref.partition("id_translation.")[-1]
                            entries[i] = (title, ref)

        return nodes

    Autosummary.run = make_toc_tree_titles_shorter


def callback(_app, _env, node, _contnode):  # noqa
    reftarget = node.get("reftarget")

    # This doesn't actually do anything now, since autodoc_typehints = "none" (see above).
    if reftarget in ("NameType", "SourceType", "IdType"):
        # TODO When are they gonna fix this sh*t? Did they already..?
        #   Special hack for factory.py, which is a public module. And for some
        #   reason that breaks. I've no idea why :')
        reftarget = f"id_translation.types.{reftarget}"

    if reftarget == "id_translation.fetching._sql_fetcher.StatementType":
        reftarget = "id_translation.fetching.SqlFetcher.StatementType"

    if reftarget == "id_translation.mapping.support.Record":
        ans_hax = reference(
            refuri="id_translation.mapping.support.html#id_translation.mapping.support.MatchScores.Record",
            reftitle="Record",
        )
        ans_hax.children.append(Text(reftarget.rpartition(".")[-1]))
        return ans_hax

    for m in type_modules:
        if reftarget.startswith(m):
            ans_hax = reference(refuri=m + ".html#" + reftarget, reftitle=reftarget)
            ans_hax.children.append(Text(reftarget.rpartition(".")[-1]))
            return ans_hax

    return None


def setup(app):  # noqa
    app.connect("missing-reference", callback)  # Fixes linking of typevars
    monkeypatch_autosummary_toc()


# If extensions (or modules to document with autodoc) are in another
# directory, add these directories to sys.path here. If the directory is
# relative to the documentation root, use os.path.abspath to make it
# absolute, like shown here.
#


# -- Project information -------------------------------------------------------

# General information about the project.

_metadata = metadata.metadata(id_translation.__name__)
project = _metadata["Name"]
copyright = _metadata["Author"] + f", {datetime.now(timezone.utc).year}"
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
    "sphinx.ext.autodoc.typehints",
    "sphinx.ext.autosummary",
    "sphinx.ext.viewcode",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosectionlabel",
    "nbsphinx",
    "sphinx.ext.mathjax",
    "myst_parser",
]
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
shutil.rmtree("/tmp/example/", ignore_errors=True)  # noqa: 1S108

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
            url="_autosummary/id_translation.Translator.translate.html",
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
            url="_autosummary/id_translation.fetching.html",
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
nitpick_ignore = [
    ("py:class", "re.Pattern"),
    ("py:class", "module"),
]
nitpick_ignore_regex = [
    ("py:obj", r".*\.Any"),
]

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
    "python": ("https://docs.python.org/3", None),
    "pandas": ("http://pandas.pydata.org/pandas-docs/stable/", None),
    "numpy": ("http://docs.scipy.org/doc/numpy/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/14/", None),
    "matplotlib": ("https://matplotlib.org/stable/", None),
    "rics": (rics_docs, None),
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
