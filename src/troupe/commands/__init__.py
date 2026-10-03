"""Subcommand implementations, loaded lazily by ``troupe.cli``.

Each module named in ``troupe.cli.COMMAND_MODULES`` exposes::

    def run(theatre: Theatre, args: argparse.Namespace) -> str: ...

``run`` returns the complete stdout text (possibly empty) and signals every contracted failure
by raising a ``troupe.errors.TroupeError`` subclass. It must never write to stdout or stderr
itself: the CLI writes the returned text only after ``run`` succeeds, which is what keeps stdout
empty on any non-zero exit.

The long-running ``watch`` module is dispatched separately by ``troupe.cli``; it exposes::

    def watch(theatre: Theatre, given: str, *, announce: Callable[[str], None],
              report: Callable[[str], None], stop: threading.Event | None = None) -> None: ...

It also never writes to stdout or stderr itself: it calls ``announce`` once with its readiness
line and ``report`` with each load failure it reports while running; the CLI does the writing.
"""
