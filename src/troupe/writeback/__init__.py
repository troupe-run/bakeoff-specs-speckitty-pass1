"""Byte-surgical write-back: never re-serialise a file, splice only the replacement text.

Decision DM-01M3XGW5Z97R8VC909JF3TVPTT (research R-01): renderers look at the original text and
the spans recorded in the SourceTree and return ``TextEdit`` values, each replacing one span of a
``SourceFile.text`` with new text. ``apply_edits`` splices them into the original text, so every
byte outside the edited spans is identical by construction. Only once every edit for every file
has been planned and verified are the new texts written, atomically, by ``fileio.write_files``
(NFR-002).

Building blocks:

- ``fileio``: newline detection, CRLF conversion and atomic file replacement.
- ``scalars``: which quoting style can represent a string, style choice and rendering (FR-015).
- ``comments``: rebuilding one changed line so its end-of-line comment keeps its column (FR-020).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise


@dataclass(frozen=True)
class TextEdit:
    """Replace ``text[start:end]`` of one file's text with ``text``.

    Attributes:
        start: Code-point index into ``SourceFile.text``.
        end: Exclusive end index; ``start == end`` is a pure insertion.
        text: The replacement text.
    """

    start: int
    end: int
    text: str


def apply_edits(text: str, edits: Sequence[TextEdit]) -> str:
    """Return ``text`` with every edit spliced in; indices refer to the original ``text``.

    Edits may be given in any order. Two insertions at the same index are applied in the order
    given (the first one ends up first).

    Raises:
        ValueError: If an edit is out of bounds or two edits overlap. This is a programming error
            in a renderer, not a contract error.
    """
    ordered = sorted(edits, key=lambda edit: (edit.start, edit.end))
    for edit in ordered:
        if not 0 <= edit.start <= edit.end <= len(text):
            raise ValueError(f"edit {edit} is out of bounds for a text of length {len(text)}")
    for previous, current in pairwise(ordered):
        if current.start < previous.end:
            raise ValueError(f"overlapping edits {previous} and {current}")
    result = text
    for edit in reversed(ordered):
        result = result[: edit.start] + edit.text + result[edit.end :]
    return result
