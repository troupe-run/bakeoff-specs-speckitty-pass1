# Research & Decisions: troupe configuration: keep shared includes shared

Product-level out-of-contract choices are spec D-1…D-11. The decisions here are about how to implement them; the product owner confirmed them in the Engineering Alignment on 2026-10-05 (DM 01M46GE1PATR2GJF9SGQ9NAWQ1).

## R-1 — How a merged mapping is represented

- **Decision**: `MergedMapping` is a dataclass subclass of `MappingNode` with extra fields `base: MappingNode`, `override: MappingNode` and `ref: YamlInclude | None` (set only at the top of a mapping-form include). Its `entries` are the merged view; `origin` is the override mapping's origin; `flow` is the base's (the view's shape for verification). `YamlInclude` and `TextInclude` gain `holder: MappingNode | None`, the mapping that holds them as `$ref` (None for scalar form).
- **Rationale**: every reader (`paths.walk`, `leaves.flatten`, `yamlout`, `values.scalar_of`, `_matches`) already handles `MappingNode`, so the merged view is correct for them without new branches; every scalar keeps its own `Origin`, so `show --sources` attributes overrides to the including file for free. Writers go through `placement.py`, which always resolves a merged mapping to one concrete side.
- **Alternatives considered**: a separate `RefInclude` node type (rejected: a new branch in ~8 modules); merging into plain `MappingNode`s without keeping sides (rejected: placement could not tell where a key lives).

## R-2 — Loader rules for `$ref` (one place: `merge.py` + `loader._mapping`)

- A raw mapping with a `$ref` key: its value must be a scalar whose string starts `file:`, else `LoadError` naming file and `<path>.$ref` (spec D-1). The include resolves like a scalar-form include (same relative-path, missing-target and cycle rules).
- No siblings → return the include node with `holder` set (YAML or text).
- Siblings → text target: `LoadError` (contract). YAML target whose unwrapped root is not a mapping: `LoadError` (D-7; an empty file is already an empty mapping). Otherwise convert the siblings as an ordinary mapping (they may contain includes, including mapping-form) and `deep_merge(unwrap(root), overrides)`.
- `deep_merge(base, override)`: for each base key in order, if the override has the key: if both unwrapped values are mappings → nested `MergedMapping(ref=None)`, else the override value; otherwise the base value. Then override-only keys in override order. Key/entry objects are reused, not copied.
- **Rationale**: one pure function holds the merge rule (TROUPE-007), the loader only recognises `$ref`.

## R-3 — Nearest include reference and the list rule

- **Decision**: `place` walks the found nodes from the root and remembers, for each step, the last include reference seen (a `YamlInclude`, or a `MergedMapping` with `ref`) and whether a `SequenceNode` has been passed since. For a new key under deepest existing ancestor D:
  - D is a `MergedMapping` → `AddKeys(D.override, keys)` (applied recursively if the override side itself is an include or merged mapping).
  - Else if there is an include reference R above D and no list between R and D → override at R: follow the route R→D through the override tree (R's holder or override mapping); the deepest existing override mapping gets `AddKeys(..., route_rest + keys)`; if R is a scalar-form include → `ConvertInclude(R, route + keys)`.
  - Else → `AddKeys(D, keys)` (step-1).
  - `--in-include` → step-1 on the merged view: D is a `MergedMapping` → recurse into `D.base` (innermost included side, spec D-8); else `AddKeys(D, keys)`.
- **Rationale**: this is the contract text ("deepest existing ancestor comes from an included file … the file that contains the include reference"; "a new key inside a list item is written in the file that holds the list") with PO answer DM 01M46FYYFFXXZE893KWDP2WJCW for nesting.

## R-4 — Refusals in placement

- PATH with a `$ref` segment → `WriteRefused` before walking (D-6).
- Existing node is a `YamlInclude` (either form) or a `MergedMapping` with `ref` → `WriteRefused` (step-1 FR-013, unchanged meaning).
- Existing node is a `MergedMapping` without `ref` → `WriteRefused` (D-10).
- `ConvertInclude` whose include string spans lines → `WriteRefused` (D-11), decided in `convert_include_edits`.

## R-5 — Verification allowance

- **Decision**: in `apply._same_outside`, when `here` is a strict prefix of `target` (on the route), an old `YamlInclude` may be matched by a new `MergedMapping` whose `ref.target.path` equals the old target; comparison continues between `unwrap(old)` and the new merged view. Off the route, kinds must match and a `MergedMapping` must have the same `ref` target (or both none).
- **Rationale**: the conversion is the only structural change a `set` may cause; everything else is still verified strictly, so a renderer bug is still a refusal, never a corrupted file.

## R-6 — CLI

- `set` gains `--in-include` (`action="store_true"`), passed to `apply_set(..., in_include=...)`. argparse already turns an unknown option on other subcommands into exit 2.

## R-7 — Conversion text (`collections.convert_include_edits`)

- Block parent: delete from the end of the key's `:` to the end of the include string (separator and value), keeping the bytes between value and `#` (D-5); insert after the key's line `$ref: <include bytes>` then the override lines rendered by the existing new-key renderer, both at key column + file indent step.
- Flow parent: replace the include string with `{$ref: <bytes>, k: v}` (nested flow mappings for intermediate keys) (D-3).
- List item: replace `- <bytes>` with `- $ref: <bytes>` and put the override lines at the item content column (D-4).
- Newlines match the file (`detect_newline`).

## R-8 — Tests

- Integration tests per spec scenario with byte snapshots of the whole theatre directory (except `history.sqlite`); unit tests for `deep_merge`, placement decisions and conversion edits.
- Updated by contract: `test_new_key_goes_into_included_files_mapping` and `test_new_key_into_empty_included_file` (`tests/integration/test_set_new_entries.py`) now expect overrides in the including file; their `--in-include` variants keep the step-1 expectation.
