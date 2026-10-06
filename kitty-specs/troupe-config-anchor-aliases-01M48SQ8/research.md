# Research & Decisions: troupe configuration: anchors and aliases stay honest

Implementation decisions for step 6 (contract *Aliases*). Product-level choices are spec A-0 and C1–C14. Everything below was checked against the code at `main` 103058d and ruamel.yaml 0.19.

## R-1 — Compose from parser events, not with ruamel's composer

- **Finding.** `YAML(typ="safe").compose()` resolves an alias to the anchored `Node` object itself, so the alias's own position (`*d` at line 4) is lost. The parser events keep it: `AliasEvent(anchor="d")` has `start_mark`/`end_mark` covering exactly `*d`. Experiment on the reporter's file: `MappingStartEvent anchor=d 10..15 '&d\n  '`, `AliasEvent d 46..48 '*d'`.
- **Decision.** `yamlcore.compose` walks `YAML(typ="safe", pure=True).parse(text)` and builds `RawScalar`/`RawMapping`/`RawSequence` itself (about 60 lines). It also builds:
  - **`RawAlias(name, start, end, target)`** for each alias event. `target` is the anchored raw node most recently defined under that name, per the YAML rule that a redefined anchor applies to later aliases.
  - **`RawAnchor(name, start, end)`** on the raw node of each event carrying `anchor`. Its span is the `&name` token.
- **Refusals** (`LoadError`, exit 4, file and line in the message):
  - any event with an explicit tag: `tags are not supported at line N` (C2);
  - an alias whose name is not defined yet: `undefined alias *x at line N`;
  - an alias to an anchor whose node is still open: `recursive alias *x at line N`;
  - a second document: the same message as today for multiple documents.

  ruamel's parse errors map exactly as today (`_describe`).
- **Alternatives.** We could subclass ruamel's `Composer` to record alias marks. That ties us to ruamel internals across versions and still returns shared node objects. Positions recovered by scanning the text for `*` are fragile because of quoting and comments. Both rejected.
- `values.parse_value` keeps refusing anchors, aliases and tags (C14). It checks the raw tree for any `RawAnchor`/`RawAlias` and raises `UsageError` (exit 2), with the same wording style as today.

## R-2 — Spans of anchored nodes start at the content

- **Finding.** With an anchor, ruamel's start mark is the `&` (`&d\n  model` → start 10). Existing writers assume a block collection starts at its first key or dash (`entry_column`, `_gains_override`, `replace_value_edits`) and a scalar's span is the scalar text (`_replace_span`). The old code relied on this by refusing anchors outright (`text[start] in "&!"`).
- **Decision.** For a node with an anchor, the raw `start` is the content start:
  - block mapping: the first key's start;
  - block sequence: the first dash;
  - flow collection: `{` or `[`;
  - scalar: the first character after the anchor token and any following spaces, tabs, line breaks and comment lines.

  Ends stay as reported. An anchored empty value (`a: &x` then a newline) becomes a zero-width null at the anchor's end. Unit tests pin each case.
- With this, every existing writer sees anchored nodes exactly as unanchored ones. Only `replace_value_edits` must know about the anchor token, because it rewrites the key's line (R-9).

## R-3 — `AliasNode` in the tree; dispatch sites

- `tree.Anchor(name: str, origin: Origin, path: tuple[str, ...])`. `path` is the merged path where the anchored node is loaded; it is used for the verifier's identity rule (R-8).
- `ScalarNode`, `MappingNode` and `SequenceNode` gain `anchor: Anchor | None = None`. The field is keyword-only with a default, so existing constructors are unchanged.
- `tree.AliasNode(origin, name, target, anchored, merge, written)`:
  - `origin`: the span of the `*name` token. For a merge-derived node, the span of the alias inside the `<<` value, or the `<<` key's span for an inline mapping.
  - `target`: the node reached. For a written alias this is the anchored node itself (shared object); for a merge-derived node it is the merged-in entry's value.
  - `anchored`: the anchored node, or `None` for an inline `<<` mapping.
  - `merge`: `True` when reached through `<<`.
  - `written`: the written `AliasNode` to expand, or `None` for merge-derived nodes.

  `Node` gains `AliasNode`.
- **Loader.** Converting a raw anchored node registers `id(raw) → Node`. Converting a `RawAlias` returns `AliasNode(target=<that Node>)`, so the anchored node is converted once and shared. Since YAML defines anchors before their aliases, the anchored node is always already converted.
- **Dispatch sites that must handle `AliasNode`** (found with `grep isinstance` over `src/troupe`):

  | Site | Change |
  |---|---|
  | `paths.unwrap` | Unwraps it like `YamlInclude`, so `walk`, `lookup` and `get` resolve through aliases. |
  | `leaves._collect` | Recurses into `target`, giving resolved leaves (C1, C11). |
  | `yamlout._content` | Unwrapping is enough for `show`. |
  | `values.scalar_of` | Unwrapping is enough for `show`. |
  | `reconcile._collect` | Adds no files; does not recurse (the anchored node is collected at its own place). |
  | `placement._children` / `_peel` | Never descends into aliases: aliases are not concrete containers (R-6). |
  | `apply._matches` | Compares through `unwrap`. |
  | `apply._same_outside` | Uses the alias rule (R-8). |
  | `merge._merge_entry` | Unwraps for its "both are mappings" test (R-4). |

