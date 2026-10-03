"""The theatre lock: one exclusive, cross-process lock per theatre (research R-01, R-02).

An advisory ``flock`` on a file descriptor of the theatre's ``.troupe`` directory itself, so no
file is ever created. The kernel releases it when the descriptor is closed or the process dies,
so a crashed command can never leave a theatre locked. Locks are per open file description:
never take the lock twice in one process (a nested acquire on a new descriptor would deadlock).

``flock`` is used rather than POSIX record locks (``fcntl.lockf``), which are per process and
are released when *any* descriptor of the file is closed. There is no timeout: every holder is
a short session, and ``watch`` never holds the lock while it sleeps.
"""

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from troupe.errors import LoadError


@contextmanager
def theatre_lock(state_dir: Path) -> Iterator[None]:
    """Hold the theatre's exclusive lock for the ``with`` block, waiting for it if needed.

    Raises:
        LoadError: If ``state_dir`` cannot be opened; the message names it.
    """
    try:
        fd = os.open(state_dir, os.O_RDONLY)
    except OSError as err:
        raise LoadError(f"cannot lock {state_dir}: {err.strerror or err}") from err
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # releases the lock
