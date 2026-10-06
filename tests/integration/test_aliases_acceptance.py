"""Acceptance for anchors and aliases: history, edge cases and refusals (WP06).

Everything runs through the real CLI against real files and the real event store. Successful
writes compare the bytes of **every** theatre file; refusals check the exit code, an empty
stdout, a one-line stderr naming PATH or the file, that no file changed and that no event was
recorded (NFR-001, NFR-003).

Covered here: history, reconcile and ``watch`` of resolved leaves (C11, FR-009); the spec's
Edge Cases (redefined anchors, anchors without aliases, aliases in an included file,
``--expand-alias`` with ``--in-include``, undefined aliases, CRLF, ``show`` after expansion);
and the refusals decided during implementation that had no real-CLI test yet (merge keys never
written, recursive aliases, C14). The contract example, US2 to US4 and the read side are in
``test_set_aliases.py``, ``test_set_expand_alias.py`` and ``test_aliases_read.py``.
"""

import time
from pathlib import Path

import pytest

from conftest import (
    CliResult,
    MakeTheatre,
    WatchProcess,
    core,
    history_events,
    recorded_within,
    run_cli,
    snapshot,
)

type Files = dict[str, str | bytes]
type Event = dict[str, object]

CONFIG = "troupe.yml"
CODER = "agents/coder.yaml"
REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"
COMMENT = "  # expanded from *d by troupe"
QUIET = 2.5  # seconds: longer than the 2 s watch contract, so "nothing happened" means nothing


def _cli(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = _cli(theatre, "get", path)
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _write(theatre: Path, rel: str, text: str) -> None:
    """Hand-edit ``.troupe/<rel>`` (bytes as given, no newline translation)."""
    (theatre / ".troupe" / rel).write_bytes(text.encode("utf-8"))


def _set_ok(theatre: Path, *args: str) -> list[Event]:
    """Run a ``set`` that must succeed silently; return the events it recorded."""
    recorded = len(history_events(theatre))
    result = _cli(theatre, "set", *args)
    assert (result.code, result.out, result.err) == (0, "", ""), result.err
    return history_events(theatre)[recorded:]


def _refused(theatre: Path, args: tuple[str, ...], code: int, *names: str) -> str:
    """Run ``set *args``: exit ``code``, empty stdout, one stderr line naming every ``names``,
    no file changed and no event recorded; return stderr."""
    events = history_events(theatre)
    before = snapshot(theatre)

    result = _cli(theatre, "set", *args)

    assert (result.code, result.out) == (code, ""), result.err
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1, result.err
    for name in names:
        assert name in result.err, result.err
    assert snapshot(theatre) == before
    assert history_events(theatre) == events
    return result.err


def _changes(events: list[Event]) -> list[tuple[object, ...]]:
    return [(e["op"], e["path"], e["old"], e["new"]) for e in events]


# --- T026: history, reconcile and watch record resolved leaves (C11, FR-009) -------------------


def test_hand_edit_of_anchored_value_records_every_alias_leaf(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})
    imported = history_events(theatre)
    _write(theatre, CONFIG, REPORTER.replace("opus", "haiku"))

    assert _get(theatre, "reviewer.settings.model") == "haiku\n"

    events = history_events(theatre)[len(imported) :]
    assert _changes(events) == [
        ("set", "defaults.model", "opus", "haiku"),
        ("set", "coder.settings.model", "opus", "haiku"),
        ("set", "reviewer.settings.model", "opus", "haiku"),
    ]
    assert {e["via"] for e in events} == {"file"}  # reconcile lineage, as in step 4
    assert len({e["change"] for e in events}) == 1  # one batch


def test_hand_edit_adding_an_alias_without_value_change_records_nothing(
    make_theatre: MakeTheatre,
) -> None:
    # ``other`` changes in the same edit, proving the reconcile ran: it is the only event.
    written = "defaults: &d\n  model: opus\ncoder:\n  settings:\n    model: opus\nother: 1\n"
    theatre = make_theatre({CONFIG: written})
    imported = history_events(theatre)
    _write(theatre, CONFIG, "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nother: 2\n")

    assert _get(theatre, "coder.settings.model") == "opus\n"
    assert _changes(history_events(theatre)[len(imported) :]) == [("set", "other", 1, 2)]


