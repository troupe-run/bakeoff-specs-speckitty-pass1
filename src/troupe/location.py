"""Where a configuration source lives: a local ``Path`` or a remote ``Url`` (research R-1).

This module deliberately imports nothing from ``troupe``. ``tree.py``, ``includes.py`` and
``remote.py`` all import it, so it must sit at the bottom of the import graph; any ``troupe``
import here would risk an import cycle.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Url:
    """An absolute http(s) URL, as written or as resolved by ``urljoin`` (spec S-1).

    The text is never normalised (no lower-casing, no trailing-slash changes): equality and
    hashing go by the exact text, and messages show exactly what the user wrote or what
    ``urljoin`` produced. ``str(url)`` is that text, so an f-string message such as
    ``f"cannot load {file.path}: ..."`` prints the URL unchanged when ``path`` is a ``Url``.
    """

    text: str

    def __str__(self) -> str:
        return self.text


type Location = Path | Url
