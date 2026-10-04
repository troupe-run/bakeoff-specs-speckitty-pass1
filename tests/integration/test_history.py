"""``troupe config history [PATH]`` through the real CLI: import, output format, confinement.

Every line any test here reads is checked against contracts/history-event.schema.json by
``_valid_record``, lineage included (FR-001).
"""

import json
import re
from pathlib import Path
from typing import Any

from conftest import HISTORY_PREFIX, MakeTheatre, all_files, core, run_cli, snapshot

FIXTURE: dict[str, str | bytes] = {
    "troupe.yml": (
        "model:\n"
        "  name: gpt\n"
        "  temperature: 0.2\n"
        "tools:\n"
        "  - search\n"
        "  - true\n"
        "agents:\n"
        "  coder: file:agents/coder.yaml\n"
        "prompt: file:prompt.md\n"
        "retries: null\n"
    ),
    "agents/coder.yaml": "name: Cody\nlevel: 3\n",
    "prompt.md": "Be kind.\n",
}

FIXTURE_IMPORT = [
    {"seq": 1, "op": "import", "path": "model.name", "old": None, "new": "gpt"},
    {"seq": 2, "op": "import", "path": "model.temperature", "old": None, "new": 0.2},
    {"seq": 3, "op": "import", "path": "tools.0", "old": None, "new": "search"},
    {"seq": 4, "op": "import", "path": "tools.1", "old": None, "new": True},
    {"seq": 5, "op": "import", "path": "agents.coder.name", "old": None, "new": "Cody"},
    {"seq": 6, "op": "import", "path": "agents.coder.level", "old": None, "new": 3},
    {"seq": 7, "op": "import", "path": "prompt", "old": None, "new": "Be kind.\n"},
    {"seq": 8, "op": "import", "path": "retries", "old": None, "new": None},
]

# contracts/cli.md, "line format": the order of the keys on every line.
KEYS = ["seq", "op", "path", "old", "new", "actor", "via", "at", "reason", "change"]
JSON_SCALARS = (str, int, float, bool, type(None))
ACTOR_KINDS = ("human", "agent", "unknown")
VIAS = ("import", "cli", "file", None)
AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")


def _history(theatre: Path, *path: str) -> list[dict[str, Any]]:
    result = run_cli("config", "history", *path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, "")
    return [_valid_record(line) for line in result.out.splitlines()]


def _valid_record(line: str) -> dict[str, Any]:
    """Parse one line and check it against contracts/history-event.schema.json."""
    record: dict[str, Any] = json.loads(line)
    assert list(record) == KEYS
    assert type(record["seq"]) is int and record["seq"] >= 1
    assert record["op"] in ("import", "set", "remove")
    assert isinstance(record["path"], str)
    assert isinstance(record["old"], JSON_SCALARS)
    assert isinstance(record["new"], JSON_SCALARS)
    if record["op"] == "import":
        assert record["old"] is None
    if record["op"] == "remove":
        assert record["new"] is None
    actor = record["actor"]
    assert isinstance(actor, dict) and list(actor) == ["kind", "id"]
    assert actor["kind"] in ACTOR_KINDS
    assert actor["id"] is None or (isinstance(actor["id"], str) and actor["id"] != "")
    if actor["kind"] == "unknown":
        assert actor["id"] is None
    assert record["via"] in VIAS
    if record["via"] is None:  # only a pre-lineage set/remove (DM 01M436RBNQT22F9AM54QER2FT9)
        assert record["op"] in ("set", "remove")
    if record["via"] in ("import", "file"):
        assert actor["kind"] == "unknown" and record["reason"] is None
    assert isinstance(record["at"], str) and AT.fullmatch(record["at"])
    assert record["reason"] is None or isinstance(record["reason"], str)
    assert isinstance(record["change"], str) and record["change"] != ""
    return record


def _core_prefix(event: dict[str, Any]) -> str:
    """Return the exact text a line starts with: the five step-1 keys, then the ``actor`` key."""
    return json.dumps(event, ensure_ascii=False)[: -len("}")] + ', "actor": '


