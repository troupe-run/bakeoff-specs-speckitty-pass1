"""``set`` with include overrides (US2 core, US3), through the real CLI and real files.

Contract *Overrides* (spec FR-005 to FR-009, FR-012, FR-013; NFR-001 to NFR-003): a new key
under content from an included file becomes an override in the including file (a scalar-form
include is first converted to mapping form); existing values change where they live; lists stay
in their file; replacing a whole include is refused. Every successful test compares the bytes of
**every** theatre file and reads each new leaf back with ``get``; refusals check that no file
changed and that no event of the ``set``'s own was recorded.

The last section checks the in-memory verification allowance (research R-5) directly through
``apply_set`` with a crafted rendering, because the CLI's renderers never produce an off-route
structural change: those are exactly the renderer bugs the verifier must still refuse.
"""

from pathlib import Path
from typing import Any

import pytest

from conftest import CliResult, MakeTheatre, history_events, run_cli, snapshot
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.paths import parse_path
from troupe.tree import (
    MappingNode,
    MergedMapping,
    Node,
    Origin,
    SequenceNode,
    SourceFile,
    YamlInclude,
)
from troupe.values import Value, parse_value
from troupe.writeback import TextEdit, apply
from troupe.writeback.apply import WritePlan, apply_set
from troupe.writeback.collections import convert_include_edits
from troupe.writeback.placement import ConvertInclude, Placement, place

type Files = dict[str, str | bytes]

CODER = "agents/coder.yaml"


def _set(theatre: Path, path: str, value: str, *flags: str) -> CliResult:
    return run_cli("config", "set", path, value, *flags, "--theatre", str(theatre))


def _get(theatre: Path, path: str) -> str:
    result = run_cli("config", "get", path, "--theatre", str(theatre))
    assert (result.code, result.err) == (0, ""), result.err
    return result.out


def _bytes(files: Files) -> dict[str, bytes]:
    return {
        f".troupe/{rel}": content.encode("utf-8") if isinstance(content, str) else content
        for rel, content in files.items()
    }


def _check(
    make_theatre: MakeTheatre,
    files: Files,
    path: str,
    value: str,
    expected: Files,
    shown: dict[str, str],
) -> Path:
    """Build ``files``, run ``set``, assert every file's bytes and ``get`` of each leaf.

    ``expected`` lists only the files that change; every other file must be byte-identical.
    """
    theatre = make_theatre(files)
    result = _set(theatre, path, value)
    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes({**files, **expected})
    for leaf, printed in shown.items():
        assert _get(theatre, leaf) == printed
    return theatre


def _own_events(theatre: Path, before: int) -> list[dict[str, Any]]:
    return history_events(theatre)[before:]


# --- US2: a new key under an include becomes an override (FR-005 to FR-007) ---------------------


def test_contract_example_converts_include_and_keeps_comment(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder: file:agents/coder.yaml  # c\n",
        CODER: "model: gpt\n",
    }
    theatre = make_theatre(files)
    imported = len(history_events(theatre))

    result = _set(theatre, "coder.temperature", "0.3")

    assert (result.code, result.out, result.err) == (0, "", "")
    assert snapshot(theatre) == _bytes(
        {
            "troupe.yml": "coder:  # c\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
            CODER: "model: gpt\n",
        }
    )
    [event] = _own_events(theatre, imported)
    assert (event["op"], event["path"], event["old"], event["new"]) == (
        "set",
        "coder.temperature",
        None,
        0.3,
    )
    assert _get(theatre, "coder.temperature") == "0.3\n"
    assert _get(theatre, "coder.model") == "gpt\n"


def test_new_key_after_existing_overrides_needs_no_conversion(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
        CODER: "model: gpt\ntemperature: 0.7\n",
    }
    _check(
        make_theatre,
        files,
        "coder.top_p",
        "0.9",
        {
            "troupe.yml": (
                "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n  top_p: 0.9\n"
            )
        },
        {"coder.top_p": "0.9\n", "coder.temperature": "0.3\n", "coder.model": "gpt\n"},
    )


