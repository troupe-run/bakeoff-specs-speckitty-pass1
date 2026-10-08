---
work_package_id: WP02
title: '!literal in the composer'
dependencies: []
requirement_refs:
- FR-008
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T006
- T007
- T008
- T009
phase: Phase 1 - Foundations
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/yamlcore.py
create_intent: []
execution_mode: code_change
model: ''
owned_files:
- src/troupe/yamlcore.py
- tests/unit/test_yamlcore.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP02 – `!literal` in the composer

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

In file mode (`compose(..., allow_anchors=True)`), `yamlcore` lets one tag through: **`!literal` on a scalar** (spec S-10, research R-4). This WP records where the tag is written and makes the scalar's span start at its content, so writers can keep or drop the tag without knowing YAML tag syntax. Every other tag, and `!literal` on a mapping or sequence, is still refused. VALUE mode (`allow_anchors=False`, used by `values.parse_value`) is unchanged: every tag is still refused with the old message (S-11).

Nothing above `yamlcore` reads the tag yet. The loader starts using it in WP05, so after this WP a file containing `!literal` composes, but the loader treats the scalar like any other. That is fine: no file in the suite has a `!literal` yet.

## Context

- Current composer: `_Composer._node`, which refuses any `event.tag` with `"tags are not supported"`, and `_content`, `_anchor_token`, `_from_content_start` and `_content_start` (for anchored nodes, step-6 R-2).
- **Fact checked with ruamel**: in `a: !literal file:x.md` the `ScalarEvent.start_mark` is at the `!` (index 3). In `c: &x !literal y` it is at `&x`, and in `c: !literal &x y` it is at `!literal`. `event.tag` is `'!literal'` for the shorthand form.
- Tests that pin the current messages, which must stay green unchanged:
  - `tests/unit/test_yamlcore.py:207,212,401`
  - `tests/unit/test_values.py:109-111`
  - `tests/unit/test_loader_aliases.py:238` (`"a: !t 1"` → "tags are not supported at line 1")
  - `tests/integration/test_set_overrides.py:317`

  The contract (`contracts/cli.md`, "Bad tag") deliberately keeps the old message for other tags.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP02 --agent <name>`. This WP has no dependencies and can run in parallel with WP01 and WP03.

## Subtasks

### T006 — `RawTag` and content-start spans

1. Add:

   ```python
   LITERAL_TAG: Final = "!literal"

   @dataclass(frozen=True)
   class RawTag:
       """The ``!literal`` tag written on a scalar: ``start``/``end`` span the tag token plus
       the blanks after it, up to the scalar's content (research R-4)."""
       start: int
       end: int
   ```

   and add `tag: RawTag | None = None` to `RawScalar` only.

2. In `_node`, when `event.tag == LITERAL_TAG` and the event is a `ScalarEvent` in file mode:
   - find the tag token: `text.startswith("!literal", i)`, searching from `event.start_mark.index`. When an anchor comes first, the tag follows it, so search forward (as `_anchor_token` does) but **only** within the node's leading properties, not into the content;
   - the tag span ends after the tag token and any following blanks or line breaks. Use `_content_start(text, tag_end)`, which also skips a comment, so the span runs up to the content;
   - the scalar's `start` becomes the content start, the same index an untagged scalar would have.

   Both orders, anchor then tag and tag then anchor, must give the same content start, and the anchor span must still be exactly `&name`. Write one helper, `_properties(text, start, anchor_name, tagged) -> (RawAnchor | None, RawTag | None, content_start)`, that scans the properties in written order. Use it for anchored and/or tagged nodes, and keep `_from_content_start` behaviour identical for anchor-only nodes.

3. **Empty tagged value** (`a: !literal` followed by a newline, or `[!literal ]`): ruamel gives a plain scalar with empty text. Set `start = end = tag.end`'s content position, the same as the "anchored empty value" rule in `_from_content_start`. The loader (WP05) will read it as the empty string `''`, not null, because the tag makes it a string.

4. **Block scalars**: `a: !literal |` followed by indented lines. The content start must be at `|`, because `blocks.parse_block(text, start, …)` expects the indicator there. Add a test.

### T007 — File-mode tag rules

In `_node`:
- `event.tag is None` → unchanged.
- In **VALUE mode** (`allow_anchors=False`), any tag → `_refuse(event, …)` as today. The message stays `anchors and tags are not supported at line N`.
- In **file mode**:
  - `tag == "!literal"` on a `ScalarEvent` → accept (T006).
  - `tag == "!literal"` on a `MappingStartEvent`/`SequenceStartEvent` → refuse with `"!literal applies only to scalars"`, giving `cannot parse <file>: !literal applies only to scalars at line N` (contract table).
  - Any other tag, including `!!str` and verbatim `!<…>` forms → the existing `"tags are not supported"` message, unchanged.

  Only the exact resolved tag string `!literal` is accepted. Document that a `%TAG` directive mapping `!` elsewhere is out of scope: ruamel reports the resolved tag, and only `!literal` passes.

Keep the "first refusal wins, raised after the document parses" behaviour.

### T008 — Unit tests (`tests/unit/test_yamlcore.py`)

Add tests whose names state what they prove:
- `test_literal_tag_on_plain_scalar_spans_tag_and_content_starts_after_it`: for `a: !literal file:x.md\n`, `tag.start` is 3, `tag.end` is the index of `f`, and `start` is the same index. Also check `text[tag.start:tag.end] == "!literal "`.
- `test_literal_tag_on_quoted_scalars` (single, double), `..._on_block_literal_and_folded_scalars` (content start at `|`/`>`), `..._with_two_spaces_before_content`.
- `test_literal_tag_and_anchor_in_either_order_give_the_same_content_start`: `&a !literal x` and `!literal &a x`. The anchor span is exactly `&a` in both.
- `test_empty_literal_tagged_value_has_empty_span_after_the_tag`: block and flow forms.
- `test_literal_tag_inside_flow_mapping_and_sequence`: `{u: !literal https://x}` and `[!literal a, b]`.
- `test_literal_tag_on_mapping_is_refused_naming_the_line`; same for a sequence, block and flow.
- `test_other_tags_are_still_refused_with_the_old_message` (`!t`, `!!str`, `!<tag:x>`).
- `test_value_mode_still_refuses_literal_tag_with_the_old_message`: `compose("!literal x", "VALUE …")` → `anchors and tags are not supported at line 1`.
- `test_untagged_scalars_have_unchanged_spans` (regression for a few styles).

### T009 — Docstrings and other `compose` callers

- Update the `compose` docstring and the `_Composer` class docstring: `!literal` is accepted on scalars in file mode only, how the span is laid out, and the refusals.
- Check the other file-mode callers, which need no edit:
  - `writeback/collections.detect_indent` swallows `LoadError`;
  - `_check_open_end` would now compose `!literal` files successfully, which is what we want.
  - `writeback/scalars._round_trips_plain` and `writeback/apply._include_string` compose in VALUE mode, and WP08 replaces the latter.

  Record that check in the Activity Log; do not edit those files.
- Run the whole suite: no existing test may change.

## Definition of Done

- The tests above pass, the whole suite passes unchanged, and all four gates pass, with output pasted.
- No change outside `yamlcore.py` and its tests.

## Risks

- **Span drift** for tagged anchored nodes. Mitigation: one property scanner, with tests for both orders and every scalar style.
- **A comment between tag and content** (`a: !literal # c` followed by an indented value on the next line) is unusual but valid YAML. Mitigation: `_content_start` already skips comments; add one test.

## Reviewer guidance

- The VALUE-mode message is unchanged for every tag.
- Only `RawScalar` carries a tag. Collections with `!literal` are refused.
- Spans of untagged nodes are byte-for-byte identical to before.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
