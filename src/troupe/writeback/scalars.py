"""Scalar quoting: representability, style choice and rendering (FR-015, research R-10).

Contract (FR-015): a changed scalar keeps its quoting style if that style can represent the new
value; otherwise plain if possible, else single-quoted, else double-quoted. A new key or new string
value copies the preceding sibling's style; with no sibling, plain or the minimal quoting the text
needs. Callers express both rules through ``preferred`` (the current or sibling style, or
``None``). A double-quoted scalar escapes only ``\\``, ``"`` and control characters; everything else
is written literally. Non-string values are always written plain in their YAML 1.2 core canonical
form, because quoting them would turn them into strings.
"""

import math
from typing import Literal

from troupe import yamlcore
from troupe.errors import LoadError
from troupe.tree import Scalar
from troupe.yamlcore import RawMapping, RawScalar, RawSequence

Context = Literal["block", "flow"]
QuoteStyle = Literal["plain", "single", "double"]

_STYLE_ORDER: tuple[QuoteStyle, ...] = ("plain", "single", "double")
# Characters that always start something other than a plain scalar.
_PLAIN_FIRST_FORBIDDEN = frozenset(",[]{}#&*!|>'\"%@`")
# Indicators that may start a plain scalar only when followed by a non-space character ("-v").
_PLAIN_FIRST_IF_FOLLOWED = frozenset("-?:")
# YAML-printable characters this module still never writes literally outside double quotes:
# U+0085/U+2028/U+2029 (ruamel's scanner treats them as line breaks) and U+FEFF (byte order mark).
_LITERAL_REFUSED = frozenset("\x85\u2028\u2029\ufeff")
_FLOW_INDICATORS = frozenset(",[]{}")
_DOCUMENT_MARKERS = ("---", "...")
_DOUBLE_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\0": "\\0",
    "\a": "\\a",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\v": "\\v",
    "\f": "\\f",
    "\r": "\\r",
    "\x1b": "\\e",
    "\x85": "\\N",
    "\u2028": "\\L",
    "\u2029": "\\P",
}


def can_plain(s: str, context: Context) -> bool:
    """Return whether ``s`` can be written as a plain scalar and read back as the same string.

    Conservative syntactic rules come first; then the text must resolve to a string under the
    YAML 1.2 core schema (so ``true``, ``0.2``, ``null`` are refused) and composing it in its
    context must yield a plain scalar with exactly this text.
    """
    if not s or s[0].isspace() or s[-1].isspace() or "\t" in s or not can_single(s):
        # Conservative: no leading/trailing whitespace of any kind (NBSP, U+3000 included), no tab.
        return False
    if s[0] in _PLAIN_FIRST_FORBIDDEN or s.startswith(_DOCUMENT_MARKERS):
        return False
    if s[0] in _PLAIN_FIRST_IF_FOLLOWED and (len(s) == 1 or s[1] == " "):
        return False
    if ": " in s or " #" in s or s.endswith(":"):
        return False
    if context == "flow" and any(ch in _FLOW_INDICATORS for ch in s):
        return False
    resolved = yamlcore.resolve_plain(s)
    if not isinstance(resolved, str) or resolved != s:
        return False
    return _round_trips_plain(s, context)


def can_single(s: str) -> bool:
    """Return whether ``s`` can be single-quoted: no line breaks, nothing that needs escaping.

    Accepts tab and every YAML 1.2 ``c-printable`` character except line breaks and the
    characters in ``_LITERAL_REFUSED``.
    """
    return all(ch == "\t" or _is_printable_non_break(ch) for ch in s)


def choose_style(s: str, preferred: QuoteStyle | None, context: Context) -> QuoteStyle:
    """Return ``preferred`` if it can represent ``s``, else the first of plain, single, double.

    Args:
        s: The string to write.
        preferred: The scalar's current style (changed value), the preceding sibling's style (new
            key or value), or ``None`` (no sibling).
        context: Whether the scalar sits in a block collection or inside ``[...]``/``{...}``.
    """
    if preferred is not None and _can_represent(s, preferred, context):
        return preferred
    return next(style for style in _STYLE_ORDER if _can_represent(s, style, context))


def render_string(s: str, style: QuoteStyle) -> str:
    """Render ``s`` in ``style``; the caller has checked that the style can represent it."""
    if style == "plain":
        return s
    if style == "single":
        return "'" + s.replace("'", "''") + "'"
    return '"' + "".join(_escape_double(ch) for ch in s) + '"'


def render_nonstring(v: int | float | bool | None) -> str:
    """Render a non-string scalar as its plain YAML 1.2 core canonical text (research R-10).

    Raises:
        ValueError: If the text would not read back as ``v`` (cannot happen for Python floats;
            guards the rendering rule).
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if math.isnan(v):
        return ".nan"
    if math.isinf(v):
        return ".inf" if v > 0 else "-.inf"
    text = repr(v)
    if yamlcore.resolve_plain(text) != v:
        raise ValueError(f"float {v!r} has no plain YAML 1.2 core rendering")
    return text


def render_scalar(v: Scalar, preferred: QuoteStyle | None, context: Context) -> str:
    """Render any scalar: strings in the chosen quoting style, everything else plain."""
    if isinstance(v, str):
        return render_string(v, choose_style(v, preferred, context))
    return render_nonstring(v)


def _can_represent(s: str, style: QuoteStyle, context: Context) -> bool:
    if style == "plain":
        return can_plain(s, context)
    if style == "single":
        return can_single(s)
    return True


def _round_trips_plain(s: str, context: Context) -> bool:
    document = f"k: {s}\n" if context == "block" else f"[{s}]\n"
    try:
        root = yamlcore.compose(document, "<scalar check>")
    except LoadError:
        return False
    if isinstance(root, RawMapping) and len(root.pairs) == 1:
        scalar = root.pairs[0][1]
    elif isinstance(root, RawSequence) and len(root.items) == 1:
        scalar = root.items[0]
    else:
        return False
    return isinstance(scalar, RawScalar) and scalar.style == "plain" and scalar.text == s


def _is_printable_non_break(ch: str) -> bool:
    """YAML 1.2 ``c-printable`` minus tab, line breaks and ``_LITERAL_REFUSED``."""
    code = ord(ch)
    if ch in _LITERAL_REFUSED:
        return False
    return (
        0x20 <= code <= 0x7E
        or 0xA0 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def _escape_double(ch: str) -> str:
    named = _DOUBLE_ESCAPES.get(ch)
    if named is not None:
        return named
    code = ord(ch)
    if code < 0x20 or 0x7F <= code <= 0x9F:
        return f"\\x{code:02x}"
    if 0xD800 <= code <= 0xDFFF or code in (0xFFFE, 0xFFFF):
        # Not YAML-printable at all; writing it literally would make the file unreadable.
        return f"\\u{code:04x}"
    return ch