def test_hand_expansion_equal_to_anchor_records_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER + "other: 1\n"})
    imported = history_events(theatre)
    expanded = REPORTER.replace(
        "  settings: *d\nreviewer", "  settings:\n    model: opus\nreviewer"
    )
    _write(theatre, CONFIG, expanded + "other: 2\n")

    assert _get(theatre, "coder.settings.model") == "opus\n"
    assert _changes(history_events(theatre)[len(imported) :]) == [("set", "other", 1, 2)]


def _seq_events(start: int, old: object, new: object) -> list[Event]:
    """The three ``set`` events of a change at ``defaults.model`` in REPORTER, from ``start``."""
    paths = ("defaults.model", "coder.settings.model", "reviewer.settings.model")
    return [
        {"seq": start + i, "op": "set", "path": path, "old": old, "new": new}
        for i, path in enumerate(paths)
    ]


def test_watch_records_set_at_anchor_once_per_leaf(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})
    with WatchProcess("--theatre", str(theatre)) as watch:
        watch.wait_ready()
        before = history_events(theatre)
        result = _cli(theatre, "set", "defaults.model", "x")
        set_at = time.monotonic()
        assert (result.code, result.out, result.err) == (0, "", "")
        events = recorded_within(theatre, set_at, QUIET)  # longer than 2 s: no late duplicate
        stopped = watch.stop()

    assert len(before) == 3
    assert core(events) == [*core(before), *_seq_events(4, "opus", "x")]
    assert {e["via"] for e in events[3:]} == {"cli"}
    assert stopped == (0, "", "")


def test_watch_records_hand_edit_at_anchor_once_per_leaf(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})
    with WatchProcess("--theatre", str(theatre)) as watch:
        watch.wait_ready()
        before = history_events(theatre)
        _write(theatre, CONFIG, REPORTER.replace("opus", "haiku"))
        events = recorded_within(theatre, time.monotonic())
        stopped = watch.stop()

    assert core(events) == [*core(before), *_seq_events(4, "opus", "haiku")]
    assert {e["via"] for e in events[3:]} == {"file"}
    assert stopped == (0, "", "")


def test_refused_set_keeps_earlier_reconcile_events(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})
    imported = history_events(theatre)
    edited = REPORTER.replace("opus", "haiku")
    _write(theatre, CONFIG, edited)

    result = _cli(theatre, "set", "coder.settings.model", "x")

    assert (result.code, result.out) == (3, "")
    assert "coder.settings.model" in result.err and "--expand-alias" in result.err
    assert core(history_events(theatre)) == [*core(imported), *_seq_events(4, "opus", "haiku")]
    assert snapshot(theatre) == _bytes({CONFIG: edited})


# --- T027: edge cases --------------------------------------------------------------------------

REDEFINED = "a: &a\n  m: 1\nx: *a\na2: &a\n  m: 2\ny: *a\n"


def test_redefined_anchor_aliases_follow_the_latest_definition(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REDEFINED})
    assert (_get(theatre, "x.m"), _get(theatre, "y.m")) == ("1\n", "2\n")

    events = _set_ok(theatre, "a2.m", "5")

    assert snapshot(theatre) == _bytes({CONFIG: REDEFINED.replace("m: 2", "m: 5")})
    assert _changes(events) == [("set", "a2.m", 2, 5), ("set", "y.m", 2, 5)]
    assert (_get(theatre, "x.m"), _get(theatre, "a.m")) == ("1\n", "1\n")

    events = _set_ok(theatre, "--expand-alias", "y.m", "7")

    after = "a: &a\n  m: 1\nx: *a\na2: &a\n  m: 5\ny:  # expanded from *a by troupe\n  m: 7\n"
    assert snapshot(theatre) == _bytes({CONFIG: after})  # the copy adds no ``&a``
    assert _changes(events) == [("set", "y.m", 5, 7)]
    assert (_get(theatre, "x.m"), _get(theatre, "a2.m")) == ("1\n", "5\n")


def test_anchor_with_no_alias_behaves_like_any_value(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: "a: &a\n  m: 1\nb: 2\n"})

    assert _changes(_set_ok(theatre, "a.m", "2")) == [("set", "a.m", 1, 2)]
    assert snapshot(theatre) == _bytes({CONFIG: "a: &a\n  m: 2\nb: 2\n"})
    assert _changes(_set_ok(theatre, "a.n", "3")) == [("set", "a.n", None, 3)]
    assert _changes(_set_ok(theatre, "a", "{z: 1}")) == [
        ("set", "a.z", None, 1),
        ("remove", "a.m", 2, None),
        ("remove", "a.n", 3, None),
    ]
    assert snapshot(theatre) == _bytes({CONFIG: "a: &a\n  z: 1\nb: 2\n"})


