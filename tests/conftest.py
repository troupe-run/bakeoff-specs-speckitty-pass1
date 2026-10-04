"""Shared test harness: build real theatres on disk and run the real CLI as a subprocess.

Plain helpers (``run_cli``, ``snapshot``, ``all_files``, ``history_events``, ``recorded_within``,
``core``, ``stored_records``) and the ``WatchProcess`` context manager are importable with
``from conftest import ...``; ``make_theatre`` is a fixture because it needs ``tmp_path``.

Child processes never inherit ``TROUPE_THEATRE`` or ``TROUPE_ACTOR`` from the developer's shell,
so a value set there cannot change what a test observes.
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Final, Self

import pytest

from troupe.history import HistoryRecord, HistoryStore

type MakeTheatre = Callable[[dict[str, str | bytes]], Path]

HISTORY_PREFIX = ".troupe/history.sqlite"
# Variables a child process never inherits from the developer's environment.
HERMETIC_UNSET: Final = ("TROUPE_THEATRE", "TROUPE_ACTOR")
# The five step-1 keys of a ``history`` line.
CORE_KEYS: Final = ("seq", "op", "path", "old", "new")


@dataclass(frozen=True)
class CliResult:
    """Outcome of one CLI run: exit code and undecoded-newline stdout/stderr."""

    code: int
    out: str
    err: str


def run_cli(
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    unset: Iterable[str] = (),
) -> CliResult:
    """Run ``python -m troupe *args`` and capture output without newline translation.

    ``TROUPE_THEATRE`` and ``TROUPE_ACTOR`` are always removed from the inherited environment, as
    is every variable named in ``unset``; ``env`` entries are then added on top.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "troupe", *args],
        capture_output=True,
        text=False,
        cwd=cwd,
        env=_child_env(env, unset),
        check=False,
    )
    return CliResult(
        code=completed.returncode,
        out=completed.stdout.decode("utf-8"),
        err=completed.stderr.decode("utf-8"),
    )


def _child_env(env: dict[str, str] | None, unset: Iterable[str] = ()) -> dict[str, str]:
    removed = {*HERMETIC_UNSET, *unset}
    return {k: v for k, v in os.environ.items() if k not in removed} | (env or {})


def all_files(theatre: Path) -> set[str]:
    """Return every file under ``theatre`` (history files included) as relative POSIX paths."""
    return {p.relative_to(theatre).as_posix() for p in theatre.rglob("*") if p.is_file()}


def snapshot(theatre: Path) -> dict[str, bytes]:
    """Return the bytes of every file under ``theatre`` except the history store files."""
    return {
        rel: (theatre / rel).read_bytes()
        for rel in sorted(all_files(theatre))
        if not rel.startswith(HISTORY_PREFIX)
    }


