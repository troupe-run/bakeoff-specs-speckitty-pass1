"""``placement.place`` on trees the real loader builds from real files (contract *Overrides*,
*In-include*; spec D-4, D-6, D-8, D-10; research R-3, R-4).

Each test writes a theatre, loads it with ``troupe.loader.load`` and checks the placement: its
type, the file its target node lives in, its slot and its keys. ``_place`` also checks, for every
placement in this module, that it carries only concrete collections (never a ``MergedMapping``).
"""

import dataclasses
from pathlib import Path

import pytest

from conftest import MakeTheatre
from troupe.errors import WriteRefused
from troupe.loader import load
from troupe.paths import parse_path
from troupe.tree import MergedMapping, Node, SequenceNode
from troupe.writeback.placement import (
    AddKeys,
    AppendItem,
    ConvertInclude,
    Placement,
    ReplaceCollection,
    ReplaceScalar,
    place,
)

type Files = dict[str, str | bytes]

CODER = "model: gpt\ntemperature: 0.7\n"
SCALAR_FORM = "coder: file:agents/coder.yaml  # c\n"
REF_ONLY = "coder:\n  $ref: file:agents/coder.yaml\n"
MERGED = REF_ONLY + "  temperature: 0.3\n"
# US2-5: troupe.yml -> agents/coder.yaml -> agents/models/base.yaml.
NESTED: Files = {
    "troupe.yml": "coder: file:agents/coder.yaml\n",
    "agents/coder.yaml": "model: file:models/base.yaml\n",
    "agents/models/base.yaml": "name: gpt\n",
}


def _load(make_theatre: MakeTheatre, files: Files) -> Node:
    theatre = make_theatre(files)
    return load(theatre / ".troupe" / "troupe.yml")


def _place(
    make_theatre: MakeTheatre, files: Files, path: str, *, in_include: bool = False
) -> Placement:
    """Load ``files`` and place ``set path``; assert the placement holds concrete nodes only."""
    root = _load(make_theatre, files)
    placement = place(root, parse_path(path), path, in_include=in_include)
    _assert_concrete(placement)
    return placement


def _assert_concrete(placement: Placement) -> None:
    """Every collection a placement carries is concrete: writers never write through a view."""
    for field in dataclasses.fields(placement):
        value = getattr(placement, field.name)
        assert not isinstance(value, MergedMapping), f"{field.name} is a merged view"


def _file(node: Node | None) -> str:
    """The theatre-relative file a node's bytes live in."""
    assert node is not None
    path = node.origin.file.path
    return path.relative_to(_state_dir(path)).as_posix()


def _state_dir(path: Path) -> Path:
    return next(parent for parent in path.parents if parent.name == ".troupe")


def _refusal(make_theatre: MakeTheatre, files: Files, path: str) -> str:
    root = _load(make_theatre, files)
    with pytest.raises(WriteRefused) as caught:
        place(root, parse_path(path), path)
    assert caught.value.exit_code == 3
    assert path in caught.value.message
    return caught.value.message


# --- New keys: Overrides ------------------------------------------------------------------------


def test_new_key_under_scalar_form_include_converts_it(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": SCALAR_FORM, "agents/coder.yaml": CODER})
    placement = place(root, ["coder", "top_p"], "coder.top_p")
    _assert_concrete(placement)

    assert isinstance(placement, ConvertInclude)
    assert placement.parent is root
    assert placement.slot == "coder"
    assert _file(placement.include) == "troupe.yml"
    assert _file(placement.include.root) == "agents/coder.yaml"
    assert placement.keys == ["top_p"]


def test_new_key_under_ref_only_include_adds_to_holder(make_theatre: MakeTheatre) -> None:
    placement = _place(
        make_theatre, {"troupe.yml": REF_ONLY, "agents/coder.yaml": CODER}, "coder.top_p"
    )

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == "troupe.yml"
    assert [entry.key for entry in placement.mapping.entries] == ["$ref"]
    assert placement.keys == ["top_p"]


def test_new_key_under_merged_include_adds_to_holder_after_existing_overrides(
    make_theatre: MakeTheatre,
) -> None:
    placement = _place(
        make_theatre, {"troupe.yml": MERGED, "agents/coder.yaml": CODER}, "coder.top_p"
    )

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == "troupe.yml"
    assert [entry.key for entry in placement.mapping.entries] == ["$ref", "temperature"]
    assert placement.keys == ["top_p"]


@pytest.mark.parametrize(
    ("troupe", "coder", "path", "override_keys", "keys"),
    [
        # US2-4: no ``limits`` override yet: created inside the holder.
        (
            MERGED,
            "limits: {max: 5}\n",
            "coder.limits.min",
            ["$ref", "temperature"],
            ["limits", "min"],
        ),
        # An existing override mapping that also defines ``limits`` gets the key (D-8).
        (
            MERGED + "  limits:\n    floor: 0\n",
            "limits: {max: 5}\n",
            "coder.limits.min",
            ["floor"],
            ["min"],
        ),
        # Deeper: ``limits.inner`` only in the include; the ``limits`` override is extended.
        (
            MERGED + "  limits:\n    floor: 0\n",
            "limits:\n  inner:\n    max: 5\n",
            "coder.limits.inner.min",
            ["floor"],
            ["inner", "min"],
        ),
    ],
    ids=["override-absent", "override-present", "override-present-deeper"],
)
def test_new_nested_key_extends_existing_override_mapping(
    make_theatre: MakeTheatre,
    troupe: str,
    coder: str,
    path: str,
    override_keys: list[str],
    keys: list[str],
) -> None:
    placement = _place(make_theatre, {"troupe.yml": troupe, "agents/coder.yaml": coder}, path)

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == "troupe.yml"
    assert [entry.key for entry in placement.mapping.entries] == override_keys
    assert placement.keys == keys


def test_new_nested_key_under_scalar_form_include_converts_it_with_the_route(
    make_theatre: MakeTheatre,
) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": SCALAR_FORM, "agents/coder.yaml": "limits: {max: 5}\n"},
        "coder.limits.min",
    )

    assert isinstance(placement, ConvertInclude)
    assert placement.slot == "coder"
    assert placement.keys == ["limits", "min"]


