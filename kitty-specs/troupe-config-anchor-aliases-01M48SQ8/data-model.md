# Data Model: anchors and aliases stay honest

## Raw nodes (`troupe/yamlcore.py`)

| Type | Fields | Notes |
|---|---|---|
| `RawAnchor` | `name`, `start`, `end` | Span of the `&name` token. |
| `RawScalar` / `RawMapping` / `RawSequence` | + `anchor: RawAnchor \| None = None` | `start` is the content start, never the `&` (R-2). |
| `RawAlias` | `name`, `start`, `end`, `target: RawNode` | Span of `*name`; `target` is the most recent anchored raw node of that name. |

`RawNode = RawScalar | RawMapping | RawSequence | RawAlias`.

## Tree nodes (`troupe/tree.py`)

| Type | Fields | Invariants |
|---|---|---|
| `Anchor` | `name`, `origin` (span of `&name`), `path: tuple[str, ...]` | `path` is where the anchored node is loaded in the merged configuration. |
| `ScalarNode` / `MappingNode` / `SequenceNode` | + `anchor: Anchor \| None = None` | An anchored node is one object, shared by every `AliasNode` referring to it. |
| `AliasNode` | `origin`, `name`, `target: Node`, `anchored: Node \| None`, `merge: bool`, `written: AliasNode \| None` | Transparent to readers (`paths.unwrap`). Never a concrete container (placement does not look inside). A written alias has `merge=False`, `written=None`, `target is anchored`. A merge-derived alias has `merge=True`; it is never expanded. |
| `MergeKeyMapping(MappingNode)` | + `written: MappingNode` | `entries` is the view: written entries, with the `<<` entry replaced in place by unshadowed merged-in entries (values wrapped as merge-derived `AliasNode`). Writers receive only `written`. |

## Placements (`troupe/writeback/placement.py`)

| Placement | Fields | When |
|---|---|---|
| `ExpandAlias` | `alias: AliasNode` (written), `parent: Collection`, `slot: str \| int` | `--expand-alias` and the first alias on the route (or on the write side) is a written alias. |
| (existing) `ReplaceScalar`, `ReplaceCollection`, `AddKeys`, `AppendItem`, `ConvertInclude`, `ReplaceText` | unchanged | Only for routes without aliases; parents are concrete (`written` for merge-key views). |

## Load errors (exit 4)

| Condition | Choice |
|---|---|
| Tag on any node | C2 |
| Anchor on an include reference or on a node containing one | C3 |
| Anchored mapping key, or alias as a key | C3 |
| Undefined alias; recursive alias | FR-002 |
| `<<` value not a mapping, an alias of one, or a list of those | A-0 |
| `<<` beside `$ref` | C13 |

## Write refusals (exit 3, no file changes, no events)

| Condition | Choice |
|---|---|
| Route (or write side) goes through a written alias, no `--expand-alias` | contract; stderr mentions `--expand-alias` |
| Route goes through `<<` (with or without `--expand-alias`) | A-0 |
| Alias to expand in a flow collection; alias line has an end-of-line comment; alias not on its key/dash line | C9 |
| Replacing an anchored collection whose anchor is not on the key's line | R-9 |

## State and events

No new event types. A successful `set` records one `LeafSet` per resolved leaf whose value changed (C11), with the `set`'s lineage. Refusals record nothing of their own; reconcile events saved before a refusal stay saved, as in step 2.
