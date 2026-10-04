"""Lineage: who changed the configuration, through which channel, when, why, and in which change.

This module is the one place where every lineage decision is made (TROUPE-007):

- the ``TROUPE_ACTOR`` grammar and its usage error (FR-002, FR-003, D-5);
- the login-name fallback when ``TROUPE_ACTOR`` is unset (FR-003, D-6,
  DM 01M436TX68S2MGE4DN9AM02KTJ);
- the ``at`` format, RFC 3339 UTC with microseconds and a ``Z`` suffix (FR-007, D-4);
- the change-id formats: a UUID4 for a new change, ``pre-lineage-<seq>`` for an event recorded
  before lineage existed (FR-009, D-3, DM 01M436RBNQT22F9AM54QER2FT9);
- the lineage of each producer: import, file reconcile and CLI command (FR-004, FR-005);
- the mapping between a ``Lineage`` and the flat fields stored on history events.

Nothing outside this module builds an ``Actor``, formats an ``at`` or mints a change id. Each
producer calls its constructor exactly once, which reads the clock once and mints one change id,
so every event of one change shares ``at`` and ``change`` (FR-007, FR-009).
"""

import getpass
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, TypedDict

from troupe.errors import UsageError

ACTOR_ENV_VAR: Final = "TROUPE_ACTOR"
PRE_LINEAGE_CHANGE_PREFIX: Final = "pre-lineage-"

type ActorKind = Literal["human", "agent", "unknown"]
type Via = Literal["import", "cli", "file"]

_ACTOR_KINDS: Final[dict[str, ActorKind]] = {
    "human": "human",
    "agent": "agent",
    "unknown": "unknown",
}
# Only these kinds may be named in ``TROUPE_ACTOR``; ``unknown`` is reserved for imports, file
# reconciles and pre-lineage events (D-5).
_ENV_ACTOR_KINDS: Final[dict[str, ActorKind]] = {"human": "human", "agent": "agent"}
_VIAS: Final[dict[str, Via]] = {"import": "import", "cli": "cli", "file": "file"}


@dataclass(frozen=True)
class Actor:
    """Who made a change.

    Attributes:
        kind: ``"human"`` or ``"agent"`` for a CLI command; ``"unknown"`` only for import, file
            and pre-lineage events.
        id: The id given in ``TROUPE_ACTOR`` (non-empty, verbatim), or the login name when the
            variable is unset, or ``None`` when no login name can be determined. Always ``None``
            for ``"unknown"``.
    """

    kind: ActorKind
    id: str | None


UNKNOWN_ACTOR: Final = Actor("unknown", None)


@dataclass(frozen=True)
class Lineage:
    """The lineage shared by every event of one change.

    Attributes:
        actor: Who made the change.
        via: The channel: ``"import"``, ``"cli"`` or ``"file"``. ``None`` appears only for a
            set or remove event read from a pre-lineage history, whose channel cannot be
            determined (DM 01M436RBNQT22F9AM54QER2FT9); a new event always has a channel.
        at: When the change was recorded, RFC 3339 UTC with microseconds, ending in ``Z``.
        reason: The ``--reason`` text, stored exactly as given, or ``None``.
        change: The change id: a UUID4 string, or ``pre-lineage-<seq>`` for an old event.
    """

    actor: Actor
    via: Via | None
    at: str
    reason: str | None
    change: str


class LineageFields(TypedDict):
    """The flat lineage fields stored on each history event."""

    actor_kind: str
    actor_id: str | None
    via: str | None
    at: str
    reason: str | None
    change: str


def login_name() -> str | None:
    """Return the user's login name, or ``None`` if it cannot be determined (D-6).

    The login name is the standard library's notion: ``LOGNAME``, ``USER``, ``LNAME``,
    ``USERNAME``, then the password database. ``None`` means none of them gives a non-empty
    name (DM 01M436TX68S2MGE4DN9AM02KTJ).
    """
    try:
        name = getpass.getuser()
    except (OSError, KeyError):  # 3.13+ raises OSError; 3.12 lets pwd's KeyError escape.
        return None
    return name or None