def test_history_on_fresh_theatre_imports_every_leaf_in_document_order(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.err) == (0, "")
    lines = result.out.splitlines(keepends=True)
    assert len(lines) == len(FIXTURE_IMPORT)
    for line, event in zip(lines, FIXTURE_IMPORT, strict=True):
        assert line.startswith(_core_prefix(event))
        assert line.endswith("}\n")
    assert core([_valid_record(line) for line in lines]) == FIXTURE_IMPORT


def test_history_output_keeps_non_ascii_text_unescaped(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "name: Zoë\n"})

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert result.out.startswith(
        '{"seq": 1, "op": "import", "path": "name", "old": null, "new": "Zoë", "actor": '
    )
    assert result.out.endswith("}\n") and result.out.count("\n") == 1
    _valid_record(result.out)


def test_second_history_run_does_not_reimport(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    first = _history(theatre)

    second = _history(theatre)

    assert second == first
    assert core(first) == FIXTURE_IMPORT


def test_history_does_not_reconcile_a_hand_edit(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\nb: 2\n"})
    imported = _history(theatre)

    (theatre / ".troupe" / "troupe.yml").write_text("a: 100\nc: 3\n", encoding="utf-8")

    assert _history(theatre) == imported
    assert [r["path"] for r in imported] == ["a", "b"]

    shown = run_cli("config", "get", "a", "--theatre", str(theatre))

    assert (shown.code, shown.out, shown.err) == (0, "100\n", "")
    assert core(_history(theatre)) == [
        *core(imported),
        {"seq": 3, "op": "set", "path": "a", "old": 1, "new": 100},
        {"seq": 4, "op": "set", "path": "c", "old": None, "new": 3},
        {"seq": 5, "op": "remove", "path": "b", "old": 2, "new": None},
    ]


def test_history_of_empty_configuration_prints_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": ""})

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.out, result.err) == (0, "", "")
    assert (theatre / HISTORY_PREFIX).is_file()


def test_history_path_filter_matches_exact_and_dotted_prefix_only(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(
        {"troupe.yml": "model: m\nmodels:\n  a: 1\nmodel_x: 2\nmodel2:\n  model: 3\n"}
    )

    assert [r["path"] for r in _history(theatre, "model")] == ["model"]
    assert [r["path"] for r in _history(theatre, "models")] == ["models.a"]
    assert [r["path"] for r in _history(theatre, "models.a")] == ["models.a"]


def test_history_path_filter_keeps_original_seq(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)

    filtered = _history(theatre, "agents.coder")

    assert core(filtered) == FIXTURE_IMPORT[4:6]


def test_history_path_filter_matching_nothing_prints_nothing_and_exits_0(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    result = run_cli("config", "history", "nope.nothing", "--theatre", str(theatre))

    assert (result.code, result.out, result.err) == (0, "", "")


def test_history_path_with_empty_segment_exits_2_and_creates_nothing(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)
    before = all_files(theatre)

    result = run_cli("config", "history", "model..name", "--theatre", str(theatre))

    assert (result.code, result.out) == (2, "")
    assert "model..name" in result.err
    assert all_files(theatre) == before


def test_history_creates_only_history_files_under_dot_troupe(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    files_before = all_files(theatre)
    bytes_before = snapshot(theatre)

    _history(theatre)

    created = all_files(theatre) - files_before
    assert HISTORY_PREFIX in created
    assert all(rel.startswith(HISTORY_PREFIX) for rel in created)
    assert snapshot(theatre) == bytes_before


def test_load_failure_creates_no_history_file(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: file:missing.yaml\n"})
    files_before = all_files(theatre)

    result = run_cli("config", "history", "--theatre", str(theatre))

    assert (result.code, result.out) == (4, "")
    assert "missing.yaml" in result.err
    assert all_files(theatre) == files_before
    assert not any(rel.startswith(HISTORY_PREFIX) for rel in all_files(theatre))


def test_load_failure_after_import_appends_nothing(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre({"troupe.yml": "a: 1\n"})
    imported = _history(theatre)
    config = theatre / ".troupe" / "troupe.yml"

    config.write_text("a: [unclosed\n", encoding="utf-8")
    failed = run_cli("config", "history", "--theatre", str(theatre))
    config.write_text("a: 1\n", encoding="utf-8")

    assert failed.code == 4
    assert _history(theatre) == imported


# --- Lineage in the output (FR-001, NFR-003, contracts/cli.md) ---------------------------------


def _history_text(theatre: Path, *path: str) -> str:
    result = run_cli("config", "history", *path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _run_ok(theatre: Path, *args: str, env: dict[str, str] | None = None) -> None:
    result = run_cli("config", *args, "--theatre", str(theatre), env=env)
    assert (result.code, result.err) == (0, ""), result.err


def _with_every_producer(make_theatre: MakeTheatre) -> Path:
    """Return a theatre whose history has import, cli (with a reason) and file events."""
    theatre = make_theatre(FIXTURE)
    _run_ok(
        theatre,
        "set",
        "model.temperature",
        "0.5",
        "--reason",
        "warmer",
        env={"TROUPE_ACTOR": "agent:planner"},
    )
    coder = theatre / ".troupe" / "agents" / "coder.yaml"
    coder.write_text("name: Cody\nlevel: 4\n", encoding="utf-8")
    _run_ok(theatre, "get", "agents.coder.level")  # reconciles the hand edit: via "file"
    return theatre


def test_history_lines_have_lineage_keys_in_contract_order(make_theatre: MakeTheatre) -> None:
    theatre = _with_every_producer(make_theatre)

    lines = _history_text(theatre).splitlines()

    assert len(lines) == len(FIXTURE_IMPORT) + 2
    for line in lines:
        assert list(json.loads(line)) == KEYS
        assert list(json.loads(line)["actor"]) == ["kind", "id"]
    records = [_valid_record(line) for line in lines]
    assert [r["via"] for r in records] == ["import"] * len(FIXTURE_IMPORT) + ["cli", "file"]
    assert records[-2]["actor"] == {"kind": "agent", "id": "planner"}
    assert records[-2]["reason"] == "warmer"
    assert records[-1]["actor"] == {"kind": "unknown", "id": None}


def test_import_lines_show_unknown_actor_via_import_and_one_change(
    make_theatre: MakeTheatre,
) -> None:
    theatre = make_theatre(FIXTURE)

    records = _history(theatre)

    assert core(records) == FIXTURE_IMPORT
    assert {json.dumps(r["actor"]) for r in records} == {'{"kind": "unknown", "id": null}'}
    assert {r["via"] for r in records} == {"import"}
    assert {r["reason"] for r in records} == {None}
    assert len({r["change"] for r in records}) == 1
    assert len({r["at"] for r in records}) == 1


def test_history_path_filter_keeps_full_lineage(make_theatre: MakeTheatre) -> None:
    theatre = _with_every_producer(make_theatre)
    unfiltered = _history_text(theatre).splitlines(keepends=True)

    for path in ("model", "model.temperature", "agents.coder"):
        filtered = _history_text(theatre, path).splitlines(keepends=True)

        expected = [
            line
            for line in unfiltered
            if (p := json.loads(line)["path"]) == path or p.startswith(path + ".")
        ]
        assert filtered == expected
        assert filtered != []
        for line in filtered:
            _valid_record(line)


def test_history_output_is_identical_across_runs(make_theatre: MakeTheatre) -> None:
    theatre = _with_every_producer(make_theatre)

    first = _history_text(theatre)
    second = _history_text(theatre)

    assert first == second
    assert first.count("\n") == len(FIXTURE_IMPORT) + 2


def test_history_prints_reason_with_json_escaping(make_theatre: MakeTheatre) -> None:
    theatre = make_theatre(FIXTURE)
    reason = 'say "hi"\nnow ü'

    _run_ok(theatre, "set", "model.name", "o1", "--reason", reason)

    line = _history_text(theatre, "model.name").splitlines()[-1]
    record = _valid_record(line)
    assert core([record]) == [
        {"seq": 9, "op": "set", "path": "model.name", "old": "gpt", "new": "o1"}
    ]
    assert record["reason"] == reason
    assert '"reason": "say \\"hi\\"\\nnow ü"' in line
    assert "\\u00fc" not in line
