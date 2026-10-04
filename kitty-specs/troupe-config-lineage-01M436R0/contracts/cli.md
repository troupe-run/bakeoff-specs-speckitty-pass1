# CLI contract delta: Lineage (step 4)

This file adds to the CLI contracts of steps 1–3. Everything not mentioned here is unchanged. It implements the contract's **Lineage** section as written. Behaviour marked *out of contract* is a choice recorded in [../spec.md](../spec.md), not an amendment to the contract.

## `TROUPE_ACTOR` (every `troupe config` command)

| Value | Actor of the command's own events |
|---|---|
| unset | `{"kind": "human", "id": <login name>}`; `id` is `null` if no login name can be determined *(out of contract: DM 01M436TX68S2MGE4DN9AM02KTJ)* |
| `human:<id>` (id non-empty; everything after the first `:`) | `{"kind": "human", "id": "<id>"}` |
| `agent:<id>` (id non-empty) | `{"kind": "agent", "id": "<id>"}` |
| anything else (including empty, `human:`, `agent:`, `Human:x`, `robot:x`, `alice`) | exit **2**, stdout empty, one stderr line: `troupe: TROUPE_ACTOR: invalid value '<value>': expected 'human:<id>' or 'agent:<id>'` |

The variable is checked after the arguments are parsed and before the theatre is located or loaded. An invalid value therefore exits 2 even when the configuration is missing or broken, and nothing is recorded *(out of contract: DM 01M436TPQDWVSZQYFD6D5343DC)*.

## `troupe config set PATH VALUE [--reason TEXT]`

- `--reason TEXT` sets `reason` on every event this `set` records itself, stored exactly as given (`""` stays `""`).
- Without `--reason`, `reason` is `null`.
- `--reason` on any other command is a usage error (exit 2).
- A `set` that changes nothing, is refused (exit 3) or fails on a path (exit 5) records none of its own events. A reconcile it ran first is kept as its own change.

## `troupe config history [PATH]` — line format

One JSON object per line, oldest first, with keys in this order:

```
seq, op, path, old, new, actor, via, at, reason, change
```

```json
{"seq": 4, "op": "set", "path": "limits.max", "old": 5, "new": 10, "actor": {"kind": "agent", "id": "planner"}, "via": "cli", "at": "2026-10-04T10:18:24.017202Z", "reason": "raise limit", "change": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed"}
```

| Producer | actor | via | reason | change |
|---|---|---|---|---|
| import (first command in a theatre) | `{"kind":"unknown","id":null}` | `"import"` | `null` | one id for the whole import |
| file reconcile (before any command except `history`; each `watch` reconcile) | `{"kind":"unknown","id":null}` | `"file"` | `null` | one id per reconcile |
| `set` (its own events) | from `TROUPE_ACTOR` | `"cli"` | `--reason` or `null` | one id per command |

`at` is RFC 3339 UTC ending in `Z`, with microseconds. All events of one change share it.

### Events recorded before step 4 *(out of contract: DM 01M436RBNQT22F9AM54QER2FT9)*

| Field | Value |
|---|---|
| `actor` | `{"kind": "unknown", "id": null}` |
| `via` | `"import"` for `op: "import"`; `null` for `set`/`remove` (cannot be determined) |
| `at` | the event's stored recording time, in UTC |
| `reason` | `null` |
| `change` | `"pre-lineage-<seq>"`, unique per event |

The stored history is never rewritten.

Schema: [history-event.schema.json](history-event.schema.json).
