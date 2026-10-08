---
work_package_id: WP08
title: 'set: remote content is read-only, literals and --include, verification with the schema'
dependencies:
- WP06
- WP07
requirement_refs:
- C-005
- FR-004
- FR-005
- FR-010
- FR-011
- FR-012
- NFR-001
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T034
- T035
- T036
- T037
- T038
- T039
- T040
- T041
phase: Phase 3 - Writing
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/writeback/apply.py
create_intent:
- tests/unit/test_placement_remote.py
- tests/integration/test_remote_readonly.py
- tests/integration/test_set_schema.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/writeback/placement.py
- src/troupe/writeback/apply.py
- src/troupe/commands/set_value.py
- src/troupe/cli.py
- tests/unit/test_placement_remote.py
- tests/integration/test_remote_readonly.py
- tests/integration/test_set_schema.py
- tests/integration/test_set_existing.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP08 – `set`: remote content is read-only, literals and `--include`, verification with the schema

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

This WP wires every step-7 write rule into `set`. It is the largest WP and touches the most sensitive code, so read `placement.py` and `apply.py` whole before starting.

1. **Read-only remote content** (S-4, R-7). `placement.remote_refusal` runs at two checkpoints:
   - in `place`, before alias routing;
   - in `apply_set`, on the files a plan would write.

   The message quotes the outermost include string exactly as written in the local file.
2. **Verification with the schema** (S-9, S-12, R-10). In-memory reloads go through `configuration.load_configuration`, reusing the command's `fetched` cache:
   - a schema violation → exit 3 naming PATH and the schema file;
   - a new include that cannot be read or fetched → exit 3 naming the cause.
3. **Literals and `--include`** (S-11, S-12, S-13, R-8, R-9):
   - `apply_set` runs `includes.mark_literals`;
   - the no-op check tells an include from a literal;
   - replacing a scalar keeps, inserts or removes the `!literal` tag as a separate edit;
   - `set --include` reaches `apply_set` from the CLI.

US6's end-to-end tests are WP09; this WP tests US2, US3 and the `set` half of US5, plus focused cases for the literal and `--include` mechanics.

## Context

- Spec: US2, US3, US5-3, S-4, S-5, S-9, S-11, S-12, S-13; FR-004, FR-005, FR-010, FR-011, FR-012; NFR-001, NFR-002, NFR-003.
- Research: **R-7**, **R-8**, **R-9**, **R-10**, R-12. Contract message table (`contracts/cli.md`).
- Inputs:
  - WP04: `includes.mark_literals`, `path_steps`, `LiteralStr`, `IncludeStr`, `include_kind`.
  - WP05: `SourceFile.path: Location`, `.remote`, `ScalarNode.literal`, `load(..., schema=, fetched=)`.
  - WP06: `configuration.load_configuration`, `configuration.violation`, `Session.schema`/`fetched`.
  - WP07: renderers tag `LiteralStr` for new values; kind-changing replacement removes tags; alias copies keep them.
- Existing code (read first):
  - `placement.place`, `_route_aliases`, `_through_alias`, `_existing`, `_include_ref`, `concrete_parent`;
  - `apply.apply_set`, `_plan_expansion`, `_plan_text`, `_edits`, `_scalar_edits`, `_replace_span`, `_matches`, `_include_string`, `_verify`, `_refuse`, `_same_outside`;
  - `writeback.apply_edits`: adjacent edits are fine, overlapping ones raise;
  - `commands/set_value.run`; `cli.build_parser`.
- Tests that call `apply_set` directly: `tests/integration/test_set_overrides.py:418` and `tests/integration/test_overrides_acceptance.py:496`. New parameters must be keyword-only with defaults that keep them working unchanged.

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Run `spec-kitty agent action implement WP08 --agent <name>`. It depends on WP06 and WP07.

## Subtasks

### T034 — `placement.remote_refusal` (checkpoint 1)

```python
def remote_include_on_route(found: Walk) -> YamlInclude | TextInclude | None: ...
def remote_refusal(found: Walk, dotted: str) -> WriteRefused: ...
```

- **`remote_include_on_route`** scans `found.nodes` from the root and returns the **first** include whose target is remote:
  - a `YamlInclude`/`TextInclude` with `target.remote`;
  - a `MergedMapping` whose `ref` has `ref.target.remote` (return the `ref`).

  Because it is the first, its `origin` lies in a local file. Assert `not include.origin.file.remote`, with a comment: nested remote includes are inside it (S-4).
- **Message** (contract):

  `f"{dotted}: value comes from remote include {include.origin.source} ({include.origin.file.path} line {line}); troupe does not change remote content — change that include line instead; no file changed"`

  - `origin.source` is the include string **exactly as written**, quotes included. For `$ref` form it is the `$ref` value's source.
  - Compute the line from `origin.start`, as other messages do.
