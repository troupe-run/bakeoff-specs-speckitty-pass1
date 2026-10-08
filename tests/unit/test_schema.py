"""The configuration schema: loading and checking ``troupe.schema.json``, the S-7 ``format: uri``
lookup and 2020-12 validation of plain data (spec S-7, S-8; research R-6).

Every test writes a real schema file under ``tmp_path / ".troupe"`` and loads it through
``load_schema``, so the checks run against the file the user would have written.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from troupe.errors import LoadError
from troupe.schema import SCHEMA_FILE_NAME, Schema, Step, Violation, load_schema


def _state_dir(tmp_path: Path) -> Path:
    state_dir = tmp_path / ".troupe"
    state_dir.mkdir(exist_ok=True)
    return state_dir


def _write_bytes(tmp_path: Path, content: bytes) -> Path:
    path = _state_dir(tmp_path) / SCHEMA_FILE_NAME
    path.write_bytes(content)
    return path


def _load(tmp_path: Path, document: object) -> Schema:
    _write_bytes(tmp_path, json.dumps(document).encode("utf-8"))
    schema = load_schema(_state_dir(tmp_path))
    assert schema is not None
    return schema


def _refusal(tmp_path: Path, content: bytes) -> str:
    path = _write_bytes(tmp_path, content)
    with pytest.raises(LoadError) as caught:
        load_schema(path.parent)
    assert caught.value.message.startswith(f"cannot load schema {path}: ")
    return caught.value.message.removeprefix(f"cannot load schema {path}: ")


# --- load_schema -------------------------------------------------------------------------------


def test_absent_schema_file_gives_none(tmp_path: Path) -> None:
    assert load_schema(_state_dir(tmp_path)) is None


def test_directory_at_the_schema_file_name_is_refused_as_not_a_file(tmp_path: Path) -> None:
    path = _state_dir(tmp_path) / SCHEMA_FILE_NAME
    path.mkdir()
    with pytest.raises(LoadError) as caught:
        load_schema(path.parent)
    assert caught.value.message == f"cannot load schema {path}: not a file"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (b'{"type": "object", "title": "caf\xe9"}', "not valid UTF-8 at byte 32"),
        (b'{"type": ', "not valid JSON: Expecting value at line 1 column 10"),
        (
            b"{\n  'type': 1\n}",
            "not valid JSON: Expecting property name enclosed in double quotes at line 2 column 3",
        ),
        (b'{"maximum": NaN}', "not valid JSON: NaN/Infinity are not JSON"),
        (b'{"maximum": Infinity}', "not valid JSON: NaN/Infinity are not JSON"),
        (b'{"minimum": -Infinity}', "not valid JSON: NaN/Infinity are not JSON"),
    ],
    ids=["not-utf8", "truncated-json", "single-quotes", "nan", "infinity", "minus-infinity"],
)
def test_schema_that_is_not_utf8_json_or_has_nan_is_refused_naming_the_file(
    tmp_path: Path, content: bytes, reason: str
) -> None:
    assert _refusal(tmp_path, content) == reason


@pytest.mark.parametrize("content", [b"[]", b'"x"', b"5", b"null"])
def test_schema_root_that_is_not_an_object_or_boolean_is_refused(
    tmp_path: Path, content: bytes
) -> None:
    assert _refusal(tmp_path, content) == "the schema must be a JSON object or boolean"


def test_schema_with_other_dollar_schema_is_refused(tmp_path: Path) -> None:
    content = b'{"$schema": "http://json-schema.org/draft-07/schema#"}'
    assert _refusal(tmp_path, content) == (
        "$schema must be https://json-schema.org/draft/2020-12/schema, "
        "got http://json-schema.org/draft-07/schema#"
    )


def test_schema_with_the_2020_12_dollar_schema_loads(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"$schema": "https://json-schema.org/draft/2020-12/schema"})
    assert schema.document == {"$schema": "https://json-schema.org/draft/2020-12/schema"}


def test_schema_failing_the_meta_schema_is_refused(tmp_path: Path) -> None:
    reason = _refusal(tmp_path, b'{"properties": {"model": {"type": 5}}}')
    assert reason.startswith("not a valid JSON Schema 2020-12: 5 is not valid under any of")
    assert reason.endswith(" at /properties/model/type")


def test_schema_with_an_invalid_regex_pattern_is_refused(tmp_path: Path) -> None:
    reason = _refusal(tmp_path, b'{"pattern": "("}')
    assert reason == "not a valid JSON Schema 2020-12: '(' is not a 'regex' at /pattern"


def test_schema_with_a_remote_ref_is_refused(tmp_path: Path) -> None:
    assert _refusal(tmp_path, b'{"$ref": "https://x/y.json"}') == (
        "$ref https://x/y.json at /$ref is not a fragment within this file"
        " (references to other documents are not fetched)"
    )


def test_schema_with_a_nested_relative_ref_or_dynamic_ref_is_refused(tmp_path: Path) -> None:
    nested = b'{"properties": {"a": {"items": {"$ref": "other.json#/x"}}}}'
    assert _refusal(tmp_path, nested) == (
        "$ref other.json#/x at /properties/a/items/$ref is not a fragment within this file"
        " (references to other documents are not fetched)"
    )
    dynamic = b'{"$defs": {"a~b/c": {"$dynamicRef": "https://x/y#meta"}}}'
    assert _refusal(tmp_path, dynamic) == (
        "$dynamicRef https://x/y#meta at /$defs/a~0b~1c/$dynamicRef is not a fragment within"
        " this file (references to other documents are not fetched)"
    )


def test_schema_with_a_local_fragment_ref_loads(tmp_path: Path) -> None:
    schema = _load(
        tmp_path,
        {"$defs": {"x": {"type": "string"}}, "properties": {"model": {"$ref": "#/$defs/x"}}},
    )
    assert schema.validate({"model": "opus"}) is None
    assert schema.validate({"model": 5}) == Violation("model", "5 is not of type 'string'")


@pytest.mark.parametrize(
    "keyword", ["properties", "patternProperties", "$defs", "dependentSchemas"]
)
def test_property_named_dollar_ref_is_not_a_reference(tmp_path: Path, keyword: str) -> None:
    schema = _load(tmp_path, {keyword: {"$ref": {"type": "string"}}})
    assert schema.document == {keyword: {"$ref": {"type": "string"}}}


def test_boolean_root_schema_loads_and_true_accepts_everything(tmp_path: Path) -> None:
    accept_all = _load(tmp_path, True)
    assert accept_all.document is True
    for data in ({"model": 5}, [1, "x"], "s", None):
        assert accept_all.validate(data) is None
    reject_all = _load(tmp_path, False)
    assert reject_all.validate({}) == Violation("(root)", "False schema does not allow {}")


def test_schema_path_is_the_file_read(tmp_path: Path) -> None:
    schema = _load(tmp_path, {})
    assert schema.path == _state_dir(tmp_path) / SCHEMA_FILE_NAME


# --- uri_at ------------------------------------------------------------------------------------

URI: dict[str, Any] = {"type": "string", "format": "uri"}


def _key(name: str) -> Step:
    return ("key", name)


def _index(position: int) -> Step:
    return ("index", position)


@pytest.mark.parametrize(
    ("document", "steps", "expected"),
    [
        ({"properties": {"webhook": URI}}, [_key("webhook")], True),
        ({"properties": {"webhook": URI}}, [_key("other")], False),
        ({"additionalProperties": URI}, [_key("anything")], True),
        (
            {"properties": {"a": {"type": "string"}}, "additionalProperties": URI},
            [_key("a")],
            False,
        ),
        ({"properties": {"urls": {"items": URI}}}, [_key("urls"), _index(3)], True),
        (
            {
                "properties": {
                    "agents": {"additionalProperties": {"properties": {"urls": {"items": URI}}}}
                }
            },
            [_key("agents"), _key("coder"), _key("urls"), _index(0)],
            True,
        ),
        ({"$defs": {"u": URI}, "properties": {"w": {"$ref": "#/$defs/u"}}}, [_key("w")], False),
        ({"properties": {"w": {"allOf": [URI]}}}, [_key("w")], False),
        ({"properties": {"w": {"anyOf": [URI]}}}, [_key("w")], False),
        ({"properties": {"w": {"if": True, "then": URI}}}, [_key("w")], False),
        ({"patternProperties": {"^w": URI}}, [_key("w")], False),
        ({"properties": {"l": {"prefixItems": [URI]}}}, [_key("l"), _index(0)], False),
        ({"properties": {"w": {"format": "uri-reference"}}}, [_key("w")], False),
        ({"properties": {"w": {"format": "iri"}}}, [_key("w")], False),
        ({"items": URI}, [_key("0")], False),
        ({"properties": {"0": URI}}, [_index(0)], False),
        ({"properties": {"w": True}}, [_key("w")], False),
        ({"additionalProperties": True}, [_key("w")], False),
        (URI, [], True),
        (True, [], False),
    ],
    ids=[
        "properties-hit",
        "properties-miss-without-additional",
        "additional-properties-fallback",
        "properties-wins-over-additional",
        "items",
        "nested-agents-urls",
        "not-through-ref",
        "not-through-allOf",
        "not-through-anyOf",
        "not-through-if-then",
        "not-through-patternProperties",
        "not-through-prefixItems",
        "uri-reference-is-not-uri",
        "iri-is-not-uri",
        "key-step-on-items-only",
        "index-step-on-properties-only",
        "boolean-subschema",
        "boolean-additional-properties",
        "root-uri",
        "boolean-root",
    ],
)
def test_uri_at_follows_only_properties_additional_properties_and_items(
    tmp_path: Path, document: object, steps: list[Step], expected: bool
) -> None:
    assert _load(tmp_path, document).uri_at(steps) is expected


# --- validate ----------------------------------------------------------------------------------


def test_valid_data_gives_no_violation(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"model": {"type": "string"}}})
    assert schema.validate({"model": "opus", "other": [1, 2]}) is None


def test_type_error_names_the_dotted_path_and_the_validator_message(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"model": {"type": "string"}}})
    assert schema.validate({"model": 5}) == Violation("model", "5 is not of type 'string'")


def test_first_violation_is_the_first_in_path_order(tmp_path: Path) -> None:
    schema = _load(
        tmp_path,
        {
            "properties": {
                "b": {"type": "string"},
                "a": {"properties": {"b": {"type": "string"}}},
            }
        },
    )
    assert schema.validate({"b": 1, "a": {"b": 2}}) == Violation("a.b", "2 is not of type 'string'")


def test_first_violation_orders_list_indexes_numerically(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"items": {"type": "string"}})
    data: list[object] = ["ok"] * 10 + [10, 1]
    data[2] = 2
    assert schema.validate(data) == Violation("2", "2 is not of type 'string'")


def test_first_violation_prefers_the_shorter_path_then_the_validator_name(tmp_path: Path) -> None:
    schema = _load(
        tmp_path,
        {
            "properties": {
                "a": {
                    "required": ["x"],
                    "minProperties": 3,
                    "properties": {"y": {"type": "string"}},
                }
            }
        },
    )
    assert schema.validate({"a": {"y": 1}}) == Violation(
        "a", "{'y': 1} does not have enough properties"
    )


def test_violation_at_the_root_is_reported_as_root(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"type": "object"})
    assert schema.validate(5) == Violation("(root)", "5 is not of type 'object'")


def test_format_uri_is_not_asserted(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"webhook": {"type": "string", "format": "uri"}}})
    assert schema.validate({"webhook": "not a uri"}) is None


def test_missing_required_key_names_the_containing_object(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"agents": {"required": ["coder"]}}})
    assert schema.validate({"agents": {}}) == Violation("agents", "'coder' is a required property")


def test_unresolvable_local_reference_during_validation_is_a_load_error(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"model": {"$ref": "#/$defs/missing"}}})
    assert schema.validate({"other": 1}) is None
    with pytest.raises(LoadError) as caught:
        schema.validate({"model": "opus"})
    assert caught.value.message == (
        f"cannot load schema {schema.path}: cannot resolve #/$defs/missing"
    )


def test_dangling_anchor_reference_during_validation_names_the_anchor(tmp_path: Path) -> None:
    schema = _load(tmp_path, {"properties": {"model": {"$ref": "#foo"}}})
    with pytest.raises(LoadError) as caught:
        schema.validate({"model": "opus"})
    assert caught.value.message == f"cannot load schema {schema.path}: cannot resolve #foo"


def test_dangling_dynamic_anchor_reference_during_validation_names_the_anchor(
    tmp_path: Path,
) -> None:
    schema = _load(tmp_path, {"properties": {"model": {"$dynamicRef": "#nope"}}})
    with pytest.raises(LoadError) as caught:
        schema.validate({"model": "opus"})
    assert caught.value.message == f"cannot load schema {schema.path}: cannot resolve #nope"


def test_unresolvable_remote_reference_in_a_hand_built_schema_is_a_load_error() -> None:
    path = Path("/nowhere/troupe.schema.json")
    schema = Schema(path, {"$ref": "https://x.example/y.json"})
    with pytest.raises(LoadError) as caught:
        schema.validate({})
    assert caught.value.message == (
        f"cannot load schema {path}: cannot resolve https://x.example/y.json"
    )