## R-4 — Merge keys: `MergeKeyMapping` view (A-0)

- **Recognition.** A plain-style key `<<` (unquoted; `'<<'` stays an ordinary key, as YAML 1.1 readers treat it) whose value is one of:
  - an alias to a mapping;
  - a mapping (block or flow);
  - a flow or block sequence of those.

  Anything else → exit 4: `cannot load F: P.<<: merge value must be a mapping, an alias of one, or a list of those`. A `<<` in a mapping that also has `$ref` → exit 4 (C13).
- **Semantics** (YAML 1.1 merge type; `merge.merge_keys`). Keys written in the mapping win. Among sources, earlier ones win. A source that is itself a `MergeKeyMapping` contributes its view entries.
- **Shape.** `MergeKeyMapping(MappingNode)` with `written: MappingNode`, the concrete mapping including its `<<` entry, and `entries` as the view:
  - written entries in written order, with the `<<` entry replaced in place by the merged-in entries that no written key shadows;
  - each merged-in entry is a new `MappingEntry` with the source's key fields and value `AliasNode(merge=True, target=<source value>)`.

  `origin` and `flow` are those of `written`.
- **Writers.** Writers never receive the view. `placement._children` yields `written`'s entries, so a key written locally is replaced in place. `AddKeys` targets `written`, so a new key goes after the last written entry (step-1 rule) and the `<<` line is untouched (FR-007).
- **Interaction with `$ref` merges.** `deep_merge` treats a `MergeKeyMapping` like any mapping (it is one). C13 prevents the two mechanisms from meeting in one mapping.

## R-5 — Load-time restrictions (C3)

In `loader`, the one place the include rule lives, all with exit 4 and naming the file and line:

- A raw anchored node that is an include string (scalar starting `file:`), or a mapping with a `$ref` key, or contains either at any depth: `cannot load F: anchor &a at line N is on an include reference (or contains one); anchors may not share includes`. Any alias of it is then unreachable.
- An anchored mapping key, or a `RawAlias` as a key: `cannot load F: mapping key at line N under P has an anchor or is an alias`.

Existing step-5 tests that expect `anchors and tags are not supported` for `coder: &a file:x.yaml` and `coder: !t file:x.yaml` switch to the new C3 and C2 messages. Exit code 4 is unchanged.

## R-6 — "Reached through an alias" (one place: `placement.place`)

- **Route scan.** After `walk(root, segments)`, the first `AliasNode` among `found.nodes[1:]` decides. These nodes are as found, and an alias on the route is visible because `walk` appends entry values unwrapped only for descent. This covers:
  - PATH itself being an alias (C4);
  - an alias above PATH;
  - the deepest existing ancestor of a new key being or lying below an alias (C6);
  - merge-derived nodes (`merge=True`).
- **Write-side scan.** For a new key whose deepest existing ancestor is a step-5 `MergedMapping`, `_on_side` and `_on_base` descend override or base sides. Meeting an `AliasNode` there means the write would land in the anchored node, so the same decision applies, using that alias. The same holds for `_include_ref`/`_on_side` routes inside holders.
- **Decision.**
  - `alias.merge` → `WriteRefused`: `P: <prefix> comes through the merge key '<<' (from *d); refusing to change a shared value (use --expand-alias to give it its own copy); no file changed`. With `expand_alias` the message instead says `merge keys are never written, so it cannot be expanded`.
  - Otherwise, without `expand_alias` → `WriteRefused`: `P: <prefix> is the alias *d in F line N, shared with its anchor &d; refusing to change it for every user (use --expand-alias to give this path its own copy); no file changed`.
  - With `expand_alias` → `ExpandAlias(alias=<written AliasNode>, parent, slot)`, where `parent`/`slot` come from `concrete_parent(root, alias)`.
- **Concrete containers.** `_children` does not descend into `AliasNode`, so `concrete_parent` of an anchored node or its children always finds the anchor's place. An alias is found as a value of its concrete parent.
- Anchored nodes reached directly are ordinary nodes: rules 1–5 of earlier steps apply (FR-003).

## R-7 — Expansion text (`writeback/aliases.expand_edits`)

Input: the file, the written alias, its concrete parent and slot, and the indentation step (`collections.detect_indent`).

- **Refusals** (`WriteRefused`, exit 3, naming PATH, `*name` and the file line, "no file changed"; C9):
  - the parent is a flow collection;
  - the alias is not on its key's line (mapping) or dash's line (sequence);
  - the line already has an end-of-line comment after the alias (`comments.find_comment_start`).
