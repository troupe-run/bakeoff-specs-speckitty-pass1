# Data Model: keep shared includes shared

## Tree nodes (`troupe/tree.py`)

| Node | New / changed fields | Meaning |
|---|---|---|
| `YamlInclude` | `holder: MappingNode \| None` | The mapping that holds this include as `$ref` (mapping form without overrides); `None` for scalar form. |
| `TextInclude` | `holder: MappingNode \| None` | Same; a text include never has overrides. |
| `MergedMapping(MappingNode)` | `base: MappingNode`, `override: MappingNode`, `ref: YamlInclude \| None` | Merged view: `entries` = base keys in base order (value from override where present, nested `MergedMapping` where both are mappings) then override-only keys. `ref` set only at the top of a mapping-form include; `override` is then the holder mapping (its `$ref` entry excluded from `entries`). |

Invariants:

- No `$ref` key appears in any merged view (`entries`) or flattened leaf path.
- Every `ScalarNode`/`TextInclude` in the view keeps its own `Origin` (its source file).
- A `MergedMapping` is never written through directly: placements only carry concrete `MappingNode`/`SequenceNode`s.

## Placements (`troupe/writeback/placement.py`)

| Placement | When | File written |
|---|---|---|
| `ReplaceScalar` / `ReplaceText` / `ReplaceCollection` | existing value (one-sided) | the file holding it |
| `AppendItem` | index = list length | the list's file |
| `AddKeys(mapping, keys)` | new key: step-1, `--in-include`, or existing override mapping | `mapping.origin.file` |
| `ConvertInclude(include, keys)` (NEW) | new key at a scalar-form include reference | the including file |
| refusal (exit 3) | whole include; `MergedMapping` with or without `ref`; `$ref` segment; multi-line include string | none |

## Load errors (exit 4)

- `$ref` value not a `file:` string (D-1).
- Mapping-form include with siblings and a non-YAML target (contract).
- Mapping-form include with siblings and YAML content that is not a mapping (D-7).
- Missing target / cycle (step 1, both forms).
