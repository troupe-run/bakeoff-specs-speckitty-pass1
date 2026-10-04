"""The lineage rules: actor grammar, login fallback, ``at`` format, change ids, producers.

The only stand-in is ``getpass.getuser``, patched on the ``getpass`` module: a missing or empty
login name cannot be produced on a real machine, so the login-name fallback (D-6) is driven by
monkeypatching it.
"""

import getpass
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest

from troupe.errors import UsageError
from troupe.lineage import (
    UNKNOWN_ACTOR,
    Actor,
    Lineage,
    Via,
    cli_lineage,
    file_lineage,
    format_at,
    import_lineage,
    lineage_fields,
    lineage_from_fields,
    new_change_id,
    pre_lineage_change_id,
    pre_lineage_fields,
    resolve_actor,
)

AT_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def test_unset_actor_is_human_with_login_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(getpass, "getuser", lambda: "bob")

    assert resolve_actor({}) == Actor("human", "bob")


def _raise_os_error() -> str:
    raise OSError("no login name")


def _raise_key_error() -> str:
    raise KeyError("uid not in password database")


@pytest.mark.parametrize(
    "getuser",
    [_raise_os_error, _raise_key_error, lambda: ""],
    ids=["oserror", "keyerror", "empty"],
)
def test_unset_actor_with_unknown_login_is_human_with_null_id(
    monkeypatch: pytest.MonkeyPatch, getuser: Callable[[], str]
) -> None:
    monkeypatch.setattr(getpass, "getuser", getuser)

    assert resolve_actor({}) == Actor("human", None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("human:alice", Actor("human", "alice")),
        ("agent:planner", Actor("agent", "planner")),
        ("human:alice:x", Actor("human", "alice:x")),
        ("agent:with space", Actor("agent", "with space")),
    ],
)
def test_human_and_agent_values_give_that_kind_and_id(value: str, expected: Actor) -> None:
    assert resolve_actor({"TROUPE_ACTOR": value}) == expected


@pytest.mark.parametrize("value", ["", "alice", "human:", "agent:", "Human:alice", "robot:x", ":x"])
def test_invalid_actor_values_raise_usage_error_naming_the_variable(value: str) -> None:
    with pytest.raises(UsageError) as caught:
        resolve_actor({"TROUPE_ACTOR": value})

    assert caught.value.exit_code == 2
    assert "TROUPE_ACTOR" in caught.value.message
    assert caught.value.message == (
        f"TROUPE_ACTOR: invalid value {value!r}: expected 'human:<id>' or 'agent:<id>'"
    )


def test_invalid_actor_message_matches_the_contract_exactly() -> None:
    with pytest.raises(UsageError) as caught:
        resolve_actor({"TROUPE_ACTOR": "robot:x"})

    assert caught.value.message == (
        "TROUPE_ACTOR: invalid value 'robot:x': expected 'human:<id>' or 'agent:<id>'"
    )


def test_format_at_converts_to_utc_with_microseconds_and_z() -> None:
    moment = datetime(2026, 10, 4, 12, 18, 24, 17202, tzinfo=timezone(timedelta(hours=2)))

    at = format_at(moment)

    assert at == "2026-10-04T10:18:24.017202Z"
    assert AT_PATTERN.match(at)


def test_format_at_keeps_fixed_width_for_zero_microseconds() -> None:
    assert format_at(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T03:04:05.000000Z"


def test_format_at_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        format_at(datetime(2026, 10, 4, 10, 18, 24))


def test_new_change_ids_are_distinct_uuid_strings() -> None:
    ids = [new_change_id() for _ in range(1000)]

    assert len(set(ids)) == 1000
    for change in ids:
        assert str(uuid.UUID(change)) == change


def test_pre_lineage_change_id_cannot_collide_with_a_uuid() -> None:
    change = pre_lineage_change_id(3)

    assert change == "pre-lineage-3"
    with pytest.raises(ValueError):
        uuid.UUID(change)


@pytest.mark.parametrize(
    ("constructor", "via"), [(import_lineage, "import"), (file_lineage, "file")]
)
def test_import_and_file_lineage_have_unknown_actor_and_no_reason(
    constructor: Callable[[], Lineage], via: str
) -> None:
    made = constructor()

    assert isinstance(made, Lineage)
    assert made.actor == UNKNOWN_ACTOR
    assert made.via == via
    assert made.reason is None
    assert AT_PATTERN.match(made.at)
    uuid.UUID(made.change)


def test_each_constructor_call_mints_a_new_change() -> None:
    assert file_lineage().change != file_lineage().change


@pytest.mark.parametrize("reason", ["", "a\nb", "ünï 'q'", None])
def test_cli_lineage_keeps_reason_verbatim(reason: str | None) -> None:
    actor = Actor("agent", "planner")

    made = cli_lineage(actor, reason)

    assert made.reason == reason
    assert made.actor == actor
    assert made.via == "cli"
    assert AT_PATTERN.match(made.at)
    uuid.UUID(made.change)


@pytest.mark.parametrize(
    "made",
    [
        import_lineage(),
        file_lineage(),
        cli_lineage(Actor("human", "alice"), "why"),
        cli_lineage(Actor("human", None), None),
    ],
    ids=["import", "file", "cli", "cli-no-login"],
)
def test_lineage_round_trips_through_stored_fields(made: Lineage) -> None:
    assert lineage_from_fields(**lineage_fields(made)) == made


def test_lineage_fields_are_flat_and_ordered() -> None:
    made = cli_lineage(Actor("human", "alice"), "why")
    fields = lineage_fields(made)

    # Dict equality ignores order, so the stored layout (D-1) is checked separately.
    assert list(fields) == ["actor_kind", "actor_id", "via", "at", "reason", "change"]
    assert fields == {
        "actor_kind": "human",
        "actor_id": "alice",
        "via": "cli",
        "at": made.at,
        "reason": "why",
        "change": made.change,
    }


@pytest.mark.parametrize(
    ("actor_kind", "via", "bad"),
    [("robot", "cli", "robot"), ("Human", "cli", "Human"), ("human", "web", "web")],
)
def test_lineage_from_fields_rejects_unknown_kind_or_via(
    actor_kind: str, via: str, bad: str
) -> None:
    with pytest.raises(ValueError, match=repr(bad)):
        lineage_from_fields(actor_kind, "x", via, "2026-10-04T10:18:24.017202Z", None, "c")


@pytest.mark.parametrize("via", [None, "import"])
def test_pre_lineage_fields_follow_the_recorded_decision(via: Via | None) -> None:
    recorded = datetime(2026, 10, 4, 15, 48, 24, 17202, tzinfo=timezone(timedelta(hours=5.5)))

    fields = pre_lineage_fields(7, via, recorded)

    assert fields == {
        "actor_kind": "unknown",
        "actor_id": None,
        "via": via,
        "at": "2026-10-04T10:18:24.017202Z",
        "reason": None,
        "change": "pre-lineage-7",
    }
    assert lineage_from_fields(**fields).actor == UNKNOWN_ACTOR
