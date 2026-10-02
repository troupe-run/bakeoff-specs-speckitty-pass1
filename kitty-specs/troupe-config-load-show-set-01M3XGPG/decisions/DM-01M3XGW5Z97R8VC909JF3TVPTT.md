# Decision Moment `01M3XGW5Z97R8VC909JF3TVPTT`

- **Mission:** `troupe-config-load-show-set-01M3XGPG`
- **Origin flow:** `plan`
- **Slot key:** `plan.architecture.writeback-strategy`
- **Input key:** `writeback_strategy`
- **Status:** `resolved`
- **Created:** `2026-10-02T05:19:59.977158+00:00`
- **Resolved:** `2026-10-02T05:20:32.889877+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

How should set write changes back: (A) parse to locate node byte/character spans, then splice only the new text into the original file text (never re-serialize the document), or (B) ruamel.yaml round-trip load/modify/dump?

## Options

- A: span-locating parse + text splice (recommended)
- B: ruamel.yaml round-trip dump
- Other

## Final answer

A: locate node spans with a parser and splice only the replacement text into the original file text; never re-serialize; atomic temp+rename write. Any technique is acceptable if it guarantees byte-surgical write-back; round-trip dumps are rejected.

## Rationale

_(none)_

## Change log

- `2026-10-02T05:19:59.977158+00:00` — opened
- `2026-10-02T05:20:32.889877+00:00` — resolved (final_answer="A: locate node spans with a parser and splice only the replacement text into the original file text; never re-serialize; atomic temp+rename write. Any technique is acceptable if it guarantees byte-surgical write-back; round-trip dumps are rejected.")