- **Checkpoint 1** in `place`: right after the D-6 `$ref` check and `walk`, and **before** `_route_aliases`. When `found.remaining` is empty (an existing PATH), refuse if the value at PATH comes from remote content: let `last = found.nodes[-1]`; refuse if
  - `last.origin.file.remote` is true (for an `AliasNode`, its own origin), or
  - `last` is a `YamlInclude`/`TextInclude` with a remote target, or
  - `last` is a `MergedMapping` with a remote `ref`.

  A local override inside a mapping-form remote include is local, so it does not refuse. Check this with a test (US2-5).
- New keys (`remaining` non-empty) are **not** refused here: S-5 makes them local overrides, and checkpoint 2 catches every route that would write remote content.
- Update the `place` docstring's "Raises" list and the module docstring: the remote rule and its order before the alias rule (research R-7).

### T035 — Checkpoint 2 in `apply_set`

- After every plan branch has computed its `files` (ordinary edits, expansion and text include), call `_refuse_remote(root, segments, dotted, files)`:
  - if any `SourceFile` key has `remote` true, raise `remote_refusal(walk(root, segments), dotted)`;
  - if no remote include is on the route (which should be impossible), raise `WriteRefused(f"{dotted}: the change would write remote content {file.path}; no file changed")`.
- This catches:
  - `--in-include` into a remote include (S-4);
  - a list append in remote content;
  - a new key inside a remote list item;
  - an `--expand-alias` copy in remote content.
- `fileio.write_files` (WP05) remains the last net. Add a comment pointing at it.

### T036 — Verification and expansion reload through the configuration

1. Add a keyword-only parameter `context: SetContext | None = None` to `apply_set`, where:

   ```python
   @dataclass(frozen=True)
   class SetContext:
       theatre: Theatre
       schema: Schema | None
       fetched: dict[Url, str]
   ```

   `None` (the existing direct-call tests) means: reload with `loader.load(config_file, overrides)`, no schema and a fresh `fetched`, exactly as before.
2. `_verify` and `_plan_expansion` reload through one helper, `_reload(root, overrides, context)`. With a context it calls `load_configuration(context.theatre, overrides, context.fetched)` **without** validating inside, so it can tell the causes apart. Either call `loader.load(..., schema=context.schema, fetched=context.fetched)` and then `configuration.violation(tree, schema)` yourself, or give `load_configuration` a `validate=False` flag (WP06 owns that file; prefer the first option).
3. Outcomes in `_verify`:
   - a schema violation → `WriteRefused(f"{dotted}: the change would not match schema {schema.path} at {v.path}: {v.message}; no file changed")` (S-9);
   - a `LoadError` from the reload, such as a new include target that is missing or a new URL that fails to fetch → `WriteRefused(f"{dotted}: {err.message}; no file changed")` (S-12). This replaces the generic "byte-surgically" refusal **for load errors only**. Read-back, anchor and `_same_outside` failures keep `_refuse`.
4. Check the order: the schema check runs after read-back succeeds, so a write that does not even read back still gets the generic refusal.
5. The annotation-only edits WP05 made (`dict[Location, str]` and so on) become real code here.

### T037 — Literal marking, no-op rule, CLI flag

1. Add the keyword-only `include: bool = False` to `apply_set`. Before `place`:
   - `steps = includes.path_steps(root, segments)`;
   - `value = includes.mark_literals(value, steps, context.schema if context else None, include=include, dotted=dotted)`.

   A `WriteRefused` (`--include` on a `uri` path) propagates: exit 3, nothing loaded twice, nothing written.
2. `_matches` (R-9):
   - an include node (`YamlInclude`/`TextInclude`) matches only an `IncludeStr` equal to `_include_string(node)`;
   - a `ScalarNode` matches a `str` with the same value only if the value is **not** an `IncludeStr`. A `LiteralStr` matches both a literal and a plain string scalar of the same text.
   - Update the docstring.
   - Watch the step-1 behaviour: `set b file:p.md` on `b: file:p.md` is now **not** a no-op. It writes `b: !literal file:p.md` (S-13). `set --include b file:p.md` on it **is** a no-op.
3. **Text includes** (`_plan_text`, step-1 FR-010): VALUE is file text. Convert `LiteralStr`/`IncludeStr` to a plain `str` before writing, and keep the step-1 behaviour exactly; existing tests must pass unchanged.
4. **`cli.py`**: `set_.add_argument("--include", action="store_true", help="write include-looking strings in VALUE as includes instead of !literal strings")`. Update the module docstring (the flag exists only on `set`, other subcommands give exit 2).
5. **`commands/set_value.run`**: pass `include=args.include` and `context=SetContext(session.theatre, session.schema, session.fetched)`. Use the location's `str` in the write-failure message; it is already f-string-safe.

### T038 — Tag edits when replacing a scalar

In `_scalar_edits` (and wherever a `ReplaceScalar` is rendered, including the block paths through `blocks.replace_block`/`replace_with_multiline` and the flow multi-line `render_string(value, "double")` at about line 408):
1. Render the new value as a **plain `str`**: `str(value)` for markers. Replacement renderers never see markers (WP07 contract).
2. Then add a separate tag edit, by these rules:

   | Existing `node.literal` | New value | Edit |
   |---|---|---|
   | none | `LiteralStr` | insert `scalars.LITERAL_PREFIX` at `node.origin.start` (a zero-length `TextEdit`, adjacent to the content edit) |
   | none | anything else | none |
   | tag | `LiteralStr` or plain `str` | none: the tag is kept (S-11) |
   | tag | `IncludeStr` or non-string | delete `[literal.start, literal.end)` |

