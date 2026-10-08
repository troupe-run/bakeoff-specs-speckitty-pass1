"""``troupe config watch``: record hand edits as they happen (FR-008..FR-014, research R-03..R-09).

``watch`` imports or reconciles once, then announces ``watching <dir>`` and polls the watched
files every ``POLL_INTERVAL`` seconds until SIGINT or SIGTERM. A poll compares bytes, never
mtimes, and any difference triggers a reconcile. Each reconcile runs in its own session, so the
theatre lock is held only while reconciling, never while sleeping.

The baseline is built from the texts the session's load actually read, so an edit that lands
after that load (even before the line is printed) differs from it and is seen by the first poll:
that is what makes the line a promise (NFR-002).

The schema file ``troupe.schema.json`` is baselined too (absent maps to ``None``): it decides
which strings are literals and what is valid, so editing, adding or removing it is a change that
triggers a reconcile (spec S-6, research R-11).

Remote content is never polled (spec S-6): URLs are not in the baseline, and remote includes are
fetched again only when a reconcile runs, i.e. when a local watched file or the schema changes.

While the configuration cannot be loaded, ``watch`` keeps running, records nothing, retries on
every tick (a stale baseline could not see, say, a missing include target being created) and
reports each distinct message once (D-1, research R-05). A failing remote include is therefore
fetched again on each retry, each fetch bounded by its 10-second deadline (spec S-6).
"""

import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

from troupe.errors import LoadError
from troupe.reconcile import watched_files
from troupe.schema import SCHEMA_FILE_NAME
from troupe.session import open_session
from troupe.theatre import ROOT_FILE_NAMES, Theatre

POLL_INTERVAL: Final = 0.25  # seconds; the only place the reaction-time budget is spent (NFR-001)

type Baseline = dict[Path, bytes | None]  # None: the file is absent or unreadable


def watch(
    theatre: Theatre,
    given: str,
    *,
    announce: Callable[[str], None],
    report: Callable[[str], None],
    stop: threading.Event | None = None,
) -> None:
    """Watch ``theatre`` until ``stop`` is set (by SIGINT/SIGTERM unless injected).

    Args:
        theatre: The theatre located by the CLI.
        given: The theatre directory as the user gave it; echoed verbatim (D-8).
        announce: Writes one stdout line; called once, after the baseline exists.
        report: Writes one ``troupe: <message>`` stderr line.
        stop: Set to end the watch. When ``None``, SIGINT and SIGTERM set it; the previous
            handlers are restored on return. Injected events need no main thread.

    Raises:
        LoadError: If the configuration cannot be loaded at start; nothing is announced.
    """
    if stop is not None:
        _run(theatre, given, announce, report, stop)
        return
    stopped = threading.Event()
    previous = {
        sig: signal.signal(sig, lambda *_: stopped.set()) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        _run(theatre, given, announce, report, stopped)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _run(
    theatre: Theatre,
    given: str,
    announce: Callable[[str], None],
    report: Callable[[str], None],
    stop: threading.Event,
) -> None:
    baseline: Baseline | None = _reconcile_and_snapshot(theatre)  # LoadError: exit 4, no line
    if stop.is_set():
        return
    announce(f"watching {given}")
    last_error: str | None = None
    while not stop.wait(POLL_INTERVAL):
        if baseline is not None and _current(baseline) == baseline:
            continue
        try:
            baseline = _reconcile_and_snapshot(theatre)
            last_error = None
        except LoadError as err:
            baseline = None  # unloadable: retry on every tick
            if err.message != last_error:
                report(err.message)
                last_error = err.message


def _reconcile_and_snapshot(theatre: Theatre) -> Baseline:
    """Import or reconcile in one session and return the bytes that session's load read.

    The watched files map to their loaded bytes. Both root candidates are keyed as ``locate``
    checks them: the located one maps to its loaded bytes (also when it is a symlink), the other
    to ``None``, since ``locate`` has just found it absent.

    The schema file decides what is a literal and what is valid, so editing it is a change to
    watch (S-6). It maps to its bytes read *before* the session's load (``None`` when absent):
    an edit landing after that read differs from the baseline whether or not the load saw it,
    so it is never missed; at worst it causes one extra, idempotent reconcile.
    """
    schema_bytes = _read(theatre.state_dir / SCHEMA_FILE_NAME)
    with open_session(theatre, reconcile=True) as session:
        baseline: Baseline = dict(watched_files(session.tree))
        located = session.theatre.config_file
        for name in ROOT_FILE_NAMES:
            candidate = session.theatre.state_dir / name
            baseline[candidate] = baseline[located.resolve()] if candidate == located else None
        baseline[session.theatre.state_dir / SCHEMA_FILE_NAME] = schema_bytes
        return baseline


def _current(baseline: Baseline) -> Baseline:
    """Read every baselined path now; absent or unreadable files map to ``None``."""
    return {path: _read(path) for path in baseline}


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None
