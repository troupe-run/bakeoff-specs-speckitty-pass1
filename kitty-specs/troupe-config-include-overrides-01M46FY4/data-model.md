# Data Model: keep shared includes shared

## Tree nodes (`troupe/tree.py`)

| Node | New / changed fields | Meaning |
|---|---|---|
| `YamlInclude` | `holder: MappingNode \| None` | The mapping that holds this include as its `$ref` value (mapping form, with or without overrides; for a merged include it is the merged view's `override`); `None` for scalar form. Excluded from equality and repr (the holder's `$ref` entry points back at the include). |
| `TextInclude` | `holder: MappingNode \| None` | Same; a text include never has overrides. |
| `MergedMapping(MappingNode)` | `base: Node`, `override: Node`, `ref: YamlInclude \| None` | Merged view. `base` and `override` are kept **as found** (each may be a `YamlInclude`, a `MergedMapping` or a plain `MappingNode`); `entries` = keys of `unwrap(base)` in order (value from `unwrap(override)` where present, nested `MergedMapping` where both values unwrap to mappings) then override-only keys. `ref` is set only at the top of a mapping-form include; `override` is then the holder mapping, whose `$ref` entry is excluded from `entries`. |

Invariants:

- No `$ref` key appears in any merged view (`entries`) or flattened leaf path.
- Every `ScalarNode`/`TextInclude` in the view keeps its own `Origin` (its source file).
- A `MergedMapping` is never written through directly: placements only carry concrete `MappingNode`/`SequenceNode`s. The concrete parent of an existing node is found by identity in the tree's concrete sides (`placement.concrete_parent`), never taken from a merged view.
- The include reference of a concrete mapping D is the `YamlInclude` on PATH's route (including base/override sides of merged mappings, include chains peeled) whose `target` is `D.origin.file`; the deepest such one is the *nearest*.

## Placements (`troupe/writeback/placement.py`)

| Placement | When | File written |
|---|---|---|
| `ReplaceScalar` / `ReplaceText` / `ReplaceCollection` | existing value (one-sided) | the file holding it |
| `AppendItem` | index = list length | the list's file |
| `AddKeys(mapping, keys)` | new key: step-1, `--in-include`, or existing override mapping | `mapping.origin.file` |
| `ConvertInclude(include, parent, slot, keys)` (NEW; `parent=None` when the include is the whole document) | new key at a scalar-form include reference | the including file |
| refusal (exit 3) | whole include; `MergedMapping` with or without `ref`; `$ref` segment; multi-line include string | none |

## Load errors (exit 4)

- `$ref` value not a `file:` string (D-1).
- Mapping-form include with siblings and a non-YAML target (contract).
- Mapping-form include with siblings and YAML content that is not a mapping (D-7).
- Missing target / cycle (step 1, both forms).
