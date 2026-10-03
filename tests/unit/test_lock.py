"""The theatre lock across real processes, probed with a non-blocking ``flock`` (no timing)."""

import fcntl
import os
import selectors
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from troupe.errors import LoadError
from troupe.lock import theatre_lock

_READY_TIMEOUT_SECONDS = 10.0

_HOLD_UNTIL_STDIN_CLOSES = """
import sys
from pathlib import Path
from troupe.lock import theatre_lock

with theatre_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    sys.stdin.read()
"""

_DIE_WHILE_HOLDING = """
import os
import sys
from pathlib import Path
from troupe.lock import theatre_lock

with theatre_lock(Path(sys.argv[1])):
    print("locked", flush=True)
    os._exit(1)
"""


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / ".troupe"
    directory.mkdir()
    return directory


def _is_locked_elsewhere(state_dir: Path) -> bool:
    """Probe the lock without blocking: ``True`` if another open file description holds it."""
    fd = os.open(state_dir, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False
    finally:
        os.close(fd)


def _wait_for_locked(child: subprocess.Popen[bytes]) -> None:
    """Wait (bounded) until the child reports it holds the lock."""
    assert child.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(child.stdout, selectors.EVENT_READ)
        if not selector.select(_READY_TIMEOUT_SECONDS):
            pytest.fail("child did not report holding the lock in time")
    assert child.stdout.readline() == b"locked\n"


@pytest.fixture
def spawn() -> Iterator[list[subprocess.Popen[bytes]]]:
    children: list[subprocess.Popen[bytes]] = []
    yield children
    for child in children:
        if child.poll() is None:
            child.kill()
        child.wait()
        for stream in (child.stdin, child.stdout):
            if stream is not None:
                stream.close()


def _start(
    children: list[subprocess.Popen[bytes]], code: str, state_dir: Path
) -> subprocess.Popen[bytes]:
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(state_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    children.append(child)
    return child


def test_lock_held_by_another_process_blocks_this_one(
    state_dir: Path, spawn: list[subprocess.Popen[bytes]]
) -> None:
    child = _start(spawn, _HOLD_UNTIL_STDIN_CLOSES, state_dir)
    _wait_for_locked(child)

    assert _is_locked_elsewhere(state_dir)

    assert child.stdin is not None
    child.stdin.close()
    assert child.wait(timeout=_READY_TIMEOUT_SECONDS) == 0
    assert not _is_locked_elsewhere(state_dir)


def test_lock_is_released_when_the_context_exits(state_dir: Path) -> None:
    with theatre_lock(state_dir):
        pass

    assert not _is_locked_elsewhere(state_dir)


def test_lock_is_released_when_the_holder_dies(
    state_dir: Path, spawn: list[subprocess.Popen[bytes]]
) -> None:
    child = _start(spawn, _DIE_WHILE_HOLDING, state_dir)
    _wait_for_locked(child)
    assert child.wait(timeout=_READY_TIMEOUT_SECONDS) == 1

    assert not _is_locked_elsewhere(state_dir)


def test_lock_creates_no_file(state_dir: Path) -> None:
    (state_dir / "troupe.yml").write_text("a: 1\n")
    before = sorted(state_dir.iterdir())

    with theatre_lock(state_dir):
        during = sorted(state_dir.iterdir())

    assert during == before
    assert sorted(state_dir.iterdir()) == before


def test_lock_on_missing_directory_raises_load_error_naming_it(tmp_path: Path) -> None:
    missing = tmp_path / "absent" / ".troupe"

    with pytest.raises(LoadError) as caught, theatre_lock(missing):
        pass

    assert str(missing) in caught.value.message
    assert caught.value.exit_code == 4
