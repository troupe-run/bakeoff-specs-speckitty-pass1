---
work_package_id: WP01
title: Event-based composer
dependencies: []
requirement_refs:
- FR-002
- FR-010
planning_base_branch: fix/troupe-config-anchor-aliases
merge_target_branch: fix/troupe-config-anchor-aliases
branch_strategy: Planning artifacts for this mission were generated on fix/troupe-config-anchor-aliases. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into fix/troupe-config-anchor-aliases unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
phase: Phase 1 - Parsing
history:
- at: '2026-10-06T15:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/yamlcore.py
create_intent: []
execution_mode: code_change
owned_files:
- src/troupe/yamlcore.py
- tests/unit/test_yamlcore.py
- tests/unit/test_values.py
role: implementer
agent: claude
model: ''
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-qht
---

# Work Package Prompt: WP01 – Event-based composer

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

Replace ruamel's composer in `src/troupe/yamlcore.py` with our own composer over ruamel's **parser events**. The new composer must know where every `&anchor` and every `*alias` is written. ruamel's composer returns the anchored node object for an alias and loses the alias's position (research R-1), which the step-6 write rules need.

This WP changes **no behaviour visible through the CLI**. `compose(text, source)` keeps its signature and, by default (`allow_anchors=False`), still refuses anchors and aliases with exactly today's message. WP02 opts the loader in with `allow_anchors=True`. `values.parse_value` keeps the default, so VALUE keeps refusing anchors and aliases with exit 2 (spec C14, FR-010).

## Context

- Spec: FR-002, FR-010, C2, C14; Edge Cases (undefined alias, redefined anchors).
- Research: **R-1** (composer), **R-2** (content-start spans). Read both fully.
- Data model: "Raw nodes".
- Current code: `src/troupe/yamlcore.py`, especially `compose` and `_convert` (`text[start] in "&!"` refusal) and the module docstring's "Span behaviour" list. The rest of the code relies on those spans, so keep the list true and extend it.
- Consumers of raw nodes: `loader.py`, `values.py`, `writeback/collections.py` (`detect_indent`, `_first_step`, `_shape`), `writeback/apply.py` (`_include_string`). They must keep working unchanged in this WP.

Experiment output on the reporter's file (`defaults: &d\n  model: opus\ncoder:\n  settings: *d\n...`):

```
MappingStartEvent anchor=d 10..15 '&d\n  '     # start mark is the '&'
ScalarEvent       model 15..20
AliasEvent        d 46..48 '*d'                # exactly the alias token
ScalarEvent       anchor=m 52..59 "&m  'x'"    # scalar start is the '&'
```

## Branch Strategy

