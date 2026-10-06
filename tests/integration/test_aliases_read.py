"""Reading configurations with anchors, aliases and merge keys through the real CLI (spec US1).

Spec A-0, C1, C2, C3, C13; FR-001, FR-002. Reads (``get``, ``show``, ``show --sources``,
``history``) see resolved values; unsupported anchor uses make every loading command exit 4,
naming the file. A plain ``set`` through an alias is refused (exit 3) and nothing changes; writes
at the anchor and ``--expand-alias`` are tested in ``test_set_aliases.py`` and
``test_set_expand_alias.py``.
"""

from pathlib import Path

import pytest

from conftest import CliResult, MakeTheatre, core, history_events, run_cli, snapshot

REPORTER = "defaults: &d\n  model: opus\ncoder:\n  settings: *d\nreviewer:\n  settings: *d\n"


def _cli(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = _cli(theatre, "get", path)
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def test_get_through_alias_prints_anchored_value(make_theatre: MakeTheatre) -> None:  # US1-1
    theatre = make_theatre({"troupe.yml": REPORTER})

    assert _get(theatre, "coder.settings.model") == "opus\n"
    assert _get(theatre, "reviewer.settings.model") == "opus\n"


def test_show_prints_resolved_values_without_anchor_alias_or_merge_syntax(
    make_theatre: MakeTheatre,
) -> None:  # US1-1, C1
    text = REPORTER + "base: &b {t: 1, list: &l [a, b]}\nmerged: {<<: *b, own: *l}\n"
    theatre = make_theatre({"troupe.yml": text})

    result = _cli(theatre, "show")

    assert (result.code, result.err) == (0, "")
    assert result.out == (
        "defaults:\n"
        "  model: opus\n"
        "coder:\n"
        "  settings:\n"
        "    model: opus\n"
        "reviewer:\n"
        "  settings:\n"
        "    model: opus\n"
        "base:\n"
        "  t: 1\n"
        "  list:\n"
        "    - a\n"
        "    - b\n"
        "merged:\n"
        "  t: 1\n"
        "  list:\n"
        "    - a\n"
        "    - b\n"
        "  own:\n"
        "    - a\n"
        "    - b\n"
    )
    assert _cli(theatre, "show", "coder").out == "settings:\n  model: opus\n"
    assert _cli(theatre, "show", "merged.own").out == "- a\n- b\n"


def test_merge_key_reads_written_key_over_merged_key(make_theatre: MakeTheatre) -> None:  # US1-2
    theatre = make_theatre({"troupe.yml": "base: &b {model: opus, t: 1}\ncoder: {<<: *b, t: 2}\n"})

    assert _get(theatre, "coder.t") == "2\n"
    assert _get(theatre, "coder.model") == "opus\n"


def test_earlier_merge_source_wins_on_read(make_theatre: MakeTheatre) -> None:  # US1-3
    text = "a: &a {model: A}\nb: &b {model: B, x: 1}\ncoder: {<<: [*a, *b]}\n"
    theatre = make_theatre({"troupe.yml": text})

    assert _get(theatre, "coder.model") == "A\n"
    assert _get(theatre, "coder.x") == "1\n"


def test_show_sources_attributes_aliased_scalar_to_anchor_file(
    make_theatre: MakeTheatre,
) -> None:  # US1-4, C1
    theatre = make_theatre({"troupe.yml": REPORTER})

    result = _cli(theatre, "show", "coder", "--sources")

    assert (result.code, result.err) == (0, "")
    assert result.out == "settings:\n  model: opus # from .troupe/troupe.yml\n"


def test_aliases_inside_included_file_resolve(make_theatre: MakeTheatre) -> None:  # US1-5
    included = "base: &b\n  model: opus\nagent:\n  <<: *b\n  t: 1\nother: *b\n"
    theatre = make_theatre({"troupe.yml": "coder: file:agents/x.yaml\n", "agents/x.yaml": included})

    assert _get(theatre, "coder.agent.model") == "opus\n"
    assert _get(theatre, "coder.other.model") == "opus\n"
    result = _cli(theatre, "show", "coder.agent", "--sources")
    assert (
        result.out
        == "model: opus # from .troupe/agents/x.yaml\nt: 1 # from .troupe/agents/x.yaml\n"
    )


UNSUPPORTED = {
    "tag": "a: !t 1\n",
    "anchored-include": "coder: &c file:x.yaml\n",
    "anchor-containing-include": "d: &d\n  coder: file:x.yaml\n",
    "anchored-key": "a: 1\n&k b: 2\n",
    "alias-key": "a: &k b\nc:\n  *k : 2\n",
    "undefined-alias": "a: *nope\n",
    "merge-scalar": "c:\n  <<: 5\n",
    "merge-beside-ref": "d: &d {x: 1}\ncoder: {$ref: file:x.yaml, <<: *d}\n",
}
COMMANDS = {
    "get": ("get", "a"),
    "show": ("show",),
    "set": ("set", "a", "1"),
    "history": ("history",),
}


@pytest.mark.parametrize("text", UNSUPPORTED.values(), ids=UNSUPPORTED.keys())
@pytest.mark.parametrize("command", COMMANDS.values(), ids=COMMANDS.keys())
def test_unsupported_anchor_uses_make_every_command_exit_4(
    make_theatre: MakeTheatre, text: str, command: tuple[str, ...]
) -> None:  # US1-6
    theatre = make_theatre({"troupe.yml": text, "x.yaml": "model: gpt\n"})
    before = snapshot(theatre)

    result = _cli(theatre, *command)

    assert (result.code, result.out) == (4, "")
    assert str((theatre / ".troupe" / "troupe.yml").resolve()) in result.err
    assert snapshot(theatre) == before


def test_history_import_records_resolved_alias_leaves(make_theatre: MakeTheatre) -> None:  # C1
    theatre = make_theatre({"troupe.yml": REPORTER + "merged: {<<: *d, t: 1}\n"})

    events = core(history_events(theatre))

    assert [(event["op"], event["path"], event["new"]) for event in events] == [
        ("import", "defaults.model", "opus"),
        ("import", "coder.settings.model", "opus"),
        ("import", "reviewer.settings.model", "opus"),
        ("import", "merged.model", "opus"),
        ("import", "merged.t", 1),
    ]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("coder.settings.model", "sonnet"),
        ("coder.settings", "{model: x}"),
        ("coder.settings", "[a]"),
    ],
)
def test_set_through_alias_is_refused_and_changes_nothing(
    make_theatre: MakeTheatre, path: str, value: str
) -> None:
    theatre = make_theatre({"troupe.yml": REPORTER})
    recorded = history_events(theatre)
    before = snapshot(theatre)

    result = _cli(theatre, "set", path, value)

    assert (result.code, result.out) == (3, "")
    assert path in result.err and "no file changed" in result.err
    assert snapshot(theatre) == before
    assert history_events(theatre) == recorded
    assert _get(theatre, "coder.settings.model") == "opus\n"
