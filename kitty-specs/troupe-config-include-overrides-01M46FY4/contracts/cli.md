# CLI Contract additions: step 5 (Overrides, In-include)

Run as `uv run troupe config <subcommand> [--theatre DIR] [ARGS]`. All step 1–4 sections stay in force except rule 2 under `set PATH VALUE`, replaced by Overrides. Source of truth: spec.md FR-001…FR-013 and D-1…D-11.

## Includes: mapping form

```yaml
coder:
  $ref: file:agents/coder.yaml   # the include string
  temperature: 0.3               # overrides, deep-merged over the included content
```

- Mappings merge recursively; scalars and lists in the override replace. Keys: included first, then override-only.
- `$ref` alone behaves exactly like the scalar form (YAML or text target).
- `get`/`show` never show `$ref`; `show --sources` names the including file for override scalars.

## `set PATH VALUE [--reason TEXT] [--in-include]`

| Case | Written to |
|---|---|
| Existing scalar, overridden | the override (including file) |
| Existing scalar, not overridden | the file it comes from |
| New key, deepest existing ancestor from an included file | override in the file holding the nearest include reference (scalar form converted first) |
| New key, same, with `--in-include` | the included file (innermost that defines the ancestor) |
| New key inside a list item; list append | the file holding the list |
| New key, ancestor not from an include | that file (unchanged) |

Conversion: `coder: file:agents/coder.yaml  # c` → `coder:  # c` / `  $ref: file:agents/coder.yaml` / `  temperature: 0.3` (file indentation; flow parent → `{$ref: …, k: v}`; list item → `- $ref: …` with overrides at the item column).

## Exit codes (additions)

| Code | Cases |
|---|---|
| 2 | `--in-include` on any subcommand other than `set` |
| 3 | PATH with a `$ref` segment (D-6); replacing a partly overridden mapping (D-10); conversion of a multi-line include string (D-11); replacing a whole include of either form (unchanged) |
| 4 | `$ref` value not a `file:` string (D-1); mapping-form include with siblings of a non-YAML target (contract) or of YAML content that is not a mapping (D-7) |

On any non-zero exit stdout is empty, stderr is one line `troupe: <message>` naming the path or file, and no file changes.
