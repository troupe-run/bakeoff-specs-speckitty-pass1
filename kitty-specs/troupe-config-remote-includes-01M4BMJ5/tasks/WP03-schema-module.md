---
work_package_id: WP03
title: Schema module and the jsonschema dependency
dependencies: []
requirement_refs:
- FR-007
- FR-009
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T010
- T011
- T012
- T013
- T014
phase: Phase 1 - Foundations
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/schema.py
create_intent:
- src/troupe/schema.py
- tests/unit/test_schema.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/schema.py
- pyproject.toml
- uv.lock
- tests/unit/test_schema.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP03 – Schema module and the `jsonschema` dependency

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

`src/troupe/schema.py` is the one place that knows about the configuration's JSON Schema (TROUPE-007, research R-6):

- **`load_schema(state_dir: Path) -> Schema | None`** reads and checks `<state_dir>/troupe.schema.json` (S-8).
- **`Schema.uri_at(steps) -> bool`**: does the schema mark this configuration path `"format": "uri"`, found only through `properties`, `additionalProperties` and `items` (S-7)?
- **`Schema.validate(data) -> Violation | None`** validates plain JSON data against the schema: 2020-12, `format` not asserted, first violation in path order (S-8).

The module works on **plain data** (dicts, lists, scalars) and **path steps**. It does not know the tree, files or the loader. WP06 converts the tree to data and turns a `Violation` into an error.

The dependency is `jsonschema>=4.26,<5` (DM 01M4BMXJXSNEY2QMXYA1W16W04: the product owner asked for the safest assumption).

## Context

- Spec: S-7, S-8; FR-007, FR-009.
- Research: **R-6**, plus the supply-chain review and adversarial pass (A-4, A-5) in research.md.
- Contract messages (`contracts/cli.md`): `cannot load schema <schema file>: <reason>`. Violations are rendered by WP06 and WP08 from `Violation.path` and `Violation.message`.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP03 --agent <name>`. This WP has no dependencies.

## Subtasks

### T010 — Dependency

1. In `pyproject.toml`, `[project] dependencies`, add `"jsonschema>=4.26,<5"`. Add:

   ```toml
   [tool.uv]
   no-build-package = ["rpds-py"]
   ```

   with a comment: rpds-py is a compiled Rust extension; only prebuilt wheels are acceptable, never a source build (research supply-chain review, A-5).
2. Run `uv lock` and then `uv sync`. Check that `uv.lock` has wheels for `rpds-py` for cp312 on manylinux x86_64/aarch64 and macOS. Paste the locked versions of `jsonschema`, `referencing`, `jsonschema-specifications`, `rpds-py` and `attrs` into the Activity Log.
3. mypy: `jsonschema` ships no inline types in some versions. If `mypy --strict` complains, add `types-jsonschema` to the **dev** group (and record it in the Activity Log) rather than using `ignore_missing_imports`. If types are present, add nothing.
4. Do **not** add any other dependency.

### T011 — `load_schema`

```python
SCHEMA_FILE_NAME: Final = "troupe.schema.json"
DRAFT_2020_12: Final = "https://json-schema.org/draft/2020-12/schema"

@dataclass(frozen=True)
class Schema:
    path: Path                 # absolute, as read
    document: dict[str, Any] | bool   # 2020-12 allows a boolean root schema
    ...

def load_schema(state_dir: Path) -> Schema | None: ...
```

Checks, in order. Every failure is `LoadError(f"cannot load schema {path}: {reason}")`:
1. Absent file → `None`. Use `path.is_file()`; a directory at that name is a failure, `"not a file"`.
2. Read the bytes: `OSError` → `strerror`. Decode as strict UTF-8 → `"not valid UTF-8 at byte N"`.
3. `json.loads(text, parse_constant=_refuse_constant)` → `"not valid JSON: <msg> at line L column C"` (from `JSONDecodeError`). `NaN`/`Infinity`/`-Infinity` → `"not valid JSON: NaN/Infinity are not JSON"`.
4. The root must be an object or a boolean → `"the schema must be a JSON object or boolean"`.
5. If the root is an object with `"$schema"`, it must equal `DRAFT_2020_12` → `"$schema must be https://json-schema.org/draft/2020-12/schema, got <value>"`.
6. `Draft202012Validator.check_schema(document)` → on `SchemaError`, `"not a valid JSON Schema 2020-12: <err.message> at <json pointer of err.path>"`.
7. Walk the whole document. Every `$ref` and `$dynamicRef` **string value** whose key sits in a schema object must start with `#` → `"$ref <value> at <pointer> is not a fragment within this file (references to other documents are not fetched)"`. A plain walk over all dicts is acceptable: a property *named* `$ref` inside `properties` is a key of `properties`, not a `$ref` keyword, so look only at the keys `$ref`/`$dynamicRef` of dicts that are schema objects. A simpler, conservative alternative: refuse any dict key `$ref`/`$dynamicRef` with a string value not starting `#`, except directly inside `properties`, `patternProperties`, `$defs`, `definitions` or `dependentSchemas`, whose keys are names. Document the choice.
8. Build the validator once: `Draft202012Validator(document, registry=Registry())` with **no** `format_checker`, so `format` is an annotation (S-8). An empty `referencing.Registry()` resolves nothing outside the document.

