---
work_package_id: WP07
title: Rendering !literal
dependencies:
- WP04
- WP05
requirement_refs:
- FR-011
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T030
- T031
- T032
- T033
phase: Phase 3 - Writing
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/scalars.py
create_intent:
- tests/unit/test_literal_rendering.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/scalars.py
- src/troupe/writeback/blocks.py
- src/troupe/writeback/collections.py
- src/troupe/writeback/aliases.py
- tests/unit/test_literal_rendering.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP07 – Rendering `!literal`

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Every place that renders a **new** string value writes `!literal ` in front of an `includes.LiteralStr` (spec S-11, S-13; research R-8). There are two choke points:
- `scalars.render_scalar` for single-line values;
- `blocks.render_new_multiline` for multi-line values, in block and flow form.

Two more places learn about tags written in files:
- the **alias expansion copy** (`writeback/aliases.py`) must keep `!literal` on copied scalars, or a copy of `!literal https://x` would turn into a remote include;
- **kind-changing replacement** (`collections.replace_value_edits`) must drop the tag when a tagged scalar is replaced by a mapping or list, or the result would be `!literal` on a collection (exit 4).

**Not in this WP**: replacing an existing scalar with a scalar. WP08 does that in `apply.py` with a separate tag edit: keep, insert or remove the tag at the node's `literal` span or content start. In those paths the renderers only ever get a plain `str`.

## Context

- Spec: S-10, S-11, S-13; FR-011.
- Research: R-4 (spans start at content; `ScalarNode.literal` is the tag span), R-8.
- From WP04: `includes.LiteralStr`. From WP05: `ScalarNode.literal: Origin | None`.
- Current renderer map:
  - `scalars.render_scalar(v, preferred, context)` calls `render_string(choose_style(...))`. `_round_trips_plain` composes the rendered text in VALUE mode, which refuses tags, so the prefix must be added **after** style choice and round-trip checks.
  - `render_string` is also used for **keys** (`collections.py:424, 653, 675`; `aliases.py:330`). Keys never get a tag, so do **not** put the prefix in `render_string`.
  - New values: `collections._Renderer.attach` (`render_new_multiline` at about 394, `render_scalar` at about 399), `collections.render_flow_value` (about 646–647, flow multi-line and single-line), and `aliases._Renderer.scalar` (about 268–281: single-line scalars copy `node.origin.source` verbatim; multi-line ones use `render_new_multiline`).
  - `blocks.render_new_multiline(value, context, content_indent, step)` returns `(header, body)`. In flow context it returns a double-quoted string and no body (about line 190).

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP07 --agent <name>`. It depends on WP04 and WP05, and can run in parallel with WP06.

## Subtasks

### T030 — `render_scalar`

```python
LITERAL_PREFIX: Final = "!literal "   # spec S-11; the one place this text is written

def render_scalar(v: Scalar, preferred: QuoteStyle | None, context: Context) -> str:
    if isinstance(v, str):
        rendered = render_string(v, choose_style(v, preferred, context))
        return LITERAL_PREFIX + rendered if isinstance(v, LiteralStr) else rendered
    return render_nonstring(v)
```

- Import `LiteralStr` from `troupe.includes`. Check for an import cycle (`includes` → `values` → … must not import `writeback`); if there is one, move the import under `TYPE_CHECKING` and test with `type(v).__name__`. Prefer the real import.
- Style choice is unchanged: a `LiteralStr` `https://x` is plain where a `str` would be plain. In flow context `{u: !literal https://x}` is valid YAML; verify with the composer in tests.
- Docstring: when the prefix is written, and that keys and replacements never get it here.

### T031 — `blocks.render_new_multiline`

- Block context: `header` becomes `LITERAL_PREFIX + header` (`!literal |` or `!literal |-` …), and the body is unchanged.
- Flow context, a double-quoted string: return `LITERAL_PREFIX + rendered`.
- Reuse `scalars.LITERAL_PREFIX`; do not repeat the text.
- `replace_with_multiline` and `replace_block` are **not** changed. They are replacement paths, and WP08 hands them plain `str`. Say so in their docstrings ("`LiteralStr` never reaches here; tags of replaced values are WP08's edit").

### T032 — Collections and alias copies

1. **New values in `collections`**: check every path that writes a new value: `_Renderer.attach`/mapping/sequence/item, `render_flow_value`, `_flow_entries`, `flow_append_edits`, `_replace_in_flow`, and the override lines written by `convert_include_edits`. Make sure each one ends in `render_scalar` or `render_new_multiline` for string values. Where a path renders strings some other way, route it through those two functions. List the paths you checked in the Activity Log.
2. **`replace_value_edits`** (kind-changing replacement, scalar → mapping or list): if the replaced node is a `ScalarNode` with `literal is not None`, the edit must also remove the tag span `[literal.start, literal.end)`, so the head becomes `key:` (or `key: &a` when an anchor is kept, step-6 C5). The anchor and the tag may come in either order. Remove exactly the tag token and the blanks that belong to it, without disturbing the anchor or the key line's comment column rules. Existing tests for anchors (C5) must stay green.
3. **Alias copies (`aliases._Renderer.scalar`)**: when copying a `ScalarNode` with `literal` set:
   - single-line: write `LITERAL_PREFIX + node.origin.source`;
   - multi-line: render through `render_new_multiline(LiteralStr(node.value), …)`.

   Copying a literal must produce a literal, or the copy would become an include and change meaning (S-10). Update the copy rules in the module docstring: tags are copied; anchors still are not (C8).

### T033 — Unit tests (`tests/unit/test_literal_rendering.py`)

Render, then read back with `yamlcore.compose(..., allow_anchors=True)` (WP02), and assert the `RawScalar.tag` is present and `text` equals the value:
- `test_render_scalar_prefixes_literal_strings_in_block_and_flow`: `https://x`, `file:p.md`, a string that needs quoting (`file: x` with a space; `'https://a b'`).
- `test_render_scalar_leaves_plain_strings_and_non_strings_untagged`
- `test_render_string_never_prefixes_even_for_literal_str` (keys)
- `test_new_multiline_literal_string_gets_tag_before_block_indicator` (block) and `..._as_double_quoted_in_flow`
- `test_new_key_with_literal_value_is_written_tagged` (via `collections` new-key edits on a real file text)
- `test_flow_append_of_literal_value_is_tagged`
- `test_override_line_from_include_conversion_is_tagged` (`convert_include_edits` with a `LiteralStr` value)
- `test_replacing_tagged_scalar_by_mapping_removes_only_the_tag` (with and without an anchor, both orders)
- `test_alias_copy_keeps_literal_tag_on_copied_scalars` (single-line and multi-line)

Then run the whole suite. Nothing existing may change, because no caller creates `LiteralStr` before WP09.

## Definition of Done

- The tests pass, the whole suite passes unchanged, and all four gates pass, with output pasted.
- `!literal ` appears as a literal string in exactly one place (`scalars.LITERAL_PREFIX`).

## Risks

- **Prefix inside `render_string`** would tag keys. Mitigation: a test (T033).
- **Tag removal in a head with an anchor and a comment.** Mitigation: tests for both orders, plus the existing C5 tests.

## Reviewer guidance

- Only new-value renderers and alias copies add tags; only kind-changing replacement removes them.
- A rendered output always composes back to the intended value and tag.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
