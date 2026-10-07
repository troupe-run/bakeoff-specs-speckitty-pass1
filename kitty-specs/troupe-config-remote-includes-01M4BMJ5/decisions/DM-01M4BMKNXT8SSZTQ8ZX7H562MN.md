# Decision Moment `01M4BMKNXT8SSZTQ8ZX7H562MN`

- **Mission:** `troupe-config-remote-includes-01M4BMJ5`
- **Origin flow:** `specify`
- **Slot key:** `specify.remote.relative-includes`
- **Input key:** `remote_relative_includes`
- **Status:** `resolved`
- **Created:** `2026-10-07T16:54:37.754160+00:00`
- **Resolved:** `2026-10-07T16:55:09.914384+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

A remote YAML include (https://…/team.yaml) itself contains include strings — file:x.yaml, or another https:// URL. What do they mean?

## Options

- file: resolves against the remote URL (fetched from the same server); nested https:// includes allowed; a URL cycle exits 4
- Remote files may contain https:// includes but a file: include in remote content exits 4
- Remote files may contain no includes at all (any include string in remote content exits 4)
- Other

## Final answer

Agent choice (out of contract, product owner 2026-10-07): option A — a file: include inside fetched content resolves against the remote URL (RFC 3986) and is fetched; nested https:// and http:// includes are allowed; a URL cycle exits 4; everything reached through a remote include is remote and read-only.

## Rationale

_(none)_

## Change log

- `2026-10-07T16:54:37.754160+00:00` — opened
- `2026-10-07T16:55:09.914384+00:00` — resolved (final_answer="Agent choice (out of contract, product owner 2026-10-07): option A — a file: include inside fetched content resolves against the remote URL (RFC 3986) and is fetched; nested https:// and http:// includes are allowed; a URL cycle exits 4; everything reached through a remote include is remote and read-only.")