INCLUDED_ALIAS = "defaults: &d\n  model: opus\nsettings: *d\nother: *d\n"
INCLUDE: Files = {CONFIG: "coder: file:agents/coder.yaml\n", CODER: INCLUDED_ALIAS}


def test_aliases_in_an_included_file_are_refused_and_expanded_in_that_file(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(INCLUDE)

    _refused(theatre, ("coder.settings.model", "x"), 3, "coder.settings", "*d", "--expand-alias")
    _refused(theatre, ("coder.settings.top_p", "1"), 3, "coder.settings", "*d", "--expand-alias")
    events = _set_ok(theatre, "--expand-alias", "coder.settings.model", "x")

    expanded = INCLUDED_ALIAS.replace("settings: *d\n", f"settings:{COMMENT}\n  model: x\n")
    assert snapshot(theatre) == _bytes({**INCLUDE, CODER: expanded})  # troupe.yml untouched
    assert _changes(events) == [("set", "coder.settings.model", "opus", "x")]
    assert _get(theatre, "coder.other.model") == "opus\n"


OVERRIDE_ALIAS: Files = {
    CONFIG: "defaults: &d\n  model: opus\ncoder:\n  $ref: file:agents/coder.yaml\n  settings: *d\n",
    CODER: "settings:\n  model: gpt\n  temperature: 0.7\n",
}


def test_expand_alias_with_in_include_expands_then_follows_in_include(
    make_theatre: MakeTheatre, tmp_path: Path
) -> None:
    # Both flags matter: the override side of ``coder.settings`` is the alias *d. Without
    # ``--in-include`` the new key goes to the override side, so the alias is expanded and the
    # key added to the copy; with it the key goes into the included file, which is not reached
    # through the alias, so nothing is expanded.
    theatre = make_theatre(OVERRIDE_ALIAS)
    _refused(theatre, ("coder.settings.top_p", "1"), 3, "*d", "--expand-alias")

    _set_ok(theatre, "--expand-alias", "coder.settings.top_p", "1")

    assert snapshot(theatre) == _bytes(
        {
            **OVERRIDE_ALIAS,
            CONFIG: str(OVERRIDE_ALIAS[CONFIG]).replace(
                "  settings: *d\n", f"  settings:{COMMENT}\n    model: opus\n    top_p: 1\n"
            ),
        }
    )

    both = tmp_path / "both"
    (both / ".troupe" / "agents").mkdir(parents=True)
    for rel, text in OVERRIDE_ALIAS.items():
        _write(both, rel, str(text))
    events = _set_ok(both, "--in-include", "coder.settings.top_p", "1", "--expand-alias")

    assert snapshot(both) == _bytes(
        {**OVERRIDE_ALIAS, CODER: str(OVERRIDE_ALIAS[CODER]) + "  top_p: 1\n"}
    )
    assert _changes(events) == [("set", "coder.settings.top_p", None, 1)]


def test_expand_alias_in_included_file_puts_new_key_in_the_copy_only_with_in_include(
    make_theatre: MakeTheatre,
) -> None:
    # The alias lives in the included file. Without ``--in-include`` the new key would become an
    # override in troupe.yml while the expansion is in agents/coder.yaml: two files, which C-005
    # forbids for an expansion, so it is refused (exit 3) and names --in-include.
    theatre = make_theatre(INCLUDE)

    err = _refused(
        theatre, ("--expand-alias", "coder.settings.top_p", "1"), 3, "coder.settings.top_p"
    )
    assert "--in-include" in err and "no file changed" in err

    events = _set_ok(theatre, "--expand-alias", "--in-include", "coder.settings.top_p", "1")

    expanded = INCLUDED_ALIAS.replace(
        "settings: *d\n", f"settings:{COMMENT}\n  model: opus\n  top_p: 1\n"
    )
    assert snapshot(theatre) == _bytes({**INCLUDE, CODER: expanded})
    assert _changes(events) == [("set", "coder.settings.top_p", None, 1)]


UNDEFINED: dict[str, Files] = {
    "undefined": {CONFIG: "x: *a\n"},
    "before-anchor": {CONFIG: "x: *a\na: &a 1\n"},
    "other-file": {CONFIG: "d: &d 1\ncoder: file:agents/coder.yaml\n", CODER: "m: *d\n"},
}


@pytest.mark.parametrize("files", UNDEFINED.values(), ids=UNDEFINED.keys())
@pytest.mark.parametrize("command", [("get", "d"), ("show",), ("set", "d", "2")], ids=str)
def test_undefined_alias_and_alias_before_anchor_exit_4(
    make_theatre: MakeTheatre, files: Files, command: tuple[str, ...]
) -> None:
    theatre = make_theatre(files)
    before = snapshot(theatre)

    result = _cli(theatre, *command)

    assert (result.code, result.out) == (4, "")
    assert "undefined alias" in result.err
    holder = CODER if CODER in files else CONFIG
    assert str((theatre / ".troupe" / holder).resolve()) in result.err
    assert snapshot(theatre) == before


def test_recursive_alias_exits_4(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: "a: &a\n  b: *a\n"})

    result = _cli(theatre, "get", "a")

    assert (result.code, result.out) == (4, "")
    assert "recursive alias *a" in result.err and CONFIG in result.err


