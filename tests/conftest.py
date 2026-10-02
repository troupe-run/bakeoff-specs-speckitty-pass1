"""Shared test harness: build real theatres on disk and run the real CLI as a subprocess.

Plain helpers (``run_cli``, ``snapshot``, ``all_files``) are importable with
``from conftest import ...``; ``make_theatre`` is a fixture because it needs ``tmp_path``.
"""

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

type MakeTheatre = Callable[[dict[str, str | bytes]], Path]

HISTORY_PREFIX = ".troupe/history.sqlite"


@dataclass(frozen=True)
class CliResult:
    """Outcome of one CLI run: exit code and undecoded-newline stdout/stderr."""

    code: int
    out: str
    err: str


def run_cli(*args: str, cwd: Path | None = None) -> CliResult:
    """Run ``python -m troupe *args`` and capture output without newline translation."""
    completed = subprocess.run(
        [sys.executable, "-m", "troupe", *args],
        capture_output=True,
        text=False,
        cwd=cwd,
        check=False,
    )
    return CliResult(
        code=completed.returncode,
        out=completed.stdout.decode("utf-8"),
        err=completed.stderr.decode("utf-8"),
    )


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
