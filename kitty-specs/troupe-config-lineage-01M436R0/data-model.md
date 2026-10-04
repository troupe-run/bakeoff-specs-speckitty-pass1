# Data Model: troupe configuration: lineage

## Actor (value object, `troupe.lineage`)

| Field | Type | Rule |
|---|---|---|
| `kind` | `"human" \| "agent" \| "unknown"` | `unknown` only for import and file events |
| `id` | `str \| None` | non-empty for `TROUPE_ACTOR`; the login name or `None` when unset; always `None` for `unknown` |

Sources:
- `TROUPE_ACTOR=human:<id>` gives `Actor("human", id)`.
- `TROUPE_ACTOR=agent:<id>` gives `Actor("agent", id)`. The id is everything after the first `:`, kept verbatim, and must be non-empty.
- When `TROUPE_ACTOR` is unset, the actor is `Actor("human", login name or None)`.
- Any other value raises `UsageError`, which exits 2.
- Import and file events use `UNKNOWN = Actor("unknown", None)`.

## Lineage (value object, `troupe.lineage`)

| Field | Type | Import | File reconcile | CLI command | Pre-lineage event (read-time) |
|---|---|---|---|---|---|
| `actor` | `Actor` | `UNKNOWN` | `UNKNOWN` | from `TROUPE_ACTOR` / login | `UNKNOWN` |
| `via` | `"import" \| "cli" \| "file" \| None` | `"import"` | `"file"` | `"cli"` | `"import"` for import ops, else `None` |
| `at` | `str` (RFC 3339, UTC, `Z`) | one clock read | one clock read | one clock read, after the write | stored event timestamp → UTC |
| `reason` | `str \| None` | `None` | `None` | `--reason` text or `None` | `None` |
| `change` | `str` | new UUID4 | new UUID4 | new UUID4 | `pre-lineage-<seq>` |

`at` format: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (e.g. `2026-10-04T10:18:24.017202Z`).

## History event, version 2 (`troupe.history.ConfigHistory`)

Topics unchanged: `troupe.history:ConfigHistory.LeafImported`, `.LeafSet`, `.LeafRemoved`, plus the `Created` event.

| Event | Existing fields | Added fields (v2) |
|---|---|---|
| `LeafImported` | `path`, `new` | `actor_kind`, `actor_id`, `via`, `at`, `reason`, `change` |
| `LeafSet` | `path`, `old`, `new` | same |
| `LeafRemoved` | `path`, `old` | same |

`upcast_v1_v2(state)` on each class adds the added fields to decoded v1 state, using the "Pre-lineage event" column above. `seq = originator_version - 1`.

## HistoryRecord (read model)

`seq, op, path, old, new` as in step 1, plus `lineage: Lineage`. It is rendered as one JSON line, with keys in this order: `seq, op, path, old, new, actor{kind,id}, via, at, reason, change`.

## Invariants

1. **One producer, one change.** All events saved by one `HistoryStore.import_leaves` or `record` call share one `Lineage`, and therefore share `change`, `at`, `actor`, `via` and `reason`. Each call gets a lineage created for it alone.
2. **Atomicity.** One call is one `save()`, so a change is stored entirely or not at all.
3. **Producers within one command.** The command may produce three changes: the import (if never imported), then the reconcile (if asked and there are differences), then the command's own change (only `set`, only after a successful write, only if it changed something). Each one has a distinct `change`.
4. **No stored rewrite.** Version-1 rows stay version-1 on disk; they are upgraded only in memory when read.
5. **Unknown is explicit.** Import, file and pre-lineage events never carry a named actor.
6. **Actor check precedes everything.** An invalid `TROUPE_ACTOR` exits before the theatre is located, so no lock, load, import, reconcile, write or record happens.
