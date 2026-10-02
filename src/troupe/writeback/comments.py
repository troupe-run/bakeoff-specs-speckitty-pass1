"""End-of-line comments on a changed line (FR-020).

Contract: when a changed value's length changes, the comment on that line moves back to its
previous column; if the new value reaches that column, exactly one space separates value and
comment. No other line changes. Columns count Unicode code points, which are Python ``str``
indices. A TAB before an end-of-line comment is out of contract and not special-cased.
"""

_QUOTES = "'\""
# A quote opens a quoted scalar only where a scalar can start; elsewhere (``it's``) it is text.
_SCALAR_STARTS_AFTER = " \t,[{:"


def find_comment_start(line: str, from_col: int) -> int | None:
    """Return the column of the end-of-line comment's ``#`` at or after ``from_col``, or ``None``.

    ``line`` excludes its line break and ``from_col`` must lie outside any quoted scalar. A ``#``
    outside quotes starts a comment if it is at column 0 or preceded by a space. Inside single
    quotes ``''`` is an escaped quote; inside double quotes ``\\`` escapes the next character.
    """
    quote: str | None = None
    i = from_col
    while i < len(line):
        ch = line[i]
        if quote == "'":
            if ch == "'":
                if line[i + 1 : i + 2] == "'":
                    i += 1
                else:
                    quote = None
        elif quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
        elif ch in _QUOTES and (i == from_col or line[i - 1] in _SCALAR_STARTS_AFTER):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            return i
        i += 1
    return None


def replace_in_line(line: str, start_col: int, end_col: int, new_text: str) -> str:
    """Replace ``line[start_col:end_col]`` with ``new_text``, keeping the comment's column.

    Besides the replaced text, only the run of spaces directly before the comment is resized;
    every other character of the line is kept. ``line`` excludes its line break.
    """
    before, after = line[:start_col], line[end_col:]
    comment_col = find_comment_start(line, end_col)
    if comment_col is None or len(new_text) == end_col - start_col:
        return before + new_text + after
    head = before + new_text + line[end_col:comment_col].rstrip(" ")
    comment = line[comment_col:]
    if len(head) + 1 <= comment_col:
        return head + " " * (comment_col - len(head)) + comment
    return head + " " + comment
