# Mission Specification: troupe configuration: lineage for every change

**Mission Branch**: `feat/troupe-config-lineage` (delivered by merging into `main`)
**Created**: 2026-10-04
**Status**: Draft
**Input**: Step 4 brief — "lineage". Contract section added: *Lineage*. Sections still in force from steps 1–3: General; Includes; get and show; set PATH VALUE; history [PATH]; watch / reconcile-first.

## Intent Summary (confirmed)

People and AI agents change a theatre's configuration through the CLI, by hand-editing files, and implicitly by the first import. An auditor (a theatre owner, a reviewer, or a harness acting for them) runs `troupe config history [PATH]` and, for every recorded event, can answer:

- **Who** — `actor`: `{"kind": "human" | "agent" | "unknown", "id": <string or null>}`.
- **How** — `via`: `"import"`, `"cli"` or `"file"`.
- **When** — `at`: an RFC 3339 UTC timestamp ending in `Z`.
- **Why** — `reason`: the text given with `troupe config set --reason TEXT`, else `null`.
- **What else** — `change`: one id shared by every event one producer (a CLI command, a file reconcile, or an import) produced; no two producers share one.

A CLI command's actor comes from `TROUPE_ACTOR` (`human:<id>` or `agent:<id>`; anything else, including an empty value or an empty id, exits 2); when it is unset the actor is the human running the command, identified by login name. Imports and file-originated events are attributed to `{"kind": "unknown", "id": null}` — unknown is said explicitly, never guessed. Lineage is persisted with the events, so it survives restarts.

Confirmed rules (product owner):

- A `set` that first reconciles hand edits produces **two** changes: the reconcile's events (`via: "file"`, actor unknown, `reason: null`) share one change id; the `set`'s own events (`via: "cli"`, actor from `TROUPE_ACTOR`, its reason) share a different one.
- Each reconcile `watch` performs is its own change.
- `--reason` exists only on `set`; it is stored exactly as given. A `set` that changes nothing records nothing, so its reason is not kept.
- History line keys, in order: `seq, op, path, old, new, actor, via, at, reason, change`.
- `TROUPE_ACTOR` is validated by every `troupe config` command.

Agent decisions (out of contract; recorded here, **not** as contract amendments):

- **DM 01M436RBNQT22F9AM54QER2FT9 — events recorded before lineage existed.** Histories written by steps 1–3 hold events without lineage. `history` reports them with what is truly known and marks the rest unknown: `at` is the event's stored recording time (the store always kept one); `actor` is `{"kind": "unknown", "id": null}`; `reason` is `null`; `via` is `"import"` for an `import` event and `null` for a `set`/`remove` event, because the stored data cannot tell a CLI `set` from a file reconcile; `change` is a stable id unique to that one event (which events were made together was never recorded), distinct from every id given to a new change. Stored events are never rewritten. *Why:* it loses nothing (the alternative, refusing to read the history, would hide a user's existing audit trail), and it follows the brief's rule to state unknowns rather than guess. Every event recorded from this step on carries a contract-conforming `via`.
- **DM 01M436TPQDWVSZQYFD6D5343DC — when `TROUPE_ACTOR` is checked.** After the arguments are parsed and before the theatre is located or the configuration loaded. A bad value therefore exits 2 even when the configuration could not be loaded (which would be exit 4), and the command records nothing — not even an import or reconcile. *Why:* a command that is going to fail must not leave events behind; this is the choice least likely to put unattributable or unwanted entries into the history.
- **DM 01M436TX68S2MGE4DN9AM02KTJ — login name unavailable.** If `TROUPE_ACTOR` is unset and the login name cannot be determined, the actor is `{"kind": "human", "id": null}` and the command proceeds. *Why:* the contract says an unset variable means a human actor; the id is then genuinely unknown and is stated as `null` rather than invented, and refusing would block the user without protecting any data.

## Domain Language

