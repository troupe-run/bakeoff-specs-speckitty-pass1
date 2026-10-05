"""Acceptance for include overrides: edges, refusals, history and watch (WP05).

Everything runs through the real CLI against real files and the real event store. Successful
writes compare the bytes of **every** theatre file before and after; refusals check the exit
code, an empty stdout, a one-line stderr naming PATH or the file, that no file changed and that
no event was recorded (NFR-003).

Covered here (spec references in each section): conversion edges (US2-2, US2-5 to US2-7, D-3 to
D-5, CRLF), refusals (D-1, D-6, D-10, D-11), history and reconcile (FR-013, step-2 rules),
``watch``, and chained mapping-form includes (``--in-include`` into the innermost file, D-8).
Already covered elsewhere and not repeated: the contract example and quickstart
(``test_set_overrides.py``, ``test_set_in_include.py``), and includes written with an anchor or
tag (``test_set_overrides.py``: exit 4 at load, converter backstop exit 3).
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
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.paths import parse_path
from troupe.tree import SourceFile
from troupe.values import Value, parse_value
from troupe.writeback import TextEdit, apply
from troupe.writeback.apply import WritePlan, apply_set
from troupe.writeback.placement import AddKeys, Placement, place

type Files = dict[str, str | bytes]
type Event = dict[str, object]

CODER = "agents/coder.yaml"


def _set(theatre: Path, *args: str) -> CliResult:
    return run_cli("config", "set", *args, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
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


def _check(
    make_theatre: MakeTheatre,
    files: Files,
    args: tuple[str, ...],
    expected: Files,
    shown: dict[str, str],
) -> Path:
    """Build ``files``, run ``set *args``; assert every file's bytes and ``get`` of each leaf.

    ``expected`` lists only the files that change; every other file must be byte-identical.
    """
    theatre = make_theatre(files)
    result = _set(theatre, *args)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes({**files, **expected})
    for leaf, printed in shown.items():
        assert _get(theatre, leaf) == printed
    return theatre


def _assert_refused(
    theatre: Path, args: tuple[str, ...], code: int, names: str, *, command: str = "set"
) -> None:
    """Run ``command *args``: exit ``code``, nothing on stdout, one stderr line naming ``names``,
    no file changed and no event recorded."""
    events = history_events(theatre)
    before = snapshot(theatre)

    result = run_cli("config", command, *args, "--theatre", str(theatre))

    assert (result.code, result.out) == (code, ""), result.err
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1, result.err
    assert result.err.endswith("\n")
    assert names in result.err
    assert snapshot(theatre) == before
    assert history_events(theatre) == events


# --- T024: conversion acceptance (FR-006; US2-2, US2-5 to US2-7; D-3, D-4, D-5) ----------------


def test_four_space_file_converts_with_four_space_indentation(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "agents:\n    coder: file:agents/coder.yaml\n    other: 1\n",
        CODER: "model: gpt\n",
    }
    _check(
        make_theatre,
        files,
        ("agents.coder.temperature", "0.3"),
        {
            "troupe.yml": (
                "agents:\n    coder:\n        $ref: file:agents/coder.yaml\n"
                "        temperature: 0.3\n    other: 1\n"
            )
        },
        {"agents.coder.temperature": "0.3\n", "agents.coder.model": "gpt\n"},
    )


def test_nested_include_override_lands_in_nearest_including_file(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder: file:agents/coder.yaml\n",
        CODER: "model: file:models/base.yaml\n",
        "agents/models/base.yaml": "name: gpt\n",
    }
    _check(
        make_theatre,
        files,
        ("coder.model.temperature", "0.3"),
        {CODER: "model:\n  $ref: file:models/base.yaml\n  temperature: 0.3\n"},
        {"coder.model.temperature": "0.3\n", "coder.model.name": "gpt\n"},
    )


def test_flow_parent_include_converts_in_flow_style(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "agents: {coder: file:x.yaml}\n", "x.yaml": "model: gpt\n"}
    _check(
        make_theatre,
        files,
        ("agents.coder.t", "1"),
        {"troupe.yml": "agents: {coder: {$ref: file:x.yaml, t: 1}}\n"},
        {"agents.coder.t": "1\n", "agents.coder.model": "gpt\n"},
    )


def test_list_item_include_converts_in_place(make_theatre: MakeTheatre) -> None:
    files: Files = {"troupe.yml": "list:\n  - file:a.yaml\n  - 2\n", "a.yaml": "name: a\n"}
    _check(
        make_theatre,
        files,
        ("list.0.k", "1"),
        {"troupe.yml": "list:\n  - $ref: file:a.yaml\n    k: 1\n  - 2\n"},
        {"list.0.k": "1\n", "list.0.name": "a\n", "list.1": "2\n"},
    )


@pytest.mark.parametrize(
    "written", ['"file:agents/coder.yaml"', "'file:agents/coder.yaml'"], ids=["double", "single"]
)
def test_quoted_include_string_is_moved_verbatim(make_theatre: MakeTheatre, written: str) -> None:
    files: Files = {"troupe.yml": f"coder: {written}  # c\n", CODER: "model: gpt\n"}
    _check(
        make_theatre,
        files,
        ("coder.temperature", "0.3"),
        {"troupe.yml": f"coder:  # c\n  $ref: {written}\n  temperature: 0.3\n"},
        {"coder.temperature": "0.3\n", "coder.model": "gpt\n"},
    )


def test_override_value_that_is_itself_an_include_is_converted_in_place(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder: {$ref: file:a.yaml, model: file:m.yaml}\n",
        "a.yaml": "model: {x: 1}\n",
        "m.yaml": "z: 3\n",
    }
    _check(
        make_theatre,
        files,
        ("coder.model.y", "2"),
        {"troupe.yml": "coder: {$ref: file:a.yaml, model: {$ref: file:m.yaml, y: 2}}\n"},
        {"coder.model.y": "2\n", "coder.model.x": "1\n", "coder.model.z": "3\n"},
    )


def test_crlf_including_file_keeps_crlf_after_conversion(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "name: t\r\ncoder: file:agents/coder.yaml  # c\r\nother: 1\r\n",
        CODER: "model: gpt\r\n",
    }
    _check(
        make_theatre,
        files,
        ("coder.temperature", "0.3"),
        {
            "troupe.yml": (
                "name: t\r\ncoder:  # c\r\n  $ref: file:agents/coder.yaml\r\n"
                "  temperature: 0.3\r\nother: 1\r\n"
            )
        },
        {"coder.temperature": "0.3\n", "coder.model": "gpt\n"},
    )


# --- T025: refusal acceptance (FR-003, FR-012; D-1, D-6, D-10, D-11; NFR-003) -----------------


@pytest.mark.parametrize(
    "including",
    ["coder: file:agents/coder.yaml\n", "coder: {$ref: file:agents/coder.yaml, top_p: 1}\n"],
    ids=["scalar-form", "mapping-form"],
)
def test_ref_segment_in_path_is_refused(make_theatre: MakeTheatre, including: str) -> None:
    theatre = make_theatre({"troupe.yml": including, CODER: "model: gpt\n"})

    for path in ("coder.$ref", "coder.$ref.x", "coder.model.$ref"):
        _assert_refused(theatre, (path, "file:agents/other.yaml"), 3, path)
        _assert_refused(theatre, ("--in-include", path, "1"), 3, path)
    for command in ("get", "show"):
        _assert_refused(theatre, ("coder.$ref",), 5, "coder.$ref", command=command)


def test_replacing_partly_overridden_mapping_is_refused(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(
        {
            "troupe.yml": "coder: {$ref: file:agents/coder.yaml, tools: {web: true}}\n",
            CODER: "model: gpt\ntools: {shell: true}\n",
        }
    )
    _assert_refused(theatre, ("coder.tools", "{x: 1}"), 3, "coder.tools")
    _assert_refused(theatre, ("--in-include", "coder.tools", "{x: 1}"), 3, "coder.tools")


def test_replacing_one_sided_mapping_under_merge_is_written_in_its_file(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  extra:\n    a: 1\n",
        CODER: "model: gpt\nlimits:\n  max: 5\n",
    }
    # Defined only by the included file: replaced there, the including file untouched.
    _check(
        make_theatre,
        files,
        ("coder.limits", "{max: 6, min: 1}"),
        {CODER: "model: gpt\nlimits:\n  max: 6\n  min: 1\n"},
        {"coder.limits.max": "6\n", "coder.limits.min": "1\n"},
    )
    # Defined only by the override: replaced there, the included file untouched.
    _check(
        make_theatre,
        files,
        ("coder.extra", "{b: 2}"),
        {"troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  extra:\n    b: 2\n"},
        {"coder.extra.b": "2\n", "coder.model": "gpt\n"},
    )


@pytest.mark.parametrize(
    "including",
    [
        "name: t\ncoder: |-\n  file:agents/coder.yaml\n",
        "name: t\ncoder: >-\n  file:agents/coder.yaml\n",
        # a double-quoted string wrapped with an escaped line break reads file:agents/coder.yaml
        'name: t\ncoder: "file:agents/\\\n  coder.yaml"\n',
    ],
    ids=["literal-block", "folded-block", "wrapped-quoted"],
)
def test_multiline_include_string_conversion_is_refused(
    make_theatre: MakeTheatre, including: str
) -> None:
    theatre = make_theatre({"troupe.yml": including, CODER: "model: gpt\n"})
    assert _get(theatre, "coder.model") == "gpt\n"  # it is an include, read as usual

    _assert_refused(theatre, ("coder.temperature", "0.3"), 3, "troupe.yml")
    # Without conversion the same include is still writable: --in-include and existing values.
    result = _set(theatre, "--in-include", "coder.temperature", "0.3")
    assert (result.code, result.out, result.err) == (0, "", "")
    assert _get(theatre, "coder.temperature") == "0.3\n"


@pytest.mark.parametrize(
    "including",
    [
        "coder: {$ref: 5}\n",
        "coder:\n  $ref: agents/coder.yaml\n  t: 1\n",
        "coder:\n  $ref: [file:agents/coder.yaml]\n",
    ],
    ids=["number", "no-file-prefix", "list"],
)
@pytest.mark.parametrize(
    "args",
    [("get", "coder.model"), ("show",), ("set", "coder.temperature", "0.3")],
    ids=["get", "show", "set"],
)
def test_malformed_ref_makes_every_command_exit_4(
    make_theatre: MakeTheatre, including: str, args: tuple[str, ...]
) -> None:
    files: Files = {"troupe.yml": including, CODER: "model: gpt\n"}
    theatre = make_theatre(files)

    result = run_cli("config", *args, "--theatre", str(theatre))

    assert (result.code, result.out) == (4, ""), result.err
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert "troupe.yml" in result.err and "$ref" in result.err
    assert snapshot(theatre) == _bytes(files)
    # The history cannot even be read (the configuration does not load), so nothing was recorded:
    # the event store was never created.
    assert not (theatre / ".troupe" / "history.sqlite").exists()


# --- T026: history, reconcile and watch (FR-013) -----------------------------------------------

SCALAR_FORM: Files = {
    "troupe.yml": "coder: file:agents/coder.yaml  # c\n",
    CODER: "model: gpt\ntemperature: 0.7\n",
}


def test_override_set_records_exactly_one_event_with_cli_lineage(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(SCALAR_FORM)
    imported = history_events(theatre)
    assert [(e["op"], e["path"]) for e in imported] == [
        ("import", "coder.model"),
        ("import", "coder.temperature"),
    ]

    result = _set(theatre, "coder.limits.max", "5")  # converts and creates a nested override
    assert (result.code, result.out, result.err) == (0, "", "")

    events = history_events(theatre)
    assert events[: len(imported)] == imported
    [event] = events[len(imported) :]  # no remove/set for the unchanged merged leaves
    assert (event["op"], event["path"], event["old"], event["new"]) == (
        "set",
        "coder.limits.max",
        None,
        5,
    )
    assert event["via"] == "cli"
    assert _get(theatre, "coder.limits.max") == "5\n"


def test_hand_written_conversion_without_value_change_records_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(SCALAR_FORM)
    imported = history_events(theatre)
    _write(theatre, "troupe.yml", "coder:  # c\n  $ref: file:agents/coder.yaml\n")
    edited = snapshot(theatre)

    assert _get(theatre, "coder.temperature") == "0.7\n"
    assert history_events(theatre) == imported
    assert snapshot(theatre) == edited


def test_hand_added_override_records_set_for_changed_leaf_only(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(SCALAR_FORM)
    imported = history_events(theatre)
    # ``model: gpt`` repeats the included value, so its merged leaf does not change.
    _write(
        theatre,
        "troupe.yml",
        "coder:  # c\n  $ref: file:agents/coder.yaml\n  model: gpt\n  temperature: 0.3\n"
        "  top_p: 0.9\n",
    )

    assert _get(theatre, "coder.temperature") == "0.3\n"
    events = history_events(theatre)
    assert events[: len(imported)] == imported
    n = len(imported)
    assert core(events[n:]) == [
        {"seq": n + 1, "op": "set", "path": "coder.temperature", "old": 0.7, "new": 0.3},
        {"seq": n + 2, "op": "set", "path": "coder.top_p", "old": None, "new": 0.9},
    ]


def test_watch_records_set_written_override_once(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(SCALAR_FORM)
    with WatchProcess("--theatre", str(theatre)) as w:
        w.wait_ready()
        imported = history_events(theatre)
        result = _set(theatre, "coder.top_p", "0.9")
        set_at = time.monotonic()
        assert (result.code, result.out, result.err) == (0, "", "")
        written = snapshot(theatre)

        events = recorded_within(theatre, set_at)
        stopped = w.stop()

    assert events[: len(imported)] == imported
    [event] = events[len(imported) :]
    assert (event["op"], event["path"], event["old"], event["new"], event["via"]) == (
        "set",
        "coder.top_p",
        None,
        0.9,
        "cli",
    )
    assert written == _bytes(
        {**SCALAR_FORM, "troupe.yml": "coder:  # c\n  $ref: file:agents/coder.yaml\n  top_p: 0.9\n"}
    )
    assert snapshot(theatre) == written  # watch wrote nothing
    assert stopped == (0, "", "")


# --- Chained mapping-form includes (bead c3z; D-8, research R-3 ``_on_base``) -----------------

CHAINED: Files = {
    "troupe.yml": "coder:\n  $ref: file:c.yaml\n  top_p: 1\n",
    "c.yaml": "$ref: file:b.yaml\nmid: 1\n",
    "b.yaml": "model: gpt\n",
}


def test_in_include_under_chained_mapping_form_includes_writes_innermost_file(
    make_theatre: MakeTheatre,
) -> None:
    theatre = _check(
        make_theatre,
        CHAINED,
        ("--in-include", "coder.newk", "2"),
        {"b.yaml": "model: gpt\nnewk: 2\n"},
        {"coder.newk": "2\n", "coder.mid": "1\n", "coder.top_p": "1\n", "coder.model": "gpt\n"},
    )
    shown = run_cli("config", "show", "coder", "--sources", "--theatre", str(theatre))
    assert (shown.code, shown.err) == (0, "")
    assert shown.out == (
        "model: gpt # from .troupe/b.yaml\n"
        "newk: 2 # from .troupe/b.yaml\n"
        "mid: 1 # from .troupe/c.yaml\n"
        "top_p: 1 # from .troupe/troupe.yml\n"
    )


def test_new_key_under_chained_mapping_form_includes_becomes_root_override(
    make_theatre: MakeTheatre,
) -> None:
    _check(
        make_theatre,
        CHAINED,
        ("coder.newk", "2"),
        {"troupe.yml": "coder:\n  $ref: file:c.yaml\n  top_p: 1\n  newk: 2\n"},
        {"coder.newk": "2\n", "coder.mid": "1\n", "coder.model": "gpt\n"},
    )


def test_placement_under_chained_includes_targets_innermost_mapping(tmp_path: Path) -> None:
    config = _theatre_files(tmp_path, CHAINED)
    placement = place(load(config), ["coder", "newk"], "coder.newk", in_include=True)
    assert isinstance(placement, AddKeys)
    assert placement.mapping.origin.file.path == (tmp_path / "b.yaml").resolve()
    assert placement.keys == ["newk"]


def _theatre_files(tmp_path: Path, files: Files) -> Path:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return tmp_path / "troupe.yml"


def _plan_with_rendering(
    monkeypatch: pytest.MonkeyPatch, config: Path, written: str, new_text: str
) -> WritePlan:
    """Run ``apply_set --in-include coder.newk 2`` with ``written``'s new text forced.

    Verification reads only ``path`` and the new text of each written file.
    """
    root = load(config)
    path = (config.parent / written).resolve()
    file = SourceFile(path, path.read_text(encoding="utf-8"))

    def crafted(
        placement: Placement, path: str, parsed: Value
    ) -> tuple[SourceFile, list[TextEdit]]:
        return file, [TextEdit(0, len(file.text), new_text)]

    monkeypatch.setattr(apply, "_edits", crafted)
    return apply_set(
        root, parse_path("coder.newk"), "coder.newk", parse_value("2"), "2", in_include=True
    )


def test_verifier_accepts_new_key_at_end_of_innermost_base_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _theatre_files(tmp_path, CHAINED)
    plan = _plan_with_rendering(monkeypatch, config, "b.yaml", "model: gpt\nnewk: 2\n")
    assert list(plan.files.values()) == ["model: gpt\nnewk: 2\n"]


@pytest.mark.parametrize(
    ("written", "new_text"),
    [
        # in the innermost file, but before its existing key
        ("b.yaml", "newk: 2\nmodel: gpt\n"),
        # in the middle file, but before its existing key
        ("c.yaml", "$ref: file:b.yaml\nnewk: 2\nmid: 1\n"),
        # in the root override, but before the existing override-only key
        ("troupe.yml", "coder:\n  $ref: file:c.yaml\n  newk: 2\n  top_p: 1\n"),
    ],
    ids=["innermost-first", "middle-before-mid", "root-before-top_p"],
)
def test_verifier_refuses_new_key_elsewhere_under_chained_includes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, written: str, new_text: str
) -> None:
    config = _theatre_files(tmp_path, CHAINED)
    with pytest.raises(WriteRefused):
        _plan_with_rendering(monkeypatch, config, written, new_text)
