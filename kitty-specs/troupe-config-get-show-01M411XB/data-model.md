# Data Model: troupe-config-get-show

No persisted data changes. The new model is the in-memory rendering of a loaded tree (`troupe.tree.Node`).

## Line

| Field | Type | Meaning |
|---|---|---|
| `text` | `str` | One output line without its line break |
| `source` | `Path \| None` | The file whose scalar this line holds (set for flow-scalar lines and literal-block header lines); `None` for collection-opening lines, `{}`/`[]` lines and block body lines |

`to_text(lines, sources_root: Path | None)` joins lines with `\n` and adds a final `\n`. When `sources_root` is given, it appends ` # from <source_label(source, sources_root)>` to every line whose `source` is set.

**Invariant**: removing the comments from the `--sources` output gives exactly the plain output. Both outputs come from the same `Line` list.

## Rendering rules (node → lines), indentation `n`

| Node (after `unwrap`) | Position | Lines |
|---|---|---|
| ScalarNode / TextInclude (one-line) | after `key: ` / `- ` / root | `…value` (source = node file / include target) |
| String with `\n` (or text include, see D-2), `can_block` | same | header `…\|[2][-+]` (source set), body via `literal_lines(value, n+2)` |
| String failing `can_block` | same | double-quoted flow scalar (source set) |
| MappingNode, non-empty | value of `key` | `key:` then entries at `n+2` |
| SequenceNode, non-empty | value of `key` | `key:` then items `- …` at `n+2` |
| MappingNode, non-empty | list item | `- ` + first entry inline; other entries at item column + 2 |
| SequenceNode, non-empty | list item | `- ` + first item inline (`- - a`); others at item column + 2 |
| Empty mapping / list | anywhere | `{}` / `[]` inline (no source) |
| Root mapping / list | PATH omitted or PATH names one | entries/items at column 0 |

The source of a scalar is `ScalarNode.origin.file.path`, or `TextInclude.target.path` for a text include. A `YamlInclude` is transparent: its content's nodes carry the included file.

## Key rendering

Keys are written with `choose_style(key, None, "block")`, followed by the key round-trip check (D-5).
