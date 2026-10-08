"""Command-line parsing and dispatch for ``troupe config`` (FR-001, FR-006, FR-008).

Commands: ``get PATH``, ``show [PATH] [--sources]``,
``set PATH VALUE [--reason TEXT] [--in-include] [--expand-alias] [--include]``,
``history [PATH]`` and ``watch``. ``--in-include`` (FR-011, D-9), ``--expand-alias`` (spec C10,
FR-008; research R-10) and ``--include`` (step 7, S-12; research R-12) exist only on ``set``,
anywhere among its options and combinable with each other and with ``--reason``: given to any
other command, argparse reports an unrecognised argument, a ``UsageError`` (exit 2) like any
other bad option.

``TROUPE_ACTOR`` is resolved once, here, right after the arguments are parsed and before the
theatre is located (FR-003, spec DM 01M436TPQDWVSZQYFD6D5343DC). An invalid value is a
``UsageError`` (exit 2), so nothing is located, locked, loaded, imported or recorded. The
resolved actor is passed to the one-shot command; ``watch`` is validated too but records only
file reconciles, which have no CLI actor.

This module owns the output-channel discipline: it is the only writer of stdout and stderr.
Every contracted failure becomes one ``troupe: <message>`` line on stderr and the exit code its
``TroupeError`` subclass declares, with stdout left empty. It holds no command logic.

- The one-shot commands (``COMMAND_MODULES``) return their stdout text, written once, after the
  command has succeeded.
- ``watch`` runs until SIGINT/SIGTERM (research R-09). Through the callbacks passed to it, it
  writes its one ``watching <dir>`` line to stdout (flushed) only once it is ready, and reports
  later load failures on stderr. A ``TroupeError`` raised before it is ready (e.g. a
  ``LoadError`` at startup) is handled like any other: one stderr line, empty stdout.
"""

import argparse
import importlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, NoReturn, Protocol, cast

from troupe.errors import TroupeError, UsageError
from troupe.lineage import Actor, resolve_actor
from troupe.theatre import Theatre, locate

COMMAND_MODULES: Final = {"get": "get", "show": "show", "set": "set_value", "history": "history"}
THEATRE_ENV_VAR: Final = "TROUPE_THEATRE"


class Command(Protocol):
    """Interface every ``troupe.commands.<module>`` satisfies."""

    def run(self, theatre: Theatre, args: argparse.Namespace, actor: Actor) -> str: ...


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that raises ``UsageError`` instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{message} (see '{self.prog} --help')")


def _add_theatre_option(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps a later (sub)parser from overwriting a value given earlier; the
    # fallback to $TROUPE_THEATRE, then the current directory, is applied once, in ``main``.
    parser.add_argument(
        "--theatre",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="theatre directory (default: $TROUPE_THEATRE, else current directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``troupe`` argument parser."""
    parser = _Parser(prog="troupe")
    parser.set_defaults(theatre=None)
    groups = parser.add_subparsers(dest="group", required=True, metavar="{config}")
    config = groups.add_parser("config", help="read and change configuration")
    _add_theatre_option(config)
    commands = config.add_subparsers(dest="command", required=True)

    get = commands.add_parser("get", help="print the scalar at PATH")
    get.add_argument("path", metavar="PATH")
    show = commands.add_parser("show", help="print PATH, or everything, as YAML")
    show.add_argument("path", metavar="PATH", nargs="?", default=None)
    show.add_argument(
        "--sources",
        action="store_true",
        help="end every line holding a scalar with '# from <file>'",
    )
    set_ = commands.add_parser("set", help="set the value at PATH to VALUE")
    set_.add_argument("path", metavar="PATH")
    set_.add_argument("value", metavar="VALUE")
    set_.add_argument(
        "--reason", metavar="TEXT", default=None, help="record TEXT as the reason for this change"
    )
    set_.add_argument(
        "--in-include",
        action="store_true",
        help="write a new key into the included file instead of an override in the including file",
    )
    set_.add_argument(
        "--expand-alias",
        action="store_true",
        help="give an aliased value on PATH its own copy before setting it",
    )
    set_.add_argument(
        "--include",
        action="store_true",
        help="write include-looking strings in VALUE as includes instead of !literal strings",
    )
    history = commands.add_parser("history", help="print recorded changes as JSON Lines")
    history.add_argument("path", metavar="PATH", nargs="?", default=None)
    watch = commands.add_parser(
        "watch", help="record hand edits as they happen until SIGINT/SIGTERM"
    )

    for subparser in (get, show, set_, history, watch):
        _add_theatre_option(subparser)
    return parser


def _announce(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _report(message: str) -> None:
    sys.stderr.write(f"troupe: {message}\n")
    sys.stderr.flush()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    try:
        args = build_parser().parse_args(argv)
        actor = resolve_actor(os.environ)  # before locating: a bad value records nothing
        theatre_arg = args.theatre if args.theatre is not None else os.environ.get(THEATRE_ENV_VAR)
        given = theatre_arg if theatre_arg else os.getcwd()  # as given, never resolved (D-8)
        theatre = locate(Path(given))  # exit 4 before any command module is imported
        if args.command == "watch":
            from troupe.commands.watch import watch  # lazy, like the step-1 commands

            watch(theatre, given, announce=_announce, report=_report)
            return 0
        module = importlib.import_module(f"troupe.commands.{COMMAND_MODULES[args.command]}")
        output = cast(Command, module).run(theatre, args, actor)
    except TroupeError as err:
        sys.stderr.write(f"troupe: {err.message}\n")
        return err.exit_code
    sys.stdout.write(output)
    return 0
