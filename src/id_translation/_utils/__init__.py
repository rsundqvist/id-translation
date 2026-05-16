from typing import Any as _Any

DOC_LINK: str

__all__ = [
    "DOC_LINK",
]


def __getattr__(name: str) -> _Any:
    if name == "DOC_LINK":
        from id_translation import __version__  # noqa: PLC0415

        def _is_release(v: str) -> bool:
            parts = v.split(".")
            return len(parts) == 3 and all(map(str.isdigit, parts))  # noqa: PLR2004

        version = f"v{__version__}" if _is_release(__version__) else "latest"

        return f"https://id-translation.readthedocs.io/en/{version}/"

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