def test_nested_include_override_goes_to_nearest_including_file(
    make_theatre: MakeTheatre,
) -> None:
    placement = _place(make_theatre, NESTED, "coder.model.temperature")

    assert isinstance(placement, ConvertInclude)
    assert _file(placement.include) == "agents/coder.yaml"
    assert _file(placement.include.root) == "agents/models/base.yaml"
    assert _file(placement.parent) == "agents/coder.yaml"
    assert placement.slot == "model"
    assert placement.keys == ["temperature"]


def test_new_key_in_root_file_mapping_is_step1(make_theatre: MakeTheatre) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": "model:\n  name: gpt\n" + SCALAR_FORM, "agents/coder.yaml": CODER},
        "model.limits.max",
    )

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == "troupe.yml"
    assert [entry.key for entry in placement.mapping.entries] == ["name"]
    assert placement.keys == ["limits", "max"]


def test_new_key_inside_list_item_of_included_file_stays_in_that_file(
    make_theatre: MakeTheatre,
) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": SCALAR_FORM, "agents/coder.yaml": "steps:\n  - name: x\n"},
        "coder.steps.0.retry",
    )

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == "agents/coder.yaml"
    assert [entry.key for entry in placement.mapping.entries] == ["name"]
    assert placement.keys == ["retry"]


def test_new_key_under_list_item_include_converts_the_item(make_theatre: MakeTheatre) -> None:
    placement = _place(
        make_theatre, {"troupe.yml": "list:\n  - file:a.yaml\n", "a.yaml": "x: 1\n"}, "list.0.k"
    )

    assert isinstance(placement, ConvertInclude)
    assert isinstance(placement.parent, SequenceNode)
    assert _file(placement.parent) == "troupe.yml"
    assert placement.slot == 0
    assert _file(placement.include.root) == "a.yaml"
    assert placement.keys == ["k"]


def test_new_key_under_merged_mapping_with_include_override_converts_that_include(
    make_theatre: MakeTheatre,
) -> None:
    placement = _place(
        make_theatre,
        {
            "troupe.yml": REF_ONLY + "  model: file:model.yaml\n",
            "agents/coder.yaml": "model:\n  name: gpt\n",
            "model.yaml": "size: big\n",
        },
        "coder.model.temperature",
    )

    assert isinstance(placement, ConvertInclude)
    assert _file(placement.include.root) == "model.yaml"
    assert _file(placement.parent) == "troupe.yml"
    assert placement.slot == "model"
    assert placement.keys == ["temperature"]


# --- New keys: In-include -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("files", "path", "target", "existing"),
    [
        (
            {"troupe.yml": SCALAR_FORM, "agents/coder.yaml": CODER},
            "coder.top_p",
            "agents/coder.yaml",
            ["model", "temperature"],
        ),
        (
            {"troupe.yml": REF_ONLY, "agents/coder.yaml": CODER},
            "coder.top_p",
            "agents/coder.yaml",
            ["model", "temperature"],
        ),
        (
            {"troupe.yml": MERGED, "agents/coder.yaml": CODER},
            "coder.top_p",
            "agents/coder.yaml",
            ["model", "temperature"],
        ),
        (
            {
                "troupe.yml": MERGED + "  limits:\n    floor: 0\n",
                "agents/coder.yaml": "limits: {max: 5}\n",
            },
            "coder.limits.min",
            "agents/coder.yaml",
            ["max"],
        ),
        (NESTED, "coder.model.temperature", "agents/models/base.yaml", ["name"]),
    ],
    ids=["scalar-form", "ref-only", "merged", "merged-nested-mapping", "nested-includes"],
)
def test_in_include_new_key_goes_to_innermost_included_file(
    make_theatre: MakeTheatre, files: Files, path: str, target: str, existing: list[str]
) -> None:
    placement = _place(make_theatre, files, path, in_include=True)

    assert isinstance(placement, AddKeys)
    assert _file(placement.mapping) == target
    assert [entry.key for entry in placement.mapping.entries] == existing
    assert placement.keys == [path.rsplit(".", 1)[1]]


