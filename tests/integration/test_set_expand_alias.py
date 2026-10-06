"""``set --expand-alias`` through the real CLI (spec US4; contract worked example).

Spec FR-005, FR-006, FR-008, FR-009, C4, C7, C8, C9, C10, C11; NFR-002, NFR-003; research R-8,
R-10. Every alias on PATH is replaced by a block copy of its anchored node carrying
``  # expanded from *<name> by troupe``, then VALUE is set in the copy: one write of one file,
whole files compared byte for byte. Refusals change no file and record nothing.

The last test calls the verifier directly (research R-8, plan Risks): an expansion that also
replaced another alias must be refused even though PATH reads back.
"""

from pathlib import Path

import pytest

from conftest import CliResult, MakeTheatre, history_events, run_cli, snapshot
from troupe.loader import load
from troupe.writeback.apply import _same_outside

CONFIG = "troupe.yml"
REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"
WORKED_EXAMPLE_AFTER = (
    "defaults: &d\n"
    "  model: opus\n"
    "coder:\n"
    "  settings:  # expanded from *d by troupe\n"
    "    model: sonnet\n"
    "reviewer:\n"
    "  settings: *d\n"
)


def _cli(theatre: Path, *args: str, env: dict[str, str] | None = None) -> CliResult:
    return run_cli("config", *args, "--theatre", str(theatre), env=env)


def _get(theatre: Path, path: str) -> str:
    result = _cli(theatre, "get", path)
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _config(theatre: Path) -> str:
    return (theatre / ".troupe" / CONFIG).read_bytes().decode("utf-8")


def _expand(
    theatre: Path, path: str, value: str, *extra: str, env: dict[str, str] | None = None
) -> list[dict[str, object]]:
    """Run ``set --expand-alias PATH VALUE`` that must succeed; return the events it recorded."""
    recorded = len(history_events(theatre))
    result = _cli(theatre, "set", "--expand-alias", path, value, *extra, env=env)
    assert (result.code, result.out, result.err) == (0, "", "")
    return history_events(theatre)[recorded:]


def _changes(events: list[dict[str, object]]) -> list[tuple[object, ...]]:
    return [(e["op"], e["path"], e["old"], e["new"]) for e in events]


def test_worked_example_is_reproduced_byte_for_byte(make_theatre: MakeTheatre) -> None:  # US4-1
    theatre = make_theatre({CONFIG: REPORTER})

    events = _expand(theatre, "coder.settings.model", "sonnet")

    assert _config(theatre) == WORKED_EXAMPLE_AFTER
    assert _get(theatre, "coder.settings.model") == "sonnet\n"
    assert _get(theatre, "reviewer.settings.model") == "opus\n"
    assert _get(theatre, "defaults.model") == "opus\n"
    assert _changes(events) == [("set", "coder.settings.model", "opus", "sonnet")]


def test_flow_anchor_is_expanded_in_block_style(make_theatre: MakeTheatre) -> None:  # US4-2
    text = "defaults: &d {model: opus, t: 1}\ncoder:\n    settings: *d\n"
    theatre = make_theatre({CONFIG: text})

    events = _expand(theatre, "coder.settings.t", "2")

    assert _config(theatre) == (
        "defaults: &d {model: opus, t: 1}\n"
        "coder:\n"
        "    settings:  # expanded from *d by troupe\n"
        "        model: opus\n"
        "        t: 2\n"
    )
    assert _changes(events) == [("set", "coder.settings.t", 1, 2)]


@pytest.mark.parametrize("value", ["x", "a-much-longer-value-than-before"])
def test_scalar_alias_is_expanded_in_place(make_theatre: MakeTheatre, value: str) -> None:
    # US4-3, C4: the comment keeps exactly two spaces whatever the new value's length
    theatre = make_theatre({CONFIG: "m: &m opus\ncoder:\n  model: *m\nother: *m\n"})

    events = _expand(theatre, "coder.model", value)

    assert _config(theatre) == (
        f"m: &m opus\ncoder:\n  model: {value}  # expanded from *m by troupe\nother: *m\n"
    )
    assert _get(theatre, "other") == "opus\n"
    assert _changes(events) == [("set", "coder.model", "opus", value)]


def test_alias_at_path_replaced_by_scalar_keeps_two_spaces(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})

    _expand(theatre, "coder.settings", "5")

    assert _config(theatre) == REPORTER.replace(
        "coder:\n  settings: *d\n", "coder:\n  settings: 5  # expanded from *d by troupe\n"
    )


