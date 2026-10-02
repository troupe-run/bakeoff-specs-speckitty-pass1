# Decision Moment `01M3XGX935C4759B9DMK0BXXKT`

- **Mission:** `troupe-config-load-show-set-01M3XGPG`
- **Origin flow:** `plan`
- **Slot key:** `plan.persistence.event-store`
- **Input key:** `event_store_backend`
- **Status:** `resolved`
- **Created:** `2026-10-02T05:20:35.941905+00:00`
- **Resolved:** `2026-10-02T05:21:09.542801+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

How should the eventsourcing history be persisted under .troupe/: (A) eventsourcing's built-in SQLite persistence module, one database file .troupe/history.sqlite, one aggregate per theatre; (B) eventsourcing POPO/in-memory recorder serialized to a JSON file; (C) other?

## Options

- A: built-in SQLite at .troupe/history.sqlite (recommended)
- B: custom JSON-file recorder
- Other

## Final answer

A: eventsourcing built-in SQLite persistence at <theatre>/.troupe/history.sqlite, one aggregate per theatre; all temp files (-journal/-wal) stay under .troupe/; seq = position in the event log.

## Rationale

_(none)_

## Change log

- `2026-10-02T05:20:35.941905+00:00` — opened
- `2026-10-02T05:21:09.542801+00:00` — resolved (final_answer="A: eventsourcing built-in SQLite persistence at <theatre>/.troupe/history.sqlite, one aggregate per theatre; all temp files (-journal/-wal) stay under .troupe/; seq = position in the event log.")
