"""Command-line parsing and dispatch for ``troupe config`` (FR-001, FR-006).

This module owns the output-channel discipline: stdout is written in exactly one place, after
the command has succeeded; every contracted failure becomes one ``troupe: <message>`` line on
stderr and the exit code its ``TroupeError`` subclass declares. It holds no command logic.
"""

import argparse
import importlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, NoReturn, Protocol, cast

from troupe.errors import TroupeError, UsageError
from troupe.theatre import Theatre, locate

COMMAND_MODULES: Final = {"show": "show", "set": "set_value", "history": "history"}


class Command(Protocol):
    """Interface every ``troupe.commands.<module>`` satisfies."""

    def run(self, theatre: Theatre, args: argparse.Namespace) -> str: ...


class _Parser(argparse.ArgumentParser):
    """ArgumentParser that raises ``UsageError`` instead of printing and exiting."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(f"{message} (see '{self.prog} --help')")


def _add_theatre_option(parser: argparse.ArgumentParser) -> None:
    # SUPPRESS keeps a later (sub)parser from overwriting a value given earlier; the
    # fallback to the current directory is applied once, in ``main``.
    parser.add_argument(
        "--theatre",
        metavar="DIR",
        default=argparse.SUPPRESS,
        help="theatre directory (default: current directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the ``troupe`` argument parser."""
    parser = _Parser(prog="troupe")
    parser.set_defaults(theatre=None)
    groups = parser.add_subparsers(dest="group", required=True, metavar="{config}")
    config = groups.add_parser("config", help="read and change configuration")
    _add_theatre_option(config)
    commands = config.add_subparsers(dest="command", required=True)

    show = commands.add_parser("show", help="print the scalar at PATH")
    show.add_argument("path", metavar="PATH")
    set_ = commands.add_parser("set", help="set the value at PATH to VALUE")
    set_.add_argument("path", metavar="PATH")
    set_.add_argument("value", metavar="VALUE")
    history = commands.add_parser("history", help="print recorded changes as JSON Lines")
    history.add_argument("path", metavar="PATH", nargs="?", default=None)

    for subparser in (show, set_, history):
        _add_theatre_option(subparser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    try:
        args = build_parser().parse_args(argv)
        theatre_dir = Path.cwd() if args.theatre is None else Path(args.theatre)
        theatre = locate(theatre_dir)  # exit 4 before any command module is imported
        module = importlib.import_module(f"troupe.commands.{COMMAND_MODULES[args.command]}")
        output = cast(Command, module).run(theatre, args)
    except TroupeError as err:
        sys.stderr.write(f"troupe: {err.message}\n")
        return err.exit_code
    sys.stdout.write(output)
    return 0