def test_list_item_alias_is_expanded_under_its_dash(make_theatre: MakeTheatre) -> None:  # US4-4
    theatre = make_theatre({CONFIG: "d: &d\n  model: opus\nagents:\n  - *d\n  - *d\n"})

    events = _expand(theatre, "agents.0.model", "x")

    assert _config(theatre) == (
        "d: &d\n  model: opus\nagents:\n  -  # expanded from *d by troupe\n    model: x\n  - *d\n"
    )
    assert _changes(events) == [("set", "agents.0.model", "opus", "x")]


def test_nested_aliases_on_path_are_each_expanded_with_their_comment(
    make_theatre: MakeTheatre,
) -> None:  # US4-5, C7
    text = (
        "limits: &l\n  max: 1\n"
        "defaults: &d\n  model: opus\n  limits: *l\n"
        "coder:\n  settings: *d\n"
        "reviewer:\n  settings: *d\n"
    )
    theatre = make_theatre({CONFIG: text})

    events = _expand(theatre, "coder.settings.limits.max", "9")

    assert _config(theatre) == text.replace(
        "coder:\n  settings: *d\n",
        "coder:\n"
        "  settings:  # expanded from *d by troupe\n"
        "    model: opus\n"
        "    limits:  # expanded from *l by troupe\n"
        "      max: 9\n",
    )
    assert _get(theatre, "reviewer.settings.limits.max") == "1\n"
    assert _changes(events) == [("set", "coder.settings.limits.max", 1, 9)]


def test_aliases_inside_copy_off_path_stay_aliases(make_theatre: MakeTheatre) -> None:  # C7
    text = "limits: &l\n  max: 1\ndefaults: &d\n  model: opus\n  limits: *l\ncoder:\n  s: *d\n"
    theatre = make_theatre({CONFIG: text})

    _expand(theatre, "coder.s.model", "x")

    assert _config(theatre) == text.replace(
        "  s: *d\n", "  s:  # expanded from *d by troupe\n    model: x\n    limits: *l\n"
    )


def test_copy_drops_inner_anchor_and_comments(make_theatre: MakeTheatre) -> None:  # US4-6, C8
    text = (
        "defaults: &d\n"
        "  # about the model\n"
        "  model: &x 'opus'  # note\n"
        "  t: 1\n"
        "coder:\n"
        "  settings: *d\n"
        "other: *x\n"
    )
    theatre = make_theatre({CONFIG: text})

    _expand(theatre, "coder.settings.t", "2")

    assert _config(theatre) == text.replace(
        "  settings: *d\n",
        "  settings:  # expanded from *d by troupe\n    model: 'opus'\n    t: 2\n",
    )
    assert _get(theatre, "other") == "opus\n"


def test_redefined_anchor_that_would_repoint_a_copied_alias_is_refused(
    make_theatre: MakeTheatre,
) -> None:  # edge case: the copy's *x would resolve to the later &x
    theatre = make_theatre(
        {CONFIG: "x: &x 1\nd: &d\n  inner: *x\nx2: &x 2\ncoder:\n  settings: *d\n"}
    )
    recorded = history_events(theatre)
    before = snapshot(theatre)

    result = _cli(theatre, "set", "--expand-alias", "coder.settings.t", "2")

    assert (result.code, result.out) == (3, "")
    assert "coder.settings.t" in result.err and "no file changed" in result.err
    assert snapshot(theatre) == before
    assert history_events(theatre) == recorded


REFUSALS = {
    "flow-parent": (
        "defaults: &d\n  model: opus\ncoder: {settings: *d}\n",
        "inside a flow collection",
    ),
    "comment-on-line": (
        "defaults: &d\n  model: opus\ncoder:\n  settings: *d  # mine\n",
        "already has a comment",
    ),
    "alias-on-next-line": (
        "defaults: &d\n  model: opus\ncoder:\n  settings:\n    *d\n",
        "not on its key's line",
    ),
    "keep-block-at-end-of-copy": (
        "defaults: &d\n  s: |+\n    keep\n\nnext: 1\ncoder:\n  settings: *d\n\nz: 1\n",
        "block scalar",
    ),
}


@pytest.mark.parametrize(("text", "reason"), REFUSALS.values(), ids=REFUSALS.keys())
def test_expansion_refusals_change_nothing(
    make_theatre: MakeTheatre, text: str, reason: str
) -> None:  # US4-7, C9
    theatre = make_theatre({CONFIG: text})
    recorded = history_events(theatre)
    before = snapshot(theatre)

    result = _cli(theatre, "set", "--expand-alias", "coder.settings.model", "x")

    assert (result.code, result.out) == (3, "")
    assert result.err.startswith("troupe: ") and "coder.settings.model" in result.err
    assert reason in result.err
    assert snapshot(theatre) == before
    assert history_events(theatre) == recorded