- **Edit.** Replace from the end of the head (`key:` or `-`) through the end of the alias token with `"  # expanded from *<name> by troupe"` for a collection copy, or `" <scalar>  # expanded from *<name> by troupe"` for a scalar copy. Then insert the copy's lines after that line.
- **Copy rendering** (C8), from the anchored node's content (`unwrap` of `anchored` for nested aliases), in block style:
  - **Placement.** Mapping keys sit at `key column + step` (step-1 indentation). Under a dash, the content goes at `dash column + 2` for mappings and nested items, matching the compact-form convention. For a sequence copy under a key, the offset follows `collections._sequence_offset` of the parent mapping.
  - **Keys.** Each key is written with its source text (`key_origin.source`) when that is on one line, else rendered with `scalars`.
  - **Scalars.** A scalar is written with its source text (`origin.source`, quoting kept) when the span is on one line. Otherwise multi-line strings become literal blocks (`blocks.render_new_multiline`) and other values use `scalars.render_scalar`.
  - **Aliases inside the copy.** Every inner `AliasNode` is written `*name` and stays an alias (C7).
  - **Anchors.** No `&name` is ever written, since spans exclude anchors (R-2), so inner anchors are dropped.
  - **Comments.** Comments are not copied.
  - **Empty collections.** Written as `{}` or `[]`.
  - **Line breaks.** The file's newline (`fileio.detect_newline`) is used throughout.
- **Nested aliases** (C7). Expansion happens one alias at a time. The loop in `apply_set` (R-8) re-places on the reloaded tree, so the next alias down the route is found and expanded with its own comment.

## R-8 — Apply loop and verification

- `apply_set(..., expand_alias=False)`. When `place` returns `ExpandAlias`, the loop:
  1. computes `expand_edits`;
  2. applies them to the current text of that file;
  3. reloads the configuration in memory (`load(config, overrides={file: text})`);
  4. places again.

  At most one expansion per alias on PATH; a guard of 64 iterations raises `WriteRefused`. Then the ordinary placement renders against the current text. The file's final text is the result, the edits being cumulative on that one file. If ordinary placement targets a different file, which cannot happen because anchors are per file, the code asserts.
- **Verification** compares the *original* tree with the final tree (`_verify`), so the history diff and the "nothing else changed" rule cover expansion and set together. `_same_outside` gains three rules:
  1. **Alias unchanged.** An old `AliasNode` outside the route matches only a new `AliasNode` with the same `name`, the same `merge`, and an `anchored.anchor.path` equal to the old one. The check does not descend, because the anchored node is compared at its own place.
  2. **Alias becomes a copy.** On the route, only when `expand_alias` was given and the old alias is a written alias (`merge=False`), a non-alias new node is compared against `unwrap(old)` recursively. It may differ only at PATH, inner aliases must stay aliases by rule 1, and `anchor` is ignored for the copy.
  3. **Anchors kept.** Outside the target, `old.anchor.name` must equal `new.anchor.name`, so no anchor is added, dropped or renamed. At the target itself, a replaced anchored collection or scalar must keep its anchor name (C5).
- **History.** `diff(flatten(before), flatten(after))` is unchanged code. Setting at an anchor yields one `set` per resolved alias path; an expand-and-set yields only PATH, because the copy has the same values (C11).
- **No-op.** `set --expand-alias P V` where V equals the current value is a no-op with no expansion: `_matches` is checked on the resolved node before expanding, and no files are written. This is the same "a no-op writes nothing" rule as step 1.

## R-9 — Kind-changing replacement keeps the anchor (C5)

- `collections._anchor()` (the key- or dash-line locator; the name predates YAML anchors) computes `head_end` after the `:` or `-`. If the replaced node has `anchor` and the anchor token lies on that line after the head, `head_end` moves to the anchor token's end. The new inline value or block lines then follow `&d`, as in `defaults: &d` with the new block below it, or `x: &m [a, b]` in flow. An anchor not on that line, as in `defaults:` with `&d` alone on the next line, → `WriteRefused` (exit 3), because moving it is not a byte-surgical change.
- `_replace_span` (scalars in place) already keeps the prefix before the scalar's span, and the span excludes the anchor (R-2), so `model: &m opus` → `model: &m sonnet` needs no change.

## R-10 — CLI

- `set --expand-alias` (`store_true`, help: "give an aliased value on PATH its own copy before setting it"). It combines with `--reason` and `--in-include`. `get`, `show`, `history` and `watch` do not define it, so argparse reports an unrecognised argument, a `UsageError` (exit 2), like `--in-include` (C10).
- `commands/set_value.run` passes `expand_alias` to `apply_set`; recording is unchanged.

## Tests (black-box first, real files and real CLI)

- **Integration, byte snapshots of every theatre file:**
  - US1 reads: `get`, `show`, `show --sources` and the load errors;
  - US2 anchor writes with history events per alias path;
  - US3 refusals: exit 3, empty stdout, stderr mentions `--expand-alias`, files and history unchanged;
  - US4 expansions: the worked example byte-for-byte; flow, scalar, list item and nested; C8 inner anchor and comment; C9 refusals; C10 exit 2; lineage with `--reason`.
- **Unit:** composer spans and refusals; the merge-key view (order, precedence, nested); expansion text.
- **Adjusted:** the step-1 test `test_anchors_aliases_and_tags_are_refused` becomes tag-only plus undefined and recursive aliases; the step-5 anchor/tag-on-include tests get the new messages.