def history_events(theatre: Path) -> list[dict[str, object]]:
    """Return ``troupe config history`` for ``theatre``, one parsed JSON object per line."""
    result = run_cli("config", "history", "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return [json.loads(line) for line in result.out.splitlines()]


def core(events: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Project parsed ``history`` objects onto the five step-1 keys (``CORE_KEYS``)."""
    return [{key: event[key] for key in CORE_KEYS} for event in events]


def stored_records(theatre: Path) -> list[HistoryRecord]:
    """Return every record, lineage included, read from the theatre's real history store.

    Opens ``HistoryStore(theatre / ".troupe")``, reads ``records()`` and closes it. Use it only on
    a theatre whose history exists: opening the store creates the database.
    """
    store = HistoryStore(theatre / ".troupe")
    try:
        return store.records()
    finally:
        store.close()


def recorded_within(
    theatre: Path, edited_at: float, seconds: float = 2.0
) -> list[dict[str, object]]:
    """Wait until ``edited_at + seconds``, then return ``history``.

    This is the contract check itself (FR-011): a ``history`` started that late must already show
    the edit. ``edited_at`` is a ``time.monotonic()`` reading taken right after the edit.
    """
    remaining = edited_at + seconds - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)
    return history_events(theatre)


class WatchProcess:
    """A real ``python -m troupe config watch`` child; use as a context manager (always killed).

    The child's environment is built as for ``run_cli`` (``env`` added, ``unset`` removed).

    Reader threads collect the child's stdout lines and stderr lines as they arrive, decoded as
    UTF-8 without newline translation (each line keeps its ``\n``). Every wait has a deadline.
    """

    def __init__(
        self,
        *args: str,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        unset: Iterable[str] = (),
    ) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "troupe", "config", "watch", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=_child_env(env, unset),
        )
        self._changed = threading.Condition()
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._stdout_closed = False
        self._consumed = 0  # stdout lines already returned by ``wait_ready``
        assert self._proc.stdout is not None and self._proc.stderr is not None
        self._readers = [
            threading.Thread(
                target=self._read, args=(self._proc.stdout, self._stdout), daemon=True
            ),
            threading.Thread(
                target=self._read, args=(self._proc.stderr, self._stderr), daemon=True
            ),
        ]
        for reader in self._readers:
            reader.start()

    def _read(self, stream: IO[bytes], lines: list[str]) -> None:
        for raw in iter(stream.readline, b""):
            with self._changed:
                lines.append(raw.decode("utf-8"))
                self._changed.notify_all()
        with self._changed:
            if lines is self._stdout:
                self._stdout_closed = True
            self._changed.notify_all()

    def wait_ready(self, timeout: float = 10.0) -> str:
        """Return the first stdout line (with its newline); fail on timeout or early exit."""
        with self._changed:
            if not self._changed.wait_for(lambda: self._stdout or self._stdout_closed, timeout):
                raise AssertionError(f"no stdout line within {timeout} s")
            if not self._stdout:
                raise AssertionError(f"watch exited before its line: {''.join(self._stderr)!r}")
            self._consumed = 1
            return self._stdout[0]

    def stderr_lines(self) -> list[str]:
        """Return the stderr lines received so far (each with its newline)."""
        with self._changed:
            return list(self._stderr)

    def wait_stderr(self, count: int, timeout: float = 5.0) -> list[str]:
        """Wait until at least ``count`` stderr lines have arrived and return them all."""
        with self._changed:
            if not self._changed.wait_for(lambda: len(self._stderr) >= count, timeout):
                raise AssertionError(f"fewer than {count} stderr lines: {self._stderr!r}")
            return list(self._stderr)

    def wait_exit(self, timeout: float = 10.0) -> tuple[int, str, str]:
        """Wait for the child to exit; return (exit code, stdout not yet read, all stderr)."""
        code = self._proc.wait(timeout)
        for reader in self._readers:
            reader.join(timeout)
        with self._changed:
            return code, "".join(self._stdout[self._consumed :]), "".join(self._stderr)

    def stop(self, sig: int = signal.SIGINT, timeout: float = 5.0) -> tuple[int, str, str]:
        """Send ``sig``, then wait as ``wait_exit`` does."""
        self._proc.send_signal(sig)
        return self.wait_exit(timeout)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        self._proc.wait()
        for reader in self._readers:
            reader.join(5.0)  # EOF follows the child's exit
        for stream in (self._proc.stdout, self._proc.stderr):
            if stream is not None:
                stream.close()


@pytest.fixture
def make_theatre(tmp_path: Path) -> MakeTheatre:
    """Return a builder that writes files under ``<theatre>/.troupe/`` and returns the theatre.

    ``str`` contents are UTF-8 encoded verbatim (no newline translation); ``bytes`` are written
    as given. Keys are paths relative to ``.troupe/``.
    """

    def build(files: dict[str, str | bytes]) -> Path:
        theatre = tmp_path / "theatre"
        state_dir = theatre / ".troupe"
        state_dir.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            target = state_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8") if isinstance(content, str) else content
            target.write_bytes(data)
        return theatre

    return build