def test_trailing_blank_lines_after_alias_stay_after_the_copy(make_theatre: MakeTheatre) -> None:
    text = "d: &d\n  m: 1\ncoder:\n  settings: *d\n\n\nz: 1\n"
    theatre = make_theatre({CONFIG: text})

    _expand(theatre, "coder.settings.m", "2")

    assert _config(theatre) == text.replace(
        "  settings: *d\n", "  settings:  # expanded from *d by troupe\n    m: 2\n"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [("plain.model", "x"), ("plain.new", "1"), ("defaults.model", "x"), ("list.1", "c")],
)
def test_expand_alias_without_alias_on_path_equals_plain_set(
    make_theatre: MakeTheatre, tmp_path: Path, path: str, value: str
) -> None:  # US4-8, C10
    text = REPORTER + "plain:\n  model: gpt\nlist: [a]\n"
    expanded = make_theatre({CONFIG: text})
    twin = tmp_path / "twin"
    (twin / ".troupe").mkdir(parents=True)
    (twin / ".troupe" / CONFIG).write_text(text, encoding="utf-8")

    expanded_events = _expand(expanded, path, value)
    plain_recorded = len(history_events(twin))
    plain = _cli(twin, "set", path, value)

    assert (plain.code, plain.out, plain.err) == (0, "", "")
    assert snapshot(expanded) == snapshot(twin)
    assert _changes(expanded_events) == _changes(history_events(twin)[plain_recorded:])


@pytest.mark.parametrize(
    "command", [("get", "defaults"), ("show",), ("history",), ("watch",)], ids=str
)
def test_expand_alias_is_rejected_by_other_subcommands(
    make_theatre: MakeTheatre, command: tuple[str, ...]
) -> None:  # US4-9, C10
    theatre = make_theatre({CONFIG: REPORTER})
    before = snapshot(theatre)

    result = _cli(theatre, *command, "--expand-alias")

    assert (result.code, result.out) == (2, "")
    assert "--expand-alias" in result.err
    assert snapshot(theatre) == before


def test_expand_alias_with_reason_records_lineage(make_theatre: MakeTheatre) -> None:  # US4-10
    theatre = make_theatre({CONFIG: REPORTER})

    events = _expand(
        theatre,
        "coder.settings.model",
        "sonnet",
        "--reason",
        "coder needs its own model",
        env={"TROUPE_ACTOR": "human:alice"},
    )

    assert _config(theatre) == WORKED_EXAMPLE_AFTER
    [event] = events
    assert (event["op"], event["path"]) == ("set", "coder.settings.model")
    assert (event["via"], event["reason"]) == ("cli", "coder needs its own model")
    assert event["actor"] == {"kind": "human", "id": "alice"}


def test_expand_alias_combines_with_in_include_in_any_order(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({CONFIG: REPORTER})
    recorded = len(history_events(theatre))

    result = _cli(
        theatre, "set", "coder.settings.model", "--in-include", "sonnet", "--expand-alias"
    )

    assert (result.code, result.out, result.err) == (0, "", "")
    assert _config(theatre) == WORKED_EXAMPLE_AFTER
    assert len(history_events(theatre)) == recorded + 1


def test_expand_alias_with_unchanged_value_writes_nothing(make_theatre: MakeTheatre) -> None:
    # R-8 no-op: checked on the resolved value before anything is expanded
    theatre = make_theatre({CONFIG: REPORTER})
    recorded = history_events(theatre)
    before = snapshot(theatre)

    result = _cli(theatre, "set", "--expand-alias", "coder.settings.model", "opus")

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == before
    assert history_events(theatre) == recorded


def test_verifier_refuses_an_expansion_that_also_replaced_another_alias(tmp_path: Path) -> None:
    # Plan Risks: PATH reads back, but reviewer's alias became a copy too; that must not pass.
    config = tmp_path / CONFIG
    config.write_text(REPORTER, encoding="utf-8")
    both_expanded = WORKED_EXAMPLE_AFTER.replace(
        "  settings: *d\n", "  settings:  # expanded from *d by troupe\n    model: opus\n"
    )
    path = ["coder", "settings", "model"]

    old = load(config)
    good = load(config, overrides={config: WORKED_EXAMPLE_AFTER})
    bad = load(config, overrides={config: both_expanded})

    assert _same_outside(old, good, [], path, expand_alias=True)
    assert not _same_outside(old, bad, [], path, expand_alias=True)
    assert not _same_outside(old, good, [], path, expand_alias=False)
