"""Error hierarchy and the single place where CLI exit codes are decided.

Every contracted failure is a ``TroupeError`` subclass whose ``exit_code`` is the code the CLI
returns. Constructors take the complete, user-facing message; callers format it, and it must
name the offending configuration path (e.g. ``model.temperature``) or file (absolute or
theatre-relative path), so the user can see where the problem is (TROUPE-003).
"""

from typing import ClassVar


class TroupeError(Exception):
    """Base for every contracted failure; carries the user-facing message."""

    exit_code: ClassVar[int] = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(TroupeError):
    """Malformed invocation or unparsable VALUE."""

    exit_code = 2


class WriteRefused(TroupeError):
    """A write was refused and no file was changed."""

    exit_code = 3


class LoadError(TroupeError):
    """The configuration cannot be loaded."""

    exit_code = 4


class PathError(TroupeError):
    """A configuration path was not found or names the wrong kind of node."""

    exit_code = 5


class FetchError(LoadError):
    """A remote include could not be fetched; the message names the URL (TROUPE-003).

    ``url`` and ``reason`` are kept separately so the loader can re-raise with the including
    file and the configuration path added: ``cannot fetch {url} (included from ..., at ...):
    {reason}`` (contracts/cli.md). ``url`` is a plain ``str`` so this module stays free of
    ``troupe`` imports.
    """

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"cannot fetch {url}: {reason}")
        self.url = url
        self.reason = reason
