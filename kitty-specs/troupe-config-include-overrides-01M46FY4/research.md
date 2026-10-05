# Research & Decisions: troupe configuration: keep shared includes shared

Product-level out-of-contract choices are spec D-1…D-11. The decisions here are about how to implement them; the product owner confirmed them in the Engineering Alignment on 2026-10-05 (DM 01M46GE1PATR2GJF9SGQ9NAWQ1).

## R-1 — How a merged mapping is represented

- **Decision**: `MergedMapping` is a dataclass subclass of `MappingNode` with extra fields `base: Node`, `override: Node` (both kept as found, so an override that is itself an include, or a nested mapping-form include, is handled by the same rules) and `ref: YamlInclude | None` (set only at the top of a mapping-form include). Its `entries` are the merged view; `origin` is the override mapping's origin; `flow` is the base's (the view's shape for verification). `YamlInclude` and `TextInclude` gain `holder: MappingNode | None`, the mapping that holds them as `$ref` (None for scalar form).
- **Rationale**: every reader (`paths.walk`, `leaves.flatten`, `yamlout`, `values.scalar_of`, `_matches`) already handles `MappingNode`, so the merged view is correct for them without new branches; every scalar keeps its own `Origin`, so `show --sources` attributes overrides to the including file for free. Writers go through `placement.py`, which always resolves a merged mapping to one concrete side.
- **Alternatives considered**: a separate `RefInclude` node type (rejected: a new branch in ~8 modules); merging into plain `MappingNode`s without keeping sides (rejected: placement could not tell where a key lives).

## R-2 — Loader rules for `$ref` (one place: `merge.py` + `loader._mapping`)

- A raw mapping with a `$ref` key: its value must be a scalar whose string starts `file:`, else `LoadError` naming file and `<path>.$ref` (spec D-1). The include resolves like a scalar-form include (same relative-path, missing-target and cycle rules).
- No siblings → return the include node with `holder` set (YAML or text).
- Siblings → text target: `LoadError` (contract). YAML target whose unwrapped root is not a mapping: `LoadError` (D-7; an empty file is already an empty mapping). Otherwise convert the siblings as an ordinary mapping (they may contain includes, including mapping-form) and `deep_merge(unwrap(root), overrides)`.
- `deep_merge(base, override)`: for each base key in order, if the override has the key: if both unwrapped values are mappings → nested `MergedMapping(base=<base value as found>, override=<override value as found>, ref=None)`, else the override value; otherwise the base value. Then override-only keys in override order. Key/entry objects are reused, not copied.
- **Rationale**: one pure function holds the merge rule (TROUPE-007), the loader only recognises `$ref`.

## R-3 — Nearest include reference and the list rule

- **Decision** (refined while writing tasks; same behaviour as approved): for a new key under deepest existing ancestor D (`unwrap(found.nodes[-1])`):
  - **D is a `MergedMapping`** → the key goes to its override side (spec D-8): `_on_side(D.override, keys)`; with `--in-include`, to its base side via `_on_base(D.base, keys)`, which unwraps include chains and merged bases down to the innermost included mapping and adds the key there (as implemented in WP03). `_on_side(node, keys)`: plain `MappingNode` → `AddKeys(node, keys)`; `MergedMapping` → recurse into the same side; `YamlInclude` with `holder` → `AddKeys(holder, keys)` (or, with `--in-include`, recurse into its root); scalar-form `YamlInclude` → `ConvertInclude(include, keys)` (with `--in-include`, recurse into its root).
  - **D is concrete, `--in-include`** → `AddKeys(D, keys)` (step-1).
  - **D is concrete** → let F = `D.origin.file`. The *nearest include reference* R is the deepest `YamlInclude` on the route (depths 0…k, peeling include chains and looking at both sides of merged mappings) whose `target` is F. If there is none (F is the root file), or a `SequenceNode` lies on the route between R and D → `AddKeys(D, keys)` (step-1; "a new key inside a list item is written in the file that holds the list"). Otherwise, with `route` = the PATH segments from R down to D: R has a `holder` → `AddKeys(holder, route + keys)`; R is the `ref` of a top `MergedMapping` M → descend `M.override` along `route` through existing plain override mappings and `AddKeys` at the deepest one with the rest; else (scalar form) → `ConvertInclude(R, route + keys)`.
  - The concrete parent collection and slot of an existing node or of R (for `ReplaceScalar`, `ReplaceCollection`, `ConvertInclude`) is found by identity search over concrete sides (`concrete_parent(root, node)`), never from a merged view.
- **Rationale**: this is the contract text ("deepest existing ancestor comes from an included file … the file that contains the include reference"; "a new key inside a list item is written in the file that holds the list") with PO answer DM 01M46FYYFFXXZE893KWDP2WJCW for nesting.

## R-4 — Refusals in placement

- PATH with a `$ref` segment → `WriteRefused` before walking (D-6).
- Existing node is a `YamlInclude` (either form) or a `MergedMapping` with `ref` → `WriteRefused` (step-1 FR-013, unchanged meaning).
- Existing node is a `MergedMapping` without `ref` → `WriteRefused` (D-10).
- `ConvertInclude` whose include string spans lines → `WriteRefused` (D-11), decided in `convert_include_edits`.

## R-5 — Verification allowance

- **Decision**: in `apply._same_outside`, when `here` is a strict prefix of `target` (on the route), an old `YamlInclude` may be matched by a new `MergedMapping` whose `ref.target.path` equals the old target; comparison continues between `unwrap(old)` and the new merged view. Also on the route: a plain mapping of an included file may become a nested `MergedMapping` without `ref` whose base is that same mapping (same file and start offset; `_gains_override`, needed for US2-4). The added key may sit only where the merge rule puts it: at the very end of the view, or at the end of one of its nested base blocks (`_orders`, recursive since WP05 / bead c3z); old and new entries are paired by key, all old keys must remain and exactly one key is added. Off the route, kinds must match, a `MergedMapping` must have the same `ref` target (or both none), a plain mapping must not become merged, and an include must keep its form.
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

## R-9 — Post-merge `/spec-kitty.accept` run

- **Situation**: after delivery to `main` (`ded0223`) and the mission review (`b18a000`), `spec-kitty agent mission accept --mission troupe-config-include-overrides-01M46FY4` blocked for two reasons: it refuses to run on `main` (it must run on the mission or target branch), and the repository has no `docs/` directory (the software-dev path convention).
- **Decision** (same as the lineage mission's D-11; confirmed by the product owner with "Please continue"): change no code and add no files to the project. `feat/troupe-config-include-overrides` was fast-forwarded to `main`, acceptance was re-run there with `--lenient` (which relaxes only the `docs/` path-convention check), giving acceptance commit `bb6b119`, and `main` was fast-forwarded to it.
- **Rationale**: an empty `docs/` adds structure no one asked for (TROUPE-007/-008); forcing acceptance on `main` would hide the branch rule rather than satisfy it.
- **Evidence**: `git diff b18a000 b4fcfcd` touches only `kitty-specs/troupe-config-include-overrides-01M46FY4/meta.json`; the diff over `src tests pyproject.toml uv.lock` is empty, so the tested code is unchanged (1848 passed, mypy --strict and ruff clean). The pre-merge acceptance (`6f52139`) already recorded all 13 FR criteria as `pass` with test evidence.