def test_new_nested_key_creates_override_mapping_and_keeps_included_siblings(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder: file:agents/coder.yaml\n",
        CODER: "model: gpt\nlimits: {max: 5}\n",
    }
    _check(
        make_theatre,
        files,
        "coder.limits.min",
        "1",
        {"troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  limits:\n    min: 1\n"},
        {"coder.limits.min": "1\n", "coder.limits.max": "5\n", "coder.model": "gpt\n"},
    )


def test_new_nested_key_under_mapping_form_with_overrides_extends_the_holder(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {
        "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
        CODER: "limits:\n  max: 5\n",
    }
    _check(
        make_theatre,
        files,
        "coder.limits.min",
        "1",
        {
            "troupe.yml": (
                "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
                "  limits:\n    min: 1\n"
            )
        },
        {"coder.limits.min": "1\n", "coder.limits.max": "5\n"},
    )


def test_new_key_in_root_file_mapping_unchanged_from_step1(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "a:\n  b: 1\ncoder: file:agents/coder.yaml\n",
        CODER: "model: gpt\n",
    }
    _check(
        make_theatre,
        files,
        "a.c",
        "2",
        {"troupe.yml": "a:\n  b: 1\n  c: 2\ncoder: file:agents/coder.yaml\n"},
        {"a.c": "2\n"},
    )


# --- US3: existing values and lists change where they live (FR-008, FR-009, FR-012) ------------

MAPPING_FORM: Files = {
    "troupe.yml": "coder: {$ref: file:agents/coder.yaml, temperature: 0.3}\n",
    CODER: "model: gpt\ntemperature: 0.7\n",
}


def test_overridden_value_changes_only_the_override(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        MAPPING_FORM,
        "coder.temperature",
        "0.5",
        {"troupe.yml": "coder: {$ref: file:agents/coder.yaml, temperature: 0.5}\n"},
        {"coder.temperature": "0.5\n"},
    )


def test_not_overridden_value_changes_the_included_file(make_theatre: MakeTheatre) -> None:
    _check(
        make_theatre,
        MAPPING_FORM,
        "coder.model",
        "claude",
        {CODER: "model: claude\ntemperature: 0.7\n"},
        {"coder.model": "claude\n", "coder.temperature": "0.3\n"},
    )


def test_append_to_included_list_goes_to_included_file(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder: {$ref: file:agents/coder.yaml, temperature: 0.3}\n",
        CODER: "stop: [a, b]\n",
    }
    _check(
        make_theatre,
        files,
        "coder.stop.2",
        "c",
        {CODER: "stop: [a, b, c]\n"},
        {"coder.stop.2": "c\n"},
    )


def test_new_key_inside_included_list_item_goes_to_included_file(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {"troupe.yml": "coder: file:agents/coder.yaml\n", CODER: "steps: [{name: x}]\n"}
    _check(
        make_theatre,
        files,
        "coder.steps.0.retry",
        "2",
        {CODER: "steps: [{name: x, retry: 2}]\n"},
        {"coder.steps.0.retry": "2\n", "coder.steps.0.name": "x\n"},
    )


def test_append_to_override_list_goes_to_including_file(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder: {$ref: file:agents/coder.yaml, stop: [c]}\n",
        CODER: "stop: [a, b]\n",
    }
    _check(
        make_theatre,
        files,
        "coder.stop.1",
        "d",
        {"troupe.yml": "coder: {$ref: file:agents/coder.yaml, stop: [c, d]}\n"},
        {"coder.stop.0": "c\n", "coder.stop.1": "d\n"},
    )


@pytest.mark.parametrize(
    "including",
    [
        "coder: file:agents/coder.yaml\n",
        "coder:\n  $ref: file:agents/coder.yaml\n",
        "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
    ],
    ids=["scalar-form", "mapping-form", "mapping-form-with-override"],
)
@pytest.mark.parametrize(
    ("path", "value"), [("coder", "{a: 1}"), ("coder.$ref", "x")], ids=["whole", "ref"]
)
def test_replacing_whole_include_in_either_form_exits_3_and_changes_nothing(
    make_theatre: MakeTheatre, including: str, path: str, value: str
) -> None:
    theatre = make_theatre({"troupe.yml": including, CODER: "model: gpt\n"})
    imported = len(history_events(theatre))
    before = snapshot(theatre)

    result = _set(theatre, path, value)

    assert (result.code, result.out) == (3, "")
    assert result.err.startswith("troupe: ") and result.err.count("\n") == 1
    assert snapshot(theatre) == before
    assert _own_events(theatre, imported) == []


def test_set_same_value_into_new_override_path_is_not_a_noop_but_existing_override_value_is(
    make_theatre: MakeTheatre,
) -> None:
    files: Files = {"troupe.yml": "coder: file:agents/coder.yaml\n", CODER: "model: gpt\n"}
    theatre = make_theatre(files)
    imported = len(history_events(theatre))

    first = _set(theatre, "coder.temperature", "0.3")  # a new override: written and recorded
    assert (first.code, first.out, first.err) == (0, "", "")
    written = snapshot(theatre)
    assert written != _bytes(files)
    assert len(_own_events(theatre, imported)) == 1

    again = _set(theatre, "coder.temperature", "0.3")  # the override now holds it: a no-op
    assert (again.code, again.out, again.err) == (0, "", "")
    assert snapshot(theatre) == written
    assert len(_own_events(theatre, imported)) == 1


# --- Spec C2/C3: an include with an anchor or tag is not converted (the file does not load) ---


@pytest.mark.parametrize(
    ("prop", "message"),
    [
        ("&a ", "anchor &a at line 1 is on an include reference"),
        ("!t ", "tags are not supported at line 1"),
    ],
    ids=["anchor", "tag"],
)
def test_include_with_anchor_or_tag_is_not_converted(
    make_theatre: MakeTheatre, prop: str, message: str
) -> None:
    # Through the CLI the loader rejects an anchored include (C3) and any tag (C2) with exit 4,
    # so no file can change.
    files: Files = {"troupe.yml": f"coder: {prop}file:agents/coder.yaml\n", CODER: "model: gpt\n"}
    theatre = make_theatre(files)

    result = _set(theatre, "coder.temperature", "0.3")

    assert (result.code, result.out) == (4, "")
    assert message in result.err
    assert snapshot(theatre) == _bytes(files)


LAYOUTS = {
    "key-line": ("coder: file:agents/coder.yaml  # c\n", "coder.t"),
    "next-line": ("coder:  # c\n  file:agents/coder.yaml\n", "coder.t"),
    "list-item": ("list:\n  - file:agents/coder.yaml\n", "list.0.t"),
    "flow-mapping": ("agents: {coder: file:agents/coder.yaml}\n", "agents.coder.t"),
    "flow-list": ("list: [1, file:agents/coder.yaml]\n", "list.1.t"),
    "document": ("# c\nfile:agents/coder.yaml\n", "t"),
}


@pytest.mark.parametrize("prop", ["&a ", "!t "], ids=["anchor", "tag"])
@pytest.mark.parametrize(("text", "dotted"), LAYOUTS.values(), ids=LAYOUTS.keys())
def test_converter_refuses_an_anchor_or_tag_before_the_include(
    tmp_path: Path, prop: str, text: str, dotted: str
) -> None:
    # The converter refuses on its own (exit 3, naming PATH and the file), whatever the caller:
    # the spans of a clean include are applied to the same text with the property inserted.
    config = _theatre_files(tmp_path, {"troupe.yml": text, CODER: "model: gpt\n"})
    segments = parse_path(dotted)
    placement = place(load(config), segments, dotted)
    assert isinstance(placement, ConvertInclude)
    clean = placement.include.origin
    source = clean.file
    source.text = text[: clean.start] + prop + text[clean.start :]
    include = Origin(source, clean.start + len(prop), clean.end + len(prop))

    with pytest.raises(WriteRefused) as refused:
        convert_include_edits(
            source, placement.parent, placement.slot, include, placement.keys, 1, 2, path=dotted
        )
    assert refused.value.message.startswith(f"{dotted}: ")
    assert str(source.path) in refused.value.message
    assert "anchor or tag" in refused.value.message


@pytest.mark.parametrize(("text", "dotted"), LAYOUTS.values(), ids=LAYOUTS.keys())
def test_converter_accepts_the_same_layouts_without_anchor_or_tag(
    tmp_path: Path, text: str, dotted: str
) -> None:
    config = _theatre_files(tmp_path, {"troupe.yml": text, CODER: "model: gpt\n"})
    placement = place(load(config), parse_path(dotted), dotted)
    assert isinstance(placement, ConvertInclude)
    origin = placement.include.origin
    edits = convert_include_edits(
        origin.file, placement.parent, placement.slot, origin, placement.keys, 1, 2, path=dotted
    )
    assert edits


# --- Verification allowance (research R-5): narrow, on the route, same target only ------------


def _theatre_files(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return tmp_path / "troupe.yml"


def _plan_with_rendering(
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    dotted: str,
    value: str,
    new_text: str,
    *,
    written: Path | None = None,
    in_include: bool = False,
) -> WritePlan:
    """Run ``apply_set`` with the new text of ``written`` (default: the root file) forced."""
    root = load(config)
    file = root.origin.file
    if written is not None and written.resolve() != file.path:
        file = next(n.target for n in _includes(root) if n.target.path == written.resolve())

    def crafted(
        placement: Placement, path: str, parsed: Value
    ) -> tuple[SourceFile, list[TextEdit]]:
        return file, [TextEdit(0, len(file.text), new_text)]

    monkeypatch.setattr(apply, "_edits", crafted)
    return apply_set(
        root, parse_path(dotted), dotted, parse_value(value), value, in_include=in_include
    )


def _includes(node: Node) -> list[YamlInclude]:
    """Every YAML include reachable from ``node``, concretely (both sides of merged views)."""
    found: list[YamlInclude] = []
    if isinstance(node, YamlInclude):
        found.append(node)
        found.extend(_includes(node.root))
    elif isinstance(node, MergedMapping):
        found.extend(_includes(node.base))
        found.extend(_includes(node.override))
    elif isinstance(node, MappingNode):
        for entry in node.entries:
            found.extend(_includes(entry.value))
    elif isinstance(node, SequenceNode):
        for item in node.items:
            found.extend(_includes(item))
    return found


VERIFIER_FILES = {
    "troupe.yml": "coder: file:agents/coder.yaml\nreviewer: file:agents/reviewer.yaml\n",
    "agents/coder.yaml": "model: gpt\n",
    "agents/reviewer.yaml": "model: gpt\n",
    "agents/other.yaml": "model: gpt\n",
    "empty.yml": "",
}


def test_verifier_accepts_the_conversion_on_the_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _theatre_files(tmp_path, VERIFIER_FILES)
    new_text = (
        "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
        "reviewer: file:agents/reviewer.yaml\n"
    )
    plan = _plan_with_rendering(monkeypatch, config, "coder.temperature", "0.3", new_text)
    assert [(file.path, text) for file, text in plan.files.items()] == [
        (config.resolve(), new_text)
    ]


@pytest.mark.parametrize(
    "new_text",
    [
        # on the route, but the include now names another file with the same content
        "coder:\n  $ref: file:agents/other.yaml\n  temperature: 0.3\n"
        "reviewer: file:agents/reviewer.yaml\n",
        # off the route: another include converted to mapping form without overrides
        "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
        "reviewer: {$ref: file:agents/reviewer.yaml}\n",
        # off the route: an include given an override equal to its value (same target)
        "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
        "reviewer: {$ref: file:agents/reviewer.yaml, model: gpt}\n",
        # off the route: an include replaced by a merged view of an empty file with its content
        "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
        "reviewer: {$ref: file:empty.yml, model: gpt}\n",
    ],
    ids=[
        "other-target-on-route",
        "off-route-form-change",
        "off-route-same-target-override",
        "off-route-other-target",
    ],
)
def test_verifier_refuses_any_other_structural_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, new_text: str
) -> None:
    config = _theatre_files(tmp_path, VERIFIER_FILES)
    with pytest.raises(WriteRefused):
        _plan_with_rendering(monkeypatch, config, "coder.temperature", "0.3", new_text)


def test_verifier_refuses_a_plain_mapping_turned_merged_view_off_the_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _theatre_files(
        tmp_path,
        {
            "troupe.yml": "coder: file:agents/coder.yaml\nlocal:\n  model: gpt\n",
            "agents/coder.yaml": "model: gpt\n",
            "empty.yml": "",
        },
    )
    with pytest.raises(WriteRefused):
        _plan_with_rendering(
            monkeypatch,
            config,
            "coder.temperature",
            "0.3",
            "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n"
            "local:\n  $ref: file:empty.yml\n  model: gpt\n",
        )


def test_verifier_refuses_an_included_mapping_turned_merged_view_off_the_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The new override ``limits.max`` repeats the included value, so only the route rule
    # tells this apart from the allowed change.
    config = _theatre_files(
        tmp_path,
        {
            "troupe.yml": "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.3\n",
            "agents/coder.yaml": "limits:\n  max: 5\n",
        },
    )
    with pytest.raises(WriteRefused):
        _plan_with_rendering(
            monkeypatch,
            config,
            "coder.temperature",
            "0.5",
            "coder:\n  $ref: file:agents/coder.yaml\n  temperature: 0.5\n  limits:\n    max: 5\n",
        )


IN_INCLUDE_FILES = {
    "troupe.yml": "coder: {$ref: file:agents/coder.yaml, top_p: 0.8}\n",
    "agents/coder.yaml": "model: gpt\ntemperature: 0.7\n",
}


def test_verifier_accepts_a_new_base_key_before_the_override_only_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = _theatre_files(tmp_path, IN_INCLUDE_FILES)
    new_text = "model: gpt\ntemperature: 0.7\nmax_tokens: 100\n"
    plan = _plan_with_rendering(
        monkeypatch,
        config,
        "coder.max_tokens",
        "100",
        new_text,
        written=tmp_path / CODER,
        in_include=True,
    )
    assert list(plan.files.values()) == [new_text]


@pytest.mark.parametrize(
    ("written", "new_text"),
    [
        # in the included file, but not at the end of its keys
        (CODER, "model: gpt\nmax_tokens: 100\ntemperature: 0.7\n"),
        (CODER, "max_tokens: 100\nmodel: gpt\ntemperature: 0.7\n"),
        # in the override, but before the existing override-only key
        ("troupe.yml", "coder: {$ref: file:agents/coder.yaml, max_tokens: 100, top_p: 0.8}\n"),
    ],
    ids=["base-middle", "base-first", "override-before-top_p"],
)
def test_verifier_refuses_a_new_key_at_any_other_position_in_a_merged_view(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, written: str, new_text: str
) -> None:
    config = _theatre_files(tmp_path, IN_INCLUDE_FILES)
    with pytest.raises(WriteRefused):
        _plan_with_rendering(
            monkeypatch,
            config,
            "coder.max_tokens",
            "100",
            new_text,
            written=tmp_path / written,
            in_include=True,
        )
