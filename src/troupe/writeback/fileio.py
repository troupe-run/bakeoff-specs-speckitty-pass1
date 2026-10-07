"""Newline handling and atomic file replacement (research R-05, R-12, R-14; NFR-002).

Texts are always written as UTF-8 bytes, never through text mode, so CRLF line endings and a
leading BOM (kept as U+FEFF in ``SourceFile.text``) reach the disk exactly as they are in the text.
"""

import contextlib
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

from troupe.errors import WriteRefused
from troupe.tree import SourceFile

CRLF = "\r\n"
LF = "\n"


def detect_newline(text: str) -> str:
    """Return the line ending for new lines: ``"\\r\\n"`` if the first line break is CRLF."""
    first = text.find(LF)
    return CRLF if first > 0 and text[first - 1] == "\r" else LF


def uses_crlf(text: str) -> bool:
    """Return whether ``text`` contains a CRLF line ending anywhere (FR-010 text includes)."""
    return CRLF in text


def to_crlf(value: str) -> str:
    """Turn every ``"\\n"`` not already preceded by ``"\\r"`` into ``"\\r\\n"``."""
    return value.replace(CRLF, LF).replace(LF, CRLF)


def atomic_write(path: Path, text: str) -> None:
    """Replace the existing file ``path`` with ``text`` (UTF-8) all-or-nothing.

    A temporary sibling file is written, flushed and fsynced, given the original's permission
    bits, then renamed over ``path``. If anything fails, the temporary file is removed and the
    original is left untouched. ``path`` should be resolved (no symlink), as ``SourceFile.path``
    is; replacing a symlink would replace the link, not its target.

    Raises:
        OSError: If the file cannot be written; ``path`` is unchanged.
    """
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise
    _fsync_directory(path.parent)


def write_files(new_texts: Mapping[SourceFile, str]) -> None:
    """Atomically write each file whose new text differs from the text it was loaded with.

    Callers pass complete new texts only after every edit has been planned and verified, so a
    refused command never reaches this point (NFR-002). Unchanged files are not touched at all.

    Remote content is never written (spec S-4; research R-7). Every source is checked before any
    file is written, so a plan holding a remote source changes no file at all. This is the last
    safety net: the write-back refusals mean it should never fire.

    Raises:
        WriteRefused: If any source in ``new_texts`` is remote; no file changed.
    """
    local: list[tuple[Path, str]] = []
    for source, text in new_texts.items():
        if not isinstance(source.path, Path):
            raise WriteRefused(
                f"cannot write {source.path}: it is remote content, which troupe never changes;"
                " no file changed"
            )
        if text != source.text:
            local.append((source.path, text))
    for path, text in local:
        atomic_write(path, text)


def _fsync_directory(directory: Path) -> None:
    """Make the rename durable; best effort, since the replacement itself already happened."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)