- Planning/base branch: `fix/troupe-config-anchor-aliases`; final merge target: `fix/troupe-config-anchor-aliases`, merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`; run `spec-kitty agent action implement WP01 --agent <name>` (no dependencies).

## Subtasks

### T001 — Event composer, `RawAnchor`, `RawAlias`, `allow_anchors`

**Purpose**: build the same `RawScalar`/`RawMapping`/`RawSequence` trees as today from `YAML(typ="safe", pure=True).parse(text)` events, plus anchors and aliases.

**Steps**:
1. Add frozen dataclasses:
   - `RawAnchor(name: str, start: int, end: int)`: the span of the `&name` token. It is `start` of the event's start mark plus `1 + len(name)`; verify that `text[start] == "&"`.
   - `anchor: "RawAnchor | None" = None` as the **last** field of `RawScalar`, `RawMapping` and `RawSequence`, keyword-default so every existing constructor call still works.
   - `RawAlias(name: str, start: int, end: int, target: "RawNode")`: span from the `AliasEvent` marks.
   - `RawNode = RawScalar | RawMapping | RawSequence | RawAlias`.
2. Write `compose(text, source, *, allow_anchors=False)`:
   - iterate events with a small recursive-descent reader, either an index into a list of events or an iterator with one-event lookahead;
   - `StreamStart`/`DocumentStart`, then one node, then `DocumentEnd`/`StreamEnd`;
   - an empty document (no node event, or a plain empty scalar at the root as today) returns `None`, with exactly today's behaviour; see `test_empty_document_composes_to_none`;
   - `ScalarEvent`: `RawScalar(text=event.value, style=_STYLES[event.style], ...)`;
   - `MappingStartEvent` … `MappingEndEvent`: read key and value nodes in pairs; `flow=bool(event.flow_style)`;
   - `SequenceStartEvent` … `SequenceEndEvent`: read items;
   - spans: `start_mark.index` and `end_mark.index`. For collections, `end` is the `*EndEvent`'s `end_mark.index`, which is what composed nodes report today. **Check this against ruamel's composer for the existing tests**: `test_yamlcore.py` pins today's spans and must keep passing unchanged.
3. Anchors: keep a dict `name → RawNode` of **completed** anchored nodes and a set of names whose node is still open. When an event carries `anchor`, add the name to the open set, build the node, attach `RawAnchor`, then move the name to the dict. A later anchor with the same name overwrites the entry (YAML rule: an alias refers to the most recent definition before it).
4. `AliasEvent`: if the name is open → recursive alias (T003); if absent → undefined alias (T003); else `RawAlias(name, start, end, target=dict[name])`.
5. Keep ruamel isolated: this is still the only module that imports `ruamel`. Update the module docstring: describe the composer, the new types and the extended span list (T002).

**Files**: `src/troupe/yamlcore.py`.

**Validation**: every existing test in `tests/unit/test_yamlcore.py` passes unchanged except `test_anchors_aliases_and_tags_are_refused` (see T003 and T004), and the full suite stays green.

### T002 — Content-start spans for anchored nodes (R-2)

**Purpose**: an anchored node must have exactly the span an unanchored node would have, so writers keep their assumptions (`entry_column`, `insertion_point`, `_replace_span`, `replace_value_edits`).

**Rules** (`start` of the raw node; ends unchanged):
- **Block mapping**: the first key's `start`. Empty block mappings cannot carry an anchor in a way that differs; an anchored empty value is a scalar, see below.
- **Block sequence**: the first `-`. The `SequenceStartEvent` mark after the anchor is not reliable, so use the first item's position: scan back from the first item's start to the `-` on its line, or search forward from the anchor end for the first non-space, non-comment character, which must be `-`.
- **Flow collection**: the `{` / `[`. Search forward from the anchor end, skipping spaces, tabs, line breaks and comment lines.
- **Scalar**: the first character after the anchor token and any following spaces, tabs, line breaks and comment lines. For quoted scalars that is the quote, for block scalars the `|` / `>`.
- **Anchored empty value** (`a: &x` then a line break, or `[&x , b]`): a zero-width null scalar whose `start == end ==` the anchor's `end`. Value `""`, style plain, so it resolves to `None`.

Write one private helper, e.g. `_content_start(text, after_anchor)`, that skips blanks, line breaks and `#` comments. Use the existing comment rules, where a `#` must be preceded by whitespace or the start of a line, consistently with `writeback/comments.find_comment_start`. Do **not** import writeback modules from `yamlcore`; reimplement the tiny skip here.

**Validation**: for each case, the span of `compose("k: &a <value>\n")` equals the span of `compose("k: <value>\n")` shifted by the anchor's length plus one space (unit tests in T004).

### T003 — Refusals and the legacy switch

All raise `LoadError` with messages starting `cannot parse {source}: ` (as today) and ending `at line N` (1-based line of the offending token):

- **Tag** (any event whose `tag` is not `None`): `tags are not supported at line N` (spec C2). With `allow_anchors=False` the message stays `anchors and tags are not supported at line N`, so steps 1–5 are byte-for-byte unchanged until WP02 switches the loader.
- **Anchor or alias with `allow_anchors=False`**: `anchors and tags are not supported at line N`. This is today's text, used by `values.parse_value` (exit 2 via `UsageError`) and by `detect_indent`, which simply falls back to the default step.
- **Undefined alias**: `undefined alias *name at line N`. Today's `a: *undefined` gives a parse error starting `cannot parse`; `test_invalid_yaml_raises_load_error_naming_source` must still pass.
- **Recursive alias** (alias to an anchor whose node is still open, e.g. `a: &x [*x]`): `recursive alias *name at line N`.
- **More than one document**: keep today's behaviour and message. Check what ruamel's `compose` raises today for `"a: 1\n---\nb: 2\n"` (a `ComposerError` "expected a single document"). Reproduce the same text so `_describe` output is unchanged; a test pins it.
- Parser errors (`MarkedYAMLError`, `YAMLError`) map exactly as today (`_describe`, first line).

**Note**: whether an anchor or alias is allowed is decided here, in one place, by `allow_anchors`. The loader (WP02) decides *which* anchor uses are allowed (C3, C13), because that depends on the include rule.

### T004 — Unit tests

In `tests/unit/test_yamlcore.py`, with names that state what they prove:
- `test_alias_records_its_own_span_and_target`: the reporter's file; the `RawAlias` at `coder.settings` has `text[start:end] == "*d"` and `target is` the anchored `RawMapping`.
- `test_anchor_records_the_ampersand_token_span`: `text[a.start:a.end] == "&d"`.
- `test_anchored_block_mapping_starts_at_its_first_key`.
- `test_anchored_block_sequence_starts_at_its_first_dash`, and `..._flow_collection_starts_at_bracket`.
- `test_anchored_scalar_span_excludes_the_anchor` (plain, single, double, literal; the anchor followed by two spaces; the anchor at the end of the line with the value on the next line).
- `test_anchored_empty_value_is_zero_width_null_after_anchor`.
- `test_redefined_anchor_applies_to_later_aliases`.
- `test_undefined_alias_is_refused_naming_line`, `test_recursive_alias_is_refused_naming_line`.
- `test_tags_are_refused_when_anchors_are_allowed` (`!!str`, `!t`, a verbatim tag) and `test_anchors_and_aliases_are_refused_by_default`. The second replaces the old parametrized test; keep the old test's three inputs.
- `test_spans_without_anchors_are_unchanged`: compose a corpus of the existing fixture texts with both the old ruamel composer (inline in the test via `ruamel.yaml`; tests may import ruamel) and the new one, and compare every span. This is the strongest guard against R-2 regressions; include block scalars with keep/strip chomping, flow collections, empty values, comments and CRLF.

In `tests/unit/test_values.py`:
- `test_parse_value_rejects_anchor_alias_and_tag_with_usage_error` for `*d`, `&a 1`, `[&a 1, *a]` and `!t x`. Each raises `UsageError`, and the message quotes VALUE (spec C14).

**Run**: `uv run pytest tests/unit/test_yamlcore.py tests/unit/test_values.py`, then the whole suite.

## Definition of Done

- `compose` uses parser events; `RawAnchor` and `RawAlias` exist; anchored spans follow R-2.
- Default behaviour is unchanged: the full existing suite passes, with the old anchor-refusal test replaced by its default-behaviour equivalent.
- New unit tests above pass. `uv run pytest`, `uv run mypy --strict`, `uv run ruff check`, `uv run ruff format --check` all pass, with output pasted in the handoff.
- Module docstring updated, including the span list and the `allow_anchors` decision.

## Risks

- **Span drift** in the composer rewrite breaks writers silently. The corpus-comparison test (T004) is mandatory.
- **ruamel event details** (`flow_style`, `style` values, implicit tags). Print the events for each fixture while developing; do not guess.

## Reviewer guidance

- Confirm no module other than `yamlcore` imports ruamel (tests excepted).
- Confirm `compose(...)` without `allow_anchors` behaves exactly as before, using the old suite plus the corpus test.
- Check the refusal messages name the source and the line.

## Activity Log

- 2026-10-06T15:00:00Z – system – Prompt generated via /spec-kitty.tasks
