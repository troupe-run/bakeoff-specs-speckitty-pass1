# CLI contract as delivered: Aliases (step 6)

Contract text (verbatim from the product owner, step 6):

- Setting a path whose value is defined at an anchor (`&name`) changes it at the anchor, and so everywhere the alias is used.
- Setting a path reached **through an alias** (`*name`) → exit 3; stderr mentions `--expand-alias`.
- `set --expand-alias PATH VALUE` replaces that alias with a block-style copy of the anchored node, puts the end-of-line comment `# expanded from *<name> by troupe` on the key's line (two spaces before `#`), and then sets the value in the copy. Nothing else changes; other aliases still refer to the anchor.
- Merge keys (`<<`) are never written.

## Command surface

```
troupe config set [--reason TEXT] [--in-include] [--expand-alias] PATH VALUE
```

| Exit | Meaning |
|---|---|
| 0 | Value set (or already equal: nothing written, nothing recorded). |
| 2 | Usage error: including `--expand-alias` on `get`/`show`/`history`/`watch` (C10), and an anchor, alias or tag in VALUE (C14). |
| 3 | Refused, no file changed: through an alias without `--expand-alias`; through `<<`, a new `<<` key, replacing a mapping holding `<<`, a copy containing `<<` (A-0); expansion impossible (C9: flow parent, comment on the alias line, alias off its key line, `\|+` copy, redefined anchor in copy, expansion and key in different files); anchor not on key line on replacement (C5, R-9). |
| 4 | Configuration not loadable: tags (C2), anchors on includes or keys (C3), undefined/recursive alias, bad `<<` value, `<<` beside `$ref` (C13). |
| 5 | Path errors, unchanged from step 1. |

## Agent choices (spec A-0, C1–C14)

See [spec.md](../spec.md) "Agent choices" for each choice with its reason. In short:

- A-0: `<<` is read with YAML merge semantics, and is never written through.
- C1: reads are resolved.
- C2: tags are refused.
- C3: anchors and aliases may not touch includes or keys.
- C4: a scalar alias counts as an alias.
- C5: the anchor is kept on replacement.
- C6: new keys follow the same rule.
- C7: nested aliases are expanded outermost first.
- C8: what goes in the copy.
- C9: where the comment goes, and when expansion is refused.
- C10: the flag's scope.
- C11: history has one event per changed resolved leaf.
- C12: earlier behaviour is kept.
- C13: `<<` beside `$ref` makes the file unloadable.
- C14: no anchors or aliases in VALUE.

## Messages (stderr, one line, `troupe: ` prefix)

- Through an alias: `<PATH>: <prefix> is the alias *<name> in <file> line <n>, shared with its anchor &<name>; refusing to change it for every user (use --expand-alias to give this path its own copy); no file changed`
- Through a merge key: `<PATH>: <prefix> comes through the merge key '<<' (from *<name>); refusing to change a shared value (use --expand-alias to give it its own copy); no file changed`
- Through a merge key with `--expand-alias`: `<PATH>: <prefix> comes through the merge key '<<' (from *<name>); merge keys are never written, so it cannot be expanded; no file changed`
- Expansion refusals name PATH, `*<name>`, the file and line, and the reason (flow collection / existing comment / alias not on its key's line).
- New key named `<<`: `<PATH>: '<<' is the merge key; troupe never writes merge keys; no file changed`
- Replacing a mapping holding `<<`: `<PATH>: this mapping uses the merge key '<<'; replacing it as a whole would rewrite the merge key, which troupe never writes; no file changed`
- Copy containing `<<`: `<PATH>: the alias *<name> at <file> line <n> refers to a value that uses the merge key '<<'; copying it would write a merge key, which troupe never does; no file changed`
- Anchor off its key line on replacement: `<PATH>: the anchor &<name> of this value is not on its key's line; replacing the value would move it; no file changed`
- Expansion and new key in different files: `<PATH>: the alias *<name> is expanded in <file>, but the new key would be written as an override in <file>; an expansion and its set are one write of one file (use --in-include to add it to the copy); no file changed`
- An alias, anchor or tag in VALUE exits 2; a lone alias reports YAML's own `found undefined alias '<name>'`, an anchor or tag `anchors and tags are not supported`.