| Term | Meaning | Avoid |
|---|---|---|
| Lineage | The five fields `actor`, `via`, `at`, `reason`, `change` carried by every history event | "metadata", "audit info" |
| Actor | Who made an event: kind `human`, `agent` or `unknown`, plus an id or `null` | "user", "author" |
| Via | The channel an event came through: `import`, `cli` or `file` | "source" (that word means a source *file* in `show --sources`) |
| Change | The unit of events one producer recorded together; identified by a change id | "transaction", "batch", "commit" |
| Producer | One CLI command's own work, one file reconcile, or one import — each yields exactly one change | |
| File reconcile | Recording hand edits found by comparing the files with the history (run before a command's own work, and by `watch`) | "sync" |
| Pre-lineage event | An event recorded by steps 1–3, before lineage existed | "legacy" in user-facing text |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See who changed a setting through the CLI, and why (Priority: P1)

An agent (or a person) changes a setting with `troupe config set`, optionally giving a reason. Later an auditor reads `troupe config history PATH` and sees which human or agent made the change, that it came through the CLI, when, and why.

**Why this priority**: Attributing CLI changes to a specific human or agent is the core audit need.

**Independent Test**: In a fixture theatre, run `set` with `TROUPE_ACTOR=agent:planner` and `--reason "raise limit"`, then `history`; parse each line as JSON and check the lineage fields. Repeat with `TROUPE_ACTOR` unset and with invalid values.

**Acceptance Scenarios**:

1. **Given** an imported theatre with `limits.max: 5`, **When** `TROUPE_ACTOR=agent:planner troupe config set limits.max 10 --reason "raise limit"` runs, **Then** the new `history` line has `op: "set"`, `actor: {"kind": "agent", "id": "planner"}`, `via: "cli"`, `reason: "raise limit"`, an `at` ending in `Z`, and a `change` string.
2. **Given** `TROUPE_ACTOR=human:alice`, **When** `set` runs without `--reason`, **Then** the event has `actor: {"kind": "human", "id": "alice"}` and `reason: null`.
3. **Given** `TROUPE_ACTOR` is unset and the login name is `bob`, **When** `set` runs, **Then** the event has `actor: {"kind": "human", "id": "bob"}`.
4. **Given** `TROUPE_ACTOR` is `robot:x`, `human:`, `agent:`, `alice`, or set but empty, **When** any `troupe config` command runs, **Then** it exits 2, stdout is empty, the single stderr line names `TROUPE_ACTOR`, and nothing is recorded or written.
5. **Given** `TROUPE_ACTOR` is unset and no login name can be determined, **When** `set` runs, **Then** the event has `actor: {"kind": "human", "id": null}`.
6. **Given** a `set` whose value equals the current value, **When** it runs with `--reason`, **Then** no event is recorded.

---

### User Story 2 - See changes that arrived by hand edit or import, marked unknown (Priority: P1)

A person edits `troupe.yml` in a text editor; the next command (or a running `watch`) reconciles the edit. The first command ever run in a theatre imports its configuration. The auditor sees these events marked as coming from a file or the import, with an explicitly unknown actor.

**Why this priority**: Not guessing an author for hand edits is an explicit rule of the brief.

**Independent Test**: Import a fixture theatre via any command, hand-edit a value, run `get`, then `history`; check the import events and the file event. Run `watch`, make two edits separated by polls, and check that each reconcile has its own change id.

**Acceptance Scenarios**:

1. **Given** a never-imported theatre with three leaves, **When** any command (including `history`) runs, **Then** the three `import` events have `via: "import"`, `actor: {"kind": "unknown", "id": null}`, `reason: null`, and one shared `change`.
2. **Given** a hand edit of one value, **When** `get` runs, **Then** the reconciled event has `via: "file"`, `actor: {"kind": "unknown", "id": null}`, `reason: null`, even when `TROUPE_ACTOR` is set.
3. **Given** `watch` is running, **When** two separate edits are each reconciled, **Then** the events of each reconcile share a change id and the two change ids differ.

---

### User Story 3 - See which events belong to one change (Priority: P1)

A single command can produce several events (a `set` that replaces a mapping or list, or a hand edit touching many values). The auditor groups history lines by `change` to see each multi-value change as a unit.

**Why this priority**: "What else changed with it?" is one of the five questions the brief requires answering.

**Independent Test**: Hand-edit two values, then run `set` with a mapping value that changes three leaves; check that history shows the two file events sharing one change id, the three cli events sharing another, and the import change different from both.

**Acceptance Scenarios**:

1. **Given** a `set` whose value replaces several leaves, **When** it succeeds, **Then** all its events share one `change` and have identical `actor`, `via`, `at` and `reason`.
2. **Given** pending hand edits, **When** `set` runs, **Then** the reconcile events share one `change` with `via: "file"` and the `set`'s own events share a different `change` with `via: "cli"`.
3. **Given** a never-imported theatre, **When** `set` runs, **Then** the import events and the `set`'s events have different change ids.
4. **Given** any two commands, reconciles or imports, **When** history is read, **Then** their change ids differ — including across separate processes and restarts.

---

### User Story 4 - Lineage survives restarts and old histories stay readable (Priority: P2)

Lineage is part of the persisted history: closing everything and reading `history` later shows the same values. A theatre whose history was written before this step still lists every event.

**Why this priority**: An audit trail that disappears or becomes unreadable is worthless; existing users must not lose their history.

**Independent Test**: Record events, then read `history` twice in separate processes and compare output byte-for-byte. Build a history with the step-3 code (or a fixture database recorded by it), then read it with the new code.

**Acceptance Scenarios**:

1. **Given** recorded events, **When** `history` is run in a new process, **Then** every line, including all lineage fields, is identical to the previous run.
2. **Given** a history recorded before lineage existed, **When** `history` runs, **Then** each old event shows its stored recording time as `at`, `actor: {"kind": "unknown", "id": null}`, `reason: null`, `via: "import"` for `import` events and `null` for `set`/`remove` events, and a `change` unique to that event; the stored history is not modified.
3. **Given** such a history, **When** a new `set` runs, **Then** the new events carry full lineage and their change id differs from every old event's.

### Edge Cases

- `--reason ""`: stored as the empty string `""` (the text given), not `null`.
- `--reason` containing quotes, newlines or non-ASCII text: printed exactly, JSON-escaped as needed.
- `--reason` on any command other than `set`: usage error, exit 2.
- `set` refused (exit 3) or failing on a path (exit 5) after reconciling: the reconcile's change is kept (step 2 rule), the `set` records nothing and its reason is not kept.
- A `set` usage error (bad PATH/VALUE, exit 2): nothing recorded, as before.
- `TROUPE_ACTOR=human:alice:x` or ids with spaces: the id is everything after the first `:` and must be non-empty; such values are accepted as given. (`human:` and `agent:` with an empty id are rejected.)
- `TROUPE_ACTOR` with the kind in another case (`Human:alice`): not one of the valid forms → exit 2.
- `history PATH` filtering: unchanged; filtered lines carry their full lineage, and a change may appear only partly when some of its events lie outside PATH.
- A bad `TROUPE_ACTOR` given to `watch`: exits 2 before printing `watching <dir>`.

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Lineage on every history line | As an auditor, I want every `history` line to carry `actor`, `via`, `at`, `reason` and `change` after `seq, op, path, old, new`, in the order `seq, op, path, old, new, actor, via, at, reason, change`, so that each event answers who, how, when, why and with what. | High | Open |
| FR-002 | Actor from `TROUPE_ACTOR` | As an agent harness, I want the actor of a CLI command's own events to be `{"kind": "human", "id": <id>}` for `TROUPE_ACTOR=human:<id>` and `{"kind": "agent", "id": <id>}` for `agent:<id>`, where `<id>` is the non-empty text after the first `:`, so that my changes are attributed to me. | High | Open |
| FR-003 | Invalid `TROUPE_ACTOR` exits 2 | As an auditor, I want every `troupe config` command to exit 2 with empty stdout and one stderr line naming `TROUPE_ACTOR` when the variable is set but is not `human:<id>` or `agent:<id>` (including empty, an empty id, or an unknown kind), checked after argument parsing and before the theatre is located or loaded, so that nothing is recorded under a bad identity (DM 01M436TPQDWVSZQYFD6D5343DC). | High | Open |
| FR-004 | Default actor is the login name | As a person at a terminal, I want my CLI changes attributed to `{"kind": "human", "id": <my login name>}` when `TROUPE_ACTOR` is unset, and to `{"kind": "human", "id": null}` when no login name can be determined (DM 01M436TX68S2MGE4DN9AM02KTJ). | High | Open |
| FR-005 | Unknown actor for import and file events | As an auditor, I want import events and file-reconcile events to carry `actor: {"kind": "unknown", "id": null}` regardless of `TROUPE_ACTOR`, so that no author is guessed. | High | Open |
| FR-006 | `via` per producer | As an auditor, I want import events to carry `via: "import"`, file-reconcile events (from any command or `watch`) `via: "file"`, and a CLI command's own events `via: "cli"`. | High | Open |
| FR-007 | `at` timestamp | As an auditor, I want every event to carry `at`, the UTC time it was recorded, as an RFC 3339 timestamp ending in `Z`; all events of one change carry the same `at`. | High | Open |
| FR-008 | `set --reason TEXT` | As a person or agent changing a value, I want `troupe config set PATH VALUE --reason TEXT` to store TEXT exactly as given as the `reason` of that set's own events; events without a given reason (including all import and file events) carry `reason: null`; `--reason` is accepted only by `set`. | High | Open |
| FR-009 | One change id per producer | As an auditor, I want every event one producer records — a CLI command's own work, one file reconcile, or one import — to share one `change` string, and no two producers ever to share one, across processes and restarts. | High | Open |
| FR-010 | Reconcile and command are separate changes | As an auditor, I want the reconcile a command runs before its own work, and the import a command may trigger, each to be its own change, separate from the change of the command's own events. | High | Open |
| FR-011 | Each `watch` reconcile is a change | As an auditor, I want each reconcile performed by `watch` to have its own change id. | Medium | Open |
| FR-012 | Lineage is persisted | As an auditor, I want lineage stored with each event in the theatre's history so that `history` reports identical lineage after the process exits and in later runs. | High | Open |
| FR-013 | Pre-lineage events reported honestly | As an existing user, I want events recorded before this step listed with their stored recording time as `at`, `actor: {"kind": "unknown", "id": null}`, `reason: null`, `via: "import"` for `import` events and `via: null` for `set`/`remove` events, and a stable `change` unique to each such event and distinct from every new change id, without the stored history being modified (DM 01M436RBNQT22F9AM54QER2FT9). | Medium | Open |
| FR-014 | No-op and failed sets keep no reason | As an auditor, I want a `set` that changes nothing, is refused, or fails to record none of its own events (so its reason is not kept), while a reconcile it ran first is still kept as its own change. | Medium | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Changes recorded atomically | For 100% of producers, either all events of the change (with their lineage) are saved or none are; a reader never sees a partial change. | Reliability | High | Open |
| NFR-002 | User files untouched | Recording or reading lineage changes 0 bytes of any configuration file beyond what a `set` was asked to change (TROUPE-001). | Reliability | High | Open |
| NFR-003 | Stable output across runs | Running `history` twice with no change in between yields byte-identical output in 100% of cases, including lineage. | Reliability | High | Open |
| NFR-004 | Existing history preserved | Reading or appending to a history recorded before this step modifies 0 of its stored events and lists 100% of them. | Reliability | High | Open |
| NFR-005 | Behaviour coverage | Every functional requirement above has at least one test, run against real files, the real CLI and the real event store, that fails if the behaviour breaks; `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` all pass. | Maintainability | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Contract unchanged | The contract's Lineage section is implemented as written; out-of-contract choices are recorded in this spec and project documentation, never as contract amendments. | Business | High | Open |
| C-002 | Fixed platform | Python 3.12+ with uv; CLI runs as `uv run troupe config …`; the event store stays on the `eventsourcing` library in `<theatre>/.troupe/`; macOS/Linux only (TROUPE-004). | Technical | High | Open |
| C-003 | Earlier behaviour kept | `seq`, `op`, `path`, `old`, `new`, the `history [PATH]` filter, exit codes and the reconcile-first and write-back rules of steps 1–3 are unchanged except as this spec states. | Technical | High | Open |
| C-004 | Error messages name what is wrong | Every new error message names the variable, path or file involved (TROUPE-003). | Technical | Medium | Open |
| C-005 | No stored-history rewriting | No migration rewrites, reorders or deletes stored events. | Technical | High | Open |

### Key Entities

- **History event**: one recorded leaf change (`import`, `set` or `remove`) with its position, path, old and new value, plus its lineage.
- **Lineage**: actor (kind + id-or-null), via, at, reason-or-null, change id.
- **Change**: the set of events one producer recorded together; identified by its change id; all its events share actor, via, at and reason.
- **Producer**: a CLI command's own work, a file reconcile, or an import.

## Assumptions

- "Login name" means the operating system's notion of the login name of the user running the process; how it is looked up is a plan decision.
- `at` has at least whole-second precision; finer precision is allowed as long as the value is valid RFC 3339 ending in `Z`.
- The format of a change id is not specified by the contract; any string meeting FR-009 is acceptable, and the format is chosen in the plan.
- Read-only commands (`get`, `show`, `history`) record no events of their own; only an import or reconcile they trigger produces events.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For 100% of events recorded after this step, an auditor can read who (actor kind and id or explicit null), how, when, why and which change from one `history` line, without any other source.
- **SC-002**: 0 events from imports or hand edits are attributed to a named person or agent.
- **SC-003**: Grouping history lines by `change` reproduces exactly the set of events each command, reconcile or import produced — no group merges two producers and no producer is split across groups.
- **SC-004**: After a restart, 100% of history lines — lineage included — read back identically.
- **SC-005**: 100% of events in a history written before this step are still listed, with no stored event altered.
- **SC-006**: Every invalid `TROUPE_ACTOR` form in the acceptance scenarios is rejected with exit 2 and leaves the history and all configuration files unchanged.
