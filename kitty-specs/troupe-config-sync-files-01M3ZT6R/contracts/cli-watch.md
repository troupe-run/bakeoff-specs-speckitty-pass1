# CLI Contract additions: `troupe config watch` and reconcile-first

Extends `kitty-specs/troupe-config-load-show-set-01M3XGPG/contracts/cli.md`. Exit codes, the error
line format (`troupe: <message>`) and the history event schema are unchanged.

| Subcommand | Arguments | Reconciles first? | Success stdout |
|---|---|---|---|
| `show PATH` | dotted path | yes | scalar |
| `set PATH VALUE` | dotted path, VALUE | yes (then its own events) | empty |
| `history [PATH]` | optional path prefix | **never** (imports if never imported) | JSON Lines |
| `watch` | none | yes, at start and on every change | exactly `watching <dir>\n`, flushed |

## `watch`

```
uv run troupe config watch [--theatre DIR]
```

| Situation | Behaviour |
|---|---|
| Configuration loads at start | import if needed → reconcile → baseline → print `watching <dir>` + flush |
| Configuration cannot load at start | exit 4, stdout empty, stderr `troupe: <message naming file>` |
| Extra argument | exit 2 |
| Change to the root file or any included file after the line | reconciled within 2 s |
| Change that leaves every leaf the same (format/comment-only) | nothing recorded |
| Change that makes the configuration unloadable | keep running; one stderr line naming the file; nothing recorded; repeated only if the message changes |
| Configuration loadable again | reconcile within 2 s |
| `set` run while watching | only the `set`'s own events are recorded |
| SIGINT or SIGTERM | finish any in-progress reconcile, exit 0, nothing more on stdout |

`<dir>`: the `--theatre` value verbatim. Without `--theatre`, the `$TROUPE_THEATRE` value verbatim,
else the current directory (`os.getcwd()`) (FR-009, D-8).

## Reconcile events

These are ordinary history events (`op` is `set` or `remove`), shaped exactly like those a `set`
command records. Within one reconcile, `set` events come first in the files' document order,
followed by `remove` events in recorded order.

## Files touched

- Reconcile and `watch` create or modify only `<theatre>/.troupe/history.sqlite` and its SQLite side files. They never touch configuration files.
- The theatre lock is an advisory lock on the `.troupe` directory and creates no file.