def test_crlf_file_expansion_keeps_crlf(make_theatre: MakeTheatre) -> None:
    crlf = REPORTER.replace("\n", "\r\n")
    theatre = make_theatre({CONFIG: crlf})

    _set_ok(theatre, "--expand-alias", "coder.settings.model", "x")

    after = crlf.replace(
        "  settings: *d\r\nreviewer", f"  settings:{COMMENT}\r\n    model: x\r\nreviewer"
    )
    assert snapshot(theatre) == _bytes({CONFIG: after})


def test_expanded_copy_reads_back_identically_with_show(make_theatre: MakeTheatre) -> None:
    text = REPORTER.replace("opus\n", "opus\n  limits: {max: 3}\n  tools: [a, b]\n")
    theatre = make_theatre({CONFIG: text})
    before = {path: _cli(theatre, "show", *path) for path in [(), ("coder",), ("reviewer",)]}

    _set_ok(theatre, "--expand-alias", "coder.settings.model", "sonnet")

    after = {path: _cli(theatre, "show", *path) for path in before}
    assert after[()].out == before[()].out.replace(
        "coder:\n  settings:\n    model: opus", "coder:\n  settings:\n    model: sonnet"
    )
    assert after[("coder",)].out == before[("coder",)].out.replace("opus", "sonnet")
    assert after[("reviewer",)] == before[("reviewer",)]
    assert after[()].out != before[()].out


def test_comment_is_respaced_only_on_lines_the_expansion_created(
    make_theatre: MakeTheatre,
) -> None:
    text = REPORTER + "note: 1    # expanded from *d by troupe\n"
    theatre = make_theatre({CONFIG: text})

    _set_ok(theatre, "--expand-alias", "coder.settings", "5")

    assert snapshot(theatre) == _bytes(
        {CONFIG: text.replace("  settings: *d\nreviewer", f"  settings: 5{COMMENT}\nreviewer")}
    )


# --- Refusals decided during implementation: merge keys never written, C14 --------------------

MERGE_REFUSALS = {
    "new-merge-key": (
        "d: &d\n  model: opus\ncoder:\n  m: 1\n",
        ("coder.<<", "1"),
        "troupe never writes merge keys",
    ),
    "copy-holding-merge-key": (
        "base: &b {x: 1}\nd: &d\n  <<: *b\n  model: opus\ncoder:\n  settings: *d\n",
        ("--expand-alias", "coder.settings.model", "x"),
        "copying it would write a merge key",
    ),
    "replace-mapping-holding-merge-key": (
        "d: &d {x: 1}\ncoder:\n  <<: *d\n  m: 1\n",
        ("coder", "{m: 2}"),
        "replacing it as a whole would rewrite the merge key",
    ),
}


@pytest.mark.parametrize(
    ("text", "args", "reason"), MERGE_REFUSALS.values(), ids=MERGE_REFUSALS.keys()
)
def test_merge_keys_are_never_written(
    make_theatre: MakeTheatre, text: str, args: tuple[str, ...], reason: str
) -> None:  # FR-007, A-0
    theatre = make_theatre({CONFIG: text})

    _refused(theatre, args, 3, args[-2], reason, "no file changed")


@pytest.mark.parametrize("value", ["*d", "&a 1", "[&a 1, *a]", "!t 1"])
def test_anchor_alias_or_tag_in_value_exits_2(make_theatre: MakeTheatre, value: str) -> None:
    theatre = make_theatre({CONFIG: REPORTER})

    err = _refused(theatre, ("x", value), 2, f"VALUE '{value}'")

    assert "alias" in err or "anchors and tags are not supported" in err