def test_in_include_without_include_equals_step1(make_theatre: MakeTheatre) -> None:
    root = _load(make_theatre, {"troupe.yml": "model:\n  name: gpt\n"})

    plain = place(root, ["model", "limits", "max"], "model.limits.max")
    flagged = place(root, ["model", "limits", "max"], "model.limits.max", in_include=True)

    assert isinstance(plain, AddKeys) and isinstance(flagged, AddKeys)
    assert flagged.mapping is plain.mapping
    assert flagged.keys == plain.keys == ["limits", "max"]


# --- Existing values and lists ------------------------------------------------------------------


@pytest.mark.parametrize("in_include", [False, True])
def test_existing_overridden_scalar_replaced_in_override_file(
    make_theatre: MakeTheatre, in_include: bool
) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": MERGED, "agents/coder.yaml": CODER},
        "coder.temperature",
        in_include=in_include,
    )

    assert isinstance(placement, ReplaceScalar)
    assert _file(placement.parent) == "troupe.yml"
    assert placement.slot == "temperature"
    assert placement.node.value == 0.3
    assert _file(placement.node) == "troupe.yml"


@pytest.mark.parametrize("in_include", [False, True])
def test_existing_scalar_not_overridden_in_included_file(
    make_theatre: MakeTheatre, in_include: bool
) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": MERGED, "agents/coder.yaml": CODER},
        "coder.model",
        in_include=in_include,
    )

    assert isinstance(placement, ReplaceScalar)
    assert _file(placement.parent) == "agents/coder.yaml"
    assert placement.slot == "model"
    assert placement.node.value == "gpt"


def test_existing_scalar_context_comes_from_its_concrete_parent(make_theatre: MakeTheatre) -> None:
    files: Files = {
        "troupe.yml": "coder: {$ref: file:agents/coder.yaml, temperature: 0.3}\n",
        "agents/coder.yaml": CODER,
    }
    overridden = _place(make_theatre, files, "coder.temperature")
    included = _place(make_theatre, files, "coder.model")

    assert isinstance(overridden, ReplaceScalar) and isinstance(included, ReplaceScalar)
    assert overridden.context == "flow"
    assert included.context == "block"


def test_replacing_one_sided_mapping_targets_its_file(make_theatre: MakeTheatre) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": MERGED, "agents/coder.yaml": "tools:\n  shell: true\n"},
        "coder.tools",
    )

    assert isinstance(placement, ReplaceCollection)
    assert _file(placement.parent) == "agents/coder.yaml"
    assert _file(placement.node) == "agents/coder.yaml"
    assert placement.slot == "tools"


@pytest.mark.parametrize("in_include", [False, True])
def test_append_to_included_list_targets_included_file(
    make_theatre: MakeTheatre, in_include: bool
) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": MERGED, "agents/coder.yaml": "stop: [a, b]\n"},
        "coder.stop.2",
        in_include=in_include,
    )

    assert isinstance(placement, AppendItem)
    assert _file(placement.sequence) == "agents/coder.yaml"


def test_append_to_override_list_targets_override_file(make_theatre: MakeTheatre) -> None:
    placement = _place(
        make_theatre,
        {"troupe.yml": MERGED + "  stop: [c]\n", "agents/coder.yaml": "stop: [a, b]\n"},
        "coder.stop.1",
    )

    assert isinstance(placement, AppendItem)
    assert _file(placement.sequence) == "troupe.yml"


# --- Refusals -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["coder.$ref", "coder.$ref.x", "$ref"])
def test_ref_segment_is_refused(make_theatre: MakeTheatre, path: str) -> None:
    message = _refusal(make_theatre, {"troupe.yml": REF_ONLY, "agents/coder.yaml": CODER}, path)

    assert "'$ref' is not a setting" in message


@pytest.mark.parametrize(
    "troupe", [SCALAR_FORM, REF_ONLY, MERGED], ids=["scalar", "ref-only", "merged"]
)
def test_replacing_whole_include_is_refused_in_both_forms(
    make_theatre: MakeTheatre, troupe: str
) -> None:
    message = _refusal(make_theatre, {"troupe.yml": troupe, "agents/coder.yaml": CODER}, "coder")

    assert "agents/coder.yaml" in message
    assert "no file changed" in message


def test_replacing_partly_overridden_mapping_is_refused(make_theatre: MakeTheatre) -> None:
    message = _refusal(
        make_theatre,
        {
            "troupe.yml": MERGED + "  tools:\n    x: 1\n",
            "agents/coder.yaml": "tools:\n  shell: true\n",
        },
        "coder.tools",
    )

    assert "agents/coder.yaml" in message
    assert "troupe.yml" in message
    assert "no file changed" in message
