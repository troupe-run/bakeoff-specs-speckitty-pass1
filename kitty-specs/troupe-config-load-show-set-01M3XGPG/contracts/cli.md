# CLI Contract: `troupe config`

Run from the repository root as `uv run troupe config <subcommand> [--theatre DIR] [ARGS]`.
`--theatre` defaults to the current working directory. Source of truth for behaviour: spec.md
FR-001…FR-024 (contract sections General; Includes; show PATH; set PATH VALUE; history [PATH]).

| Subcommand | Arguments | Success (exit 0) stdout |
|---|---|---|
| `show PATH` | dotted path | scalar printed per FR-005 |
| `set PATH VALUE` | dotted path; VALUE = one YAML 1.2 core flow node | empty |
| `history [PATH]` | optional dotted path prefix | JSON Lines, oldest first (schema: `history-event.schema.json`) |

## Exit codes

| Code | Meaning | Examples |
|---|---|---|
| 0 | success | |
| 2 | usage error | missing PATH/VALUE, unknown subcommand, unparsable VALUE |
| 3 | write refused, no file changed | replacing a whole include; non-string VALUE for a CRLF text include; more-indented line in a folded value |
| 4 | configuration cannot be loaded | no root file, both `troupe.yml` and `troupe.yaml`, invalid YAML, missing include target, include cycle |
| 5 | path not found / wrong kind of node | unknown key, out-of-range index (> length for set), `show` on a mapping or list, path through a scalar |

On any non-zero exit: stdout is empty; stderr is one line `troupe: <message>` naming the offending
path or file.

## Scalar printing (`show`)

| Value | Printed |
|---|---|
| string `s` | `s` + `\n` unless `s` ends with `\n` |
| bool | `true` / `false` |
| null | `null` |
| int | decimal |
| float | Python `repr()` |

## Files touched

- `set` may modify exactly the file(s) the write-back rules require (atomic replace).
- All commands may create/modify only `<theatre>/.troupe/history.sqlite` and its SQLite side files.