3. A block-scalar replacement whose edits start at `origin.start` is adjacent to the insertion. `apply_edits` accepts adjacent edits and applies an insertion before an edit that starts at the same index. Prove this with a test that ends in `key: !literal |`.
4. `ReplaceCollection` (collection → string): the new value is rendered by WP07's renderers, which tag `LiteralStr`. Nothing else is needed here, but add one test.

### T039 — Unit tests `tests/unit/test_placement_remote.py`

Build trees with `loader.load` against the `remote` fixture (set `NO_PROXY`). Name tests by what they prove:
- an existing remote scalar → `WriteRefused` whose message contains the include string as written, the local file and the line;
- a quoted include string (`team: "http://…/team.yaml"`) → the message contains the quotes as written;
- `$ref` form: a remote value is refused; a local override is **not** refused (it gives `ReplaceScalar` in the local file);
- a whole remote include (`team`), a remote text include and a `MergedMapping` with a remote ref → refused;
- nested remote (local → remote A → remote B) → the message names A's include string, the outermost;
- an alias inside remote content → the remote refusal, **not** the `--expand-alias` message (ordering);
- a new key under a remote include → no refusal at checkpoint 1 (placement is `ConvertInclude` or `AddKeys` on the local holder).

### T040 — Integration `tests/integration/test_remote_readonly.py` (US2, US3)

CLI subprocess tests with `snapshot` before and after, `history_events` and the server request log:
1. `test_changing_a_remote_value_exits_3_quoting_the_include_line` (US2-1): exactly one stderr line containing the include string; no file changed; no event; only `GET`s logged (NFR-001).
2. `test_setting_a_remote_text_include_exits_3` (US2-2)
3. `test_list_append_in_remote_content_exits_3`, `test_in_include_into_remote_content_exits_3`, `test_replacing_a_whole_remote_include_exits_3` (US2-3)
4. `test_value_from_nested_remote_include_names_the_outermost_include` (US2-4)
5. `test_local_override_of_remote_include_changes_only_that_line` (US2-5; byte-exact file)
6. `test_new_key_under_scalar_remote_include_becomes_a_local_override` (US3-1): the exact file text from the spec, including the `# shared` comment placement.
7. `test_new_key_under_mapping_form_remote_include_is_added_beside_overrides` (US3-2)
8. `test_expand_alias_in_remote_content_exits_3_quoting_the_include` (S-4)
9. `test_new_key_under_alias_in_remote_content_is_refused_mentioning_expand_alias` (S-5)

### T041 — Integration `tests/integration/test_set_schema.py` (US5-3) and literal mechanics

1. `test_set_that_would_violate_the_schema_exits_3_naming_path_and_schema` (US5-3): no file change, no event.
2. `test_set_whose_new_include_cannot_be_fetched_exits_3_naming_the_url` (`--include` with a 404 URL).
3. `test_set_with_include_on_a_uri_path_exits_3`
4. `test_include_flag_on_other_subcommands_exits_2` (`get`, `show`, `history`, `watch`)
5. `test_set_on_unrelated_path_reuses_one_fetch_per_url` (request log: one `GET` per URL for the whole `set`, including its verification reload; R-10)
6. `test_replacing_a_tagged_value_with_a_number_drops_the_tag` and `test_literal_value_replacing_an_untagged_block_scalar_gets_the_tag_before_the_indicator` (T038)

## Definition of Done

- All new tests pass and the whole suite passes. S-13 changes two step-1 tests in `tests/integration/test_set_existing.py` (owned here): `test_value_naming_an_existing_text_file_becomes_an_include` and `test_value_naming_a_missing_include_target_is_refused`. Each gets a `--include` variant that keeps the step-1 assertion. The first also gets a variant without the flag, asserting `b: !literal file:p.md` and that `get b` prints `file:p.md`. The missing-target variant now expects the S-12 message, which names the target, instead of "byte-surgically". Rename the tests so their names state what they prove. No other existing test may change.
- All four gates pass, with output pasted.
- No write path can reach a remote `SourceFile`: checkpoint 2 plus the `fileio` net, both tested.

## Risks

- **Refusal ordering**: remote before alias, alias before the rest. Mitigation: explicit tests (T039).
- **`_matches` change** could alter step 1–6 no-op behaviour beyond S-13. Mitigation: run the whole suite after T037 alone, and investigate any other failing test before changing it. Only S-13 tests may change.
- **Adjacent tag edits**: tests for every replacement style (plain, quoted, block, flow).

## Reviewer guidance

- One message builder for remote refusals, used at both checkpoints. Messages match the contract.
- Reloads within one `set` never fetch a URL twice (request log test).
- Direct `apply_set` callers in existing tests still work without `context`.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
