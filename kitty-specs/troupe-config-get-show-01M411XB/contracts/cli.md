# CLI Contract: `troupe config` (step 3)

Run as `uv run troupe config <subcommand> [--theatre DIR] [ARGS]`. The theatre defaults to `$TROUPE_THEATRE`, else the current directory. This contract replaces the step-1 *show PATH* section. All other step-1/2 sections stay in force: General, Includes, set, history, watch, and the reconcile-first rule.

| Subcommand | Arguments | Success (exit 0) stdout |
|---|---|---|
| `get PATH` | dotted path | the scalar, printed per *Scalar printing* |
| `show [PATH] [--sources]` | optional dotted path | a scalar printed per *Scalar printing*; otherwise YAML per *YAML output* (whole configuration when PATH is omitted) |
| `set PATH VALUE` | unchanged | empty |
| `history [PATH]` | unchanged | JSON Lines |
| `watch` | unchanged | `watching <dir>` |

`get` and `show` reconcile first and never modify a configuration or include file.

## Exit codes (additions to step 1)

| Code | `get` / `show` cases |
|---|---|
| 2 | `get` without PATH; empty path segment; `get … --sources` (unknown option) |
| 4 | configuration cannot be loaded (unchanged) |
| 5 | path not found; path through a scalar; **`get` on a mapping or list**. The stderr line is `troupe: <path> is a mapping, not a scalar; use 'troupe config show <path>'` (or `list`) |

On any non-zero exit, stdout is empty and stderr is one line, `troupe: <message>`.

## Scalar printing (`get`; `show` on a scalar without `--sources`)

This is unchanged from step 1. A string `s` prints as `s` plus `\n` unless it already ends with `\n`. A text include prints its file's exact text. Other values print as `true`/`false`, `null`, a decimal integer, or the float's Python `repr()`.

## YAML output (`show` on a mapping or list, PATH omitted, or `--sources`)

- Block style, 2-space indentation, keys and items in file order, no `---`, final `\n`.
- `key:` then nested entries at +2. A list under a key: `key:` then `  - item`.
- A list item that is a mapping is compact: `- k: v`, with its other keys at the item column + 2. A list inside a list: `- - a`.
- Empty mapping is `{}`; empty list is `[]`.
- Scalars:
  - `true`/`false`, `null`, decimal integers;
  - floats as `repr()`, except `.inf`, `-.inf` and `.nan`;
  - strings plain when they read back identically, else single-quoted, else double-quoted. Keys follow the same rule.
- Text includes, and other strings containing a line break, are literal blocks:
  - `|`, `|-` or `|+` chosen so the text reads back exactly;
  - an indentation digit when the first line starts with a space;
  - the body indented 2 beyond the key or item.
- Text a literal block cannot hold exactly (e.g. CR from CRLF files, control characters) is double-quoted with escapes.
- Includes are resolved. A YAML include's content appears in place, and a text include's value is its file's text.

## `--sources`

The output is the same YAML, plus ` # from <file>` at the end of every line that holds a scalar:

- `key: value`, `- value`, `- key: value`, a bare root scalar;
- the header line of a literal block (`key: | # from …`). Body lines never get a comment.

Lines that only open a collection (`key:`, `- key:` with a nested value) and `{}`/`[]` lines get no comment.

`<file>` is the file the scalar's bytes are in: for a text include, the included file. It is relative to the theatre directory, with `/` separators, and `../` when the file lies outside the theatre directory.

`show PATH --sources` on a scalar prints that scalar as YAML with its comment, e.g. `8080 # from .troupe/troupe.yml` (decision DM 01M411YHFR2PMJEJWMHX4KN9C4).

## Example

`.troupe/troupe.yml`:
```yaml
name: demo
server: file:server.yml
tools: [a, b]
prompt: file:prompts/sys.md
```
`.troupe/server.yml`: `port: 8080`. `.troupe/prompts/sys.md`: `Be brief.\n`.

`troupe config show --sources`:
```yaml
name: demo # from .troupe/troupe.yml
server:
  port: 8080 # from .troupe/server.yml
tools:
  - a # from .troupe/troupe.yml
  - b # from .troupe/troupe.yml
prompt: | # from .troupe/prompts/sys.md
  Be brief.
```