### T012 — `Schema.uri_at`

```python
type Step = tuple[Literal["key"], str] | tuple[Literal["index"], int]

def uri_at(self, steps: Sequence[Step]) -> bool: ...
```

Walk from the root schema:
- if the current schema is not a dict (boolean, missing) → `False`;
- `("key", k)`: `properties[k]` if `properties` is a dict and has `k`; else `additionalProperties` if it is a dict; else `False`;
- `("index", _)`: `items` if it is a dict; else `False`;
- at the end → `current.get("format") == "uri"` and `current` is a dict.

Nothing else is followed (S-7): `$ref`, `allOf`/`anyOf`/`oneOf`, `if`/`then`/`else`, `patternProperties`, `prefixItems`, `dependentSchemas`, `unevaluatedProperties`. Only the exact value `"uri"` counts; `uri-reference` and `iri` do not. Put this list in the docstring with "spec S-7: the contract names exactly properties, items and additionalProperties".

The caller (WP05) knows whether each step is a mapping key or a list index. Never guess from the segment text: a key `"0"` is a key.

### T013 — `Schema.validate`

```python
@dataclass(frozen=True)
class Violation:
    path: str      # dotted configuration path of the failing instance, "(root)" for the root
    message: str   # jsonschema's error.message

def validate(self, data: object) -> Violation | None: ...
```

- `errors = list(self._validator.iter_errors(data))`. If there are none, return `None`.
- **First violation**: sort by `error.absolute_path`. The key is a tuple of `(0, int)` for list indexes and `(1, str)` for keys, so mixed paths compare deterministically. Then take the shortest path, then the smallest `error.validator` name. Document this as "the first failure in path order, made deterministic" (research R-6).
- Path rendering: join `absolute_path` items with `.`; integers as decimal; `(root)` if empty. This matches `loader.dotted`, but do not import the loader: keep a 3-line local helper.
- `referencing.exceptions.Unresolvable` raised during validation → `LoadError(f"cannot load schema {self.path}: cannot resolve {ref}")`. This should be unreachable after T011.7; keep it as a safety net with a test that builds a `Schema` around a document whose reference cannot be resolved.

### T014 — Unit tests (`tests/unit/test_schema.py`)

Write real files to `tmp_path / ".troupe"`:
- `test_absent_schema_file_gives_none`
- `test_schema_that_is_not_utf8_json_or_has_nan_is_refused_naming_the_file` (parametrised)
- `test_schema_with_other_dollar_schema_is_refused` (draft-07 URI)
- `test_schema_failing_the_meta_schema_is_refused` (`{"type": 5}`)
- `test_schema_with_a_remote_ref_is_refused` (`{"$ref": "https://x/y.json"}`); `test_schema_with_a_local_fragment_ref_loads` (`$defs` + `#/$defs/x`)
- `test_property_named_dollar_ref_is_not_a_reference` (`{"properties": {"$ref": {"type": "string"}}}` loads)
- `test_boolean_root_schema_loads_and_true_accepts_everything`
- `uri_at` (parametrised over schema and steps): `properties` hit; `additionalProperties` fallback; `items`; nested `properties.agents.additionalProperties.properties.urls.items`; not followed through `$ref`, `allOf`, `patternProperties` or `prefixItems`; `format: "uri-reference"` → `False`; a key step on `items`-only → `False`; a boolean subschema → `False`.
- `validate`: valid → `None`; a type error at `model` → `Violation("model", "5 is not of type 'string'")`; several errors → the first in path order (`a.b` before `b`; index 0 before 1); a root error → `(root)`; `format: uri` with `"not a uri"` → valid (S-8, format not asserted); `required` missing → path of the containing object.

## Definition of Done

- All four gates pass with output pasted. Locked versions are recorded.
- `schema.py` imports nothing from `troupe` except `troupe.errors`.

## Risks

- **jsonschema typing under mypy strict.** Mitigation: T010 step 3.
- **Error ordering** differs between jsonschema versions. Mitigation: our own sort key (T013); tests use clearly separated paths.

## Reviewer guidance

- No `format_checker`, an empty `Registry`, and the meta-schema check is on.
- `uri_at` follows exactly three keywords.
- Dependency hygiene: the lock has hashes, `no-build-package` is set, and versions are recorded.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
