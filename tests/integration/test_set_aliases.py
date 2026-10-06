"""``set`` at an anchor and through an alias, through the real CLI (spec US2, US3).

Spec FR-003, FR-004, FR-007, FR-009, A-0, C4, C5, C6, C11; NFR-001, NFR-003; research R-8, R-9.
A set at the anchored node changes it for every alias and records one event per resolved leaf
whose value changed, in one batch with one lineage; a set reached through an alias or a merge
key exits 3, mentions ``--expand-alias`` and changes no file and no history.
"""

from pathlib import Path

import pytest

from conftest import CliResult, MakeTheatre, history_events, run_cli, snapshot

CONFIG = "troupe.yml"
REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"
MERGED = "defaults: &d\n  model: opus\ncoder:\n  <<: *d\n"


def _cli(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = _cli(theatre, "get", path)
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _config(theatre: Path) -> str:
    return (theatre / ".troupe" / CONFIG).read_bytes().decode("utf-8")


def _set_ok(theatre: Path, *args: str) -> list[dict[str, object]]:
    """Run a ``set`` that must succeed; return the events it recorded."""
    recorded = len(history_events(theatre))
    result = _cli(theatre, "set", *args)
    assert (result.code, result.out, result.err) == (0, "", "")
    return history_events(theatre)[recorded:]


def _refused(theatre: Path, *args: str) -> str:
    """Run a ``set`` that must exit 3 changing nothing (files and history); return stderr."""
    recorded = history_events(theatre)
    before = snapshot(theatre)
    result = _cli(theatre, "set", *args)
    assert (result.code, result.out) == (3, "")
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert snapshot(theatre) == before
    assert history_events(theatre) == recorded
    return result.err


def _changes(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [(e["op"], e["path"], e["old"], e["new"]) for e in events]


# --- US2: set at the anchor ---------------------------------------------------------------------


def test_set_at_anchor_changes_it_for_every_alias(make_theatre: MakeTheatre) -> None:  # US2-1
    theatre = make_theatre({CONFIG: REPORTER})

    events = _set_ok(theatre, "defaults.model", "sonnet")

    assert _config(theatre) == REPORTER.replace("opus", "sonnet")  # only line 2 changes
    assert _get(theatre, "coder.settings.model") == "sonnet\n"
    assert _get(theatre, "reviewer.settings.model") == "sonnet\n"
    assert _changes(events) == [
        ("set", "defaults.model", "opus", "sonnet"),
        ("set", "coder.settings.model", "opus", "sonnet"),
        ("set", "reviewer.settings.model", "opus", "sonnet"),
    ]
    assert len({event["change"] for event in events}) == 1  # one batch, one lineage (C11)
    assert {event["via"] for event in events} == {"cli"}


def test_set_anchored_scalar_keeps_anchor(make_theatre: MakeTheatre) -> None:  # US2-2
    theatre = make_theatre({CONFIG: "model: &m opus\nx: *m\n"})

    events = _set_ok(theatre, "model", "sonnet")

    assert _config(theatre) == "model: &m sonnet\nx: *m\n"
    assert _get(theatre, "x") == "sonnet\n"
    assert _changes(events) == [
        ("set", "model", "opus", "sonnet"),
        ("set", "x", "opus", "sonnet"),
    ]


@pytest.mark.parametrize(
    ("value", "after", "read"),
    [
        ("{model: x}", REPORTER.replace("opus", "x"), ("coder.settings.model", "x\n")),
        (
            "{model: x, t: 1}",
            REPORTER.replace("  model: opus\n", "  model: x\n  t: 1\n"),
            ("coder.settings.t", "1\n"),
        ),
        ("[a]", REPORTER.replace("  model: opus\n", "  - a\n"), ("coder.settings.0", "a\n")),
        ("5", REPORTER.replace("&d\n  model: opus\n", "&d 5\n"), ("reviewer.settings", "5\n")),
    ],
    ids=["same-keys", "more-keys", "list", "scalar"],
)
def test_replacing_anchored_collection_keeps_anchor(
    make_theatre: MakeTheatre, value: str, after: str, read: tuple[str, str]
) -> None:  # US2-3, C5
    theatre = make_theatre({CONFIG: REPORTER})

    _set_ok(theatre, "defaults", value)

    assert _config(theatre) == after
    path, out = read
    assert _get(theatre, path) == out


def test_new_key_under_anchor_appears_through_aliases(make_theatre: MakeTheatre) -> None:  # US2-4
    theatre = make_theatre({CONFIG: REPORTER})

    events = _set_ok(theatre, "defaults.temperature", "0.2")

    assert _config(theatre) == REPORTER.replace("opus\n", "opus\n  temperature: 0.2\n")
    assert _get(theatre, "coder.settings.temperature") == "0.2\n"
    assert _changes(events) == [
        ("set", "defaults.temperature", None, 0.2),
        ("set", "coder.settings.temperature", None, 0.2),
        ("set", "reviewer.settings.temperature", None, 0.2),
    ]


def test_set_at_anchor_in_four_space_file_keeps_its_indentation(
    make_theatre: MakeTheatre,
) -> None:  # T022: the step is read from files with anchors
    text = "defaults: &d\n    model: opus\ncoder:\n    settings: *d\n"
    theatre = make_theatre({CONFIG: text})

    _set_ok(theatre, "defaults.limits", "{max: 1}")

    assert _config(theatre) == text.replace("opus\n", "opus\n    limits:\n        max: 1\n")


# --- US3: refusals through an alias or a merge key ----------------------------------------------


def test_set_through_alias_exits_3_mentions_expand_alias_and_changes_nothing(
    make_theatre: MakeTheatre,
) -> None:  # US3-1: the reported bug
    theatre = make_theatre({CONFIG: REPORTER})

    err = _refused(theatre, "coder.settings.model", "sonnet")

    assert "coder.settings.model" in err and "*d" in err and "--expand-alias" in err
    assert "no file changed" in err
    assert _get(theatre, "reviewer.settings.model") == "opus\n"
    assert _get(theatre, "defaults.model") == "opus\n"


def test_set_through_alias_with_equal_value_is_still_refused(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})

    err = _refused(theatre, "coder.settings.model", "opus")

    assert "--expand-alias" in err


def test_scalar_alias_path_is_refused(make_theatre: MakeTheatre) -> None:  # US3-2, C4
    theatre = make_theatre({CONFIG: "m: &m opus\ncoder:\n  model: *m\n"})

    err = _refused(theatre, "coder.model", "x")

    assert err.startswith("troupe: coder.model: ") and "*m" in err and "--expand-alias" in err


def test_new_key_below_alias_is_refused(make_theatre: MakeTheatre) -> None:  # US3-3, C6
    theatre = make_theatre({CONFIG: REPORTER})

    err = _refused(theatre, "coder.settings.temperature", "0.2")

    assert "coder.settings.temperature" in err and "--expand-alias" in err


def test_merged_value_is_refused_with_and_without_expand_alias(
    make_theatre: MakeTheatre,
) -> None:  # US3-4, A-0
    theatre = make_theatre({CONFIG: MERGED})

    plain = _refused(theatre, "coder.model", "x")
    expanded = _refused(theatre, "--expand-alias", "coder.model", "x")

    assert "'<<'" in plain and "--expand-alias" in plain
    assert "'<<'" in expanded and "merge keys are never written" in expanded
    assert _get(theatre, "coder.model") == "opus\n"


def test_new_key_beside_merge_key_is_written_and_merge_line_unchanged(
    make_theatre: MakeTheatre,
) -> None:  # US3-5, A-0, FR-007
    theatre = make_theatre({CONFIG: MERGED})

    events = _set_ok(theatre, "coder.temperature", "0.2")

    assert _config(theatre) == MERGED + "  temperature: 0.2\n"
    assert _get(theatre, "coder.model") == "opus\n"
    assert _changes(events) == [("set", "coder.temperature", None, 0.2)]


def test_anchor_not_on_key_line_blocks_kind_change(make_theatre: MakeTheatre) -> None:  # R-9
    theatre = make_theatre({CONFIG: "defaults:\n  &d\n  model: opus\ncoder:\n  settings: *d\n"})

    err = _refused(theatre, "defaults", "5")

    assert err == (
        "troupe: defaults: the anchor &d of this value is not on its key's line; replacing the"
        " value would move it; no file changed\n"
    )