def resolve_actor(environ: Mapping[str, str]) -> Actor:
    """Return the actor of a CLI command from ``TROUPE_ACTOR`` in ``environ`` (FR-002, D-5).

    Unset gives ``Actor("human", login_name())``. Otherwise the value is split at the first
    ``:``; the kind must be exactly ``human`` or ``agent`` and the id, the rest kept verbatim,
    must be non-empty.

    Raises:
        UsageError: The variable is set to any other value, including the empty string.
    """
    if ACTOR_ENV_VAR not in environ:
        return Actor("human", login_name())
    value = environ[ACTOR_ENV_VAR]
    kind, sep, ident = value.partition(":")
    actor_kind = _ENV_ACTOR_KINDS.get(kind)
    if sep != ":" or actor_kind is None or ident == "":
        raise UsageError(
            f"{ACTOR_ENV_VAR}: invalid value {value!r}: expected 'human:<id>' or 'agent:<id>'"
        )
    return Actor(actor_kind, ident)


def format_at(moment: datetime) -> str:
    """Format ``moment`` as RFC 3339 UTC with microseconds and a ``Z`` suffix (D-4).

    The result has a fixed width, so values sort lexically. ``moment`` is converted to UTC, so a
    stored timestamp in another zone (a non-UTC ``TZINFO_TOPIC``) is handled too.

    Raises:
        ValueError: ``moment`` is naive.
    """
    if moment.tzinfo is None:
        raise ValueError("format_at needs an aware datetime")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def now_at() -> str:
    """Return the current time in the ``at`` format (D-4)."""
    return format_at(datetime.now(UTC))


def new_change_id() -> str:
    """Mint a new change id: a UUID4 string (D-3)."""
    return str(uuid.uuid4())


def pre_lineage_change_id(seq: int) -> str:
    """Return the change id of the event at ``seq`` in a pre-lineage history (D-3).

    It can never equal a UUID, so it cannot collide with a new change id.
    """
    return f"{PRE_LINEAGE_CHANGE_PREFIX}{seq}"


def import_lineage() -> Lineage:
    """Return the lineage of one import: unknown actor, via ``import`` (FR-005)."""
    return Lineage(UNKNOWN_ACTOR, "import", now_at(), None, new_change_id())


def file_lineage() -> Lineage:
    """Return the lineage of one file reconcile: unknown actor, via ``file`` (FR-005)."""
    return Lineage(UNKNOWN_ACTOR, "file", now_at(), None, new_change_id())


def cli_lineage(actor: Actor, reason: str | None) -> Lineage:
    """Return the lineage of one CLI command's own change, via ``cli`` (FR-004).

    ``reason`` is kept verbatim: ``""`` stays ``""``.
    """
    return Lineage(actor, "cli", now_at(), reason, new_change_id())


def lineage_fields(lineage: Lineage) -> LineageFields:
    """Return the flat fields that store ``lineage`` on a history event.

    The fields are those of a version-2 history event, in that order (D-1;
    data-model.md "History event, version 2").
    """
    return LineageFields(
        actor_kind=lineage.actor.kind,
        actor_id=lineage.actor.id,
        via=lineage.via,
        at=lineage.at,
        reason=lineage.reason,
        change=lineage.change,
    )


def lineage_from_fields(
    actor_kind: str,
    actor_id: str | None,
    via: str | None,
    at: str,
    reason: str | None,
    change: str,
) -> Lineage:
    """Rebuild a ``Lineage`` from the flat fields stored on a history event.

    The inverse of ``lineage_fields`` (D-1; data-model.md "History event, version 2").

    Raises:
        ValueError: ``actor_kind`` or ``via`` is not a known value (a corrupt store).
    """
    kind = _ACTOR_KINDS.get(actor_kind)
    if kind is None:
        raise ValueError(f"unknown actor kind {actor_kind!r} in stored lineage")
    channel: Via | None = None
    if via is not None:
        channel = _VIAS.get(via)
        if channel is None:
            raise ValueError(f"unknown via {via!r} in stored lineage")
    return Lineage(Actor(kind, actor_id), channel, at, reason, change)


def pre_lineage_fields(seq: int, via: Via | None, recorded: datetime) -> LineageFields:
    """Lineage for an event recorded before step 4 (DM 01M436RBNQT22F9AM54QER2FT9).

    The actor is unknown, ``via`` is ``"import"`` for an import and ``None`` otherwise, ``at``
    is the event's stored recording time in UTC, there is no reason, and the change id is
    ``pre-lineage-<seq>``, unique per event.

    Raises:
        ValueError: ``recorded`` is naive.
    """
    return lineage_fields(
        Lineage(UNKNOWN_ACTOR, via, format_at(recorded), None, pre_lineage_change_id(seq))
    )
