# Mission Specification: troupe configuration: load, show, set

**Mission Branch**: `feat/troupe-config-load-show-set` (delivered to `main`)
**Created**: 2026-10-02
**Status**: Draft
**Input**: Step 1 brief — troupe configuration subsystem (load with includes, event-sourced history, `config show`, `config set`, `config history`). Contract sections in force: General; Includes; show PATH (step 1 and 2); set PATH VALUE; history [PATH].

## Intent Summary (confirmed)

A theatre owner (or an automated harness acting for them) runs `troupe config show|set|history` against a project ("theatre") whose configuration lives in hand-edited, diff-reviewed YAML files rooted at `.troupe/troupe.yml` (or `.yaml`) and split across `file:` includes. They can read any scalar setting, change or add a setting so that the change lands in whichever file owns it with **only the bytes of that value changing**, and list every change made through troupe as a per-leaf history. Failures are reported with a fixed exit code, empty stdout, and a stderr message naming the offending path or file.

**Confirmed decision (DM 01M3XGPT4E0D67ZJY8PT7Z9NAT):** the files on disk are the source of truth. `show` and `set` always read the files as they currently are. The stored projection is only the change history: a hand edit is visible to `show` but produces no history event, and a later `set` records as `old` whatever value is in the file at that moment.

## Domain Language

| Term | Meaning | Avoid |
|------|---------|-------|
| Theatre | A project directory containing `.troupe/troupe.yml` or `.troupe/troupe.yaml` | "workspace", "repo" |
| Root file | The single `troupe.yml`/`troupe.yaml` in `<theatre>/.troupe/` | "main config" |
| Include | A string value beginning `file:`; the rest is a path relative to the containing file's directory | "import" (reserved for history) |
| YAML include | An include whose target ends `.yml`/`.yaml`; its content is embedded in place | |
| Text include | An include with any other target; its value is the target file's exact text | |
| Path | Dotted address of a node; digit-only segments index lists (0-based) | "key path", "selector" |
| Leaf | A scalar node (including a text-include string); list items addressed as `list.0`, `list.1`, … | |
| Import | The one-time recording of every leaf of a never-before-seen theatre into history | "sync", "reconcile" |
| Byte-surgical write-back | A `set` after which the only differing bytes in any file are those the contract requires | "rewrite", "reformat" |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read a setting (Priority: P1)

A theatre owner asks troupe for the value of one setting, wherever it is defined among the root file and its includes.

**Why this priority**: Loading the configuration (including includes) and addressing a value by path is the foundation every other command builds on.

**Independent Test**: Create a theatre fixture with nested mappings, lists, a YAML include and a text include; run `uv run troupe config show PATH --theatre <dir>` for various paths and compare stdout and exit codes.

**Acceptance Scenarios**:

1. **Given** `model: {temperature: 0.2}` in the root file, **When** `show model.temperature` runs, **Then** stdout is `0.2\n` and exit code is 0.
2. **Given** `agents: {coder: file:agents/coder.yaml}` and `agents/coder.yaml` contains `name: Ada`, **When** `show agents.coder.name` runs, **Then** stdout is `Ada\n`.
3. **Given** `prompt: file:prompts/sys.md` whose text ends with a newline, **When** `show prompt` runs, **Then** stdout is exactly the file text with no extra newline.
4. **Given** `tools: [a, b]`, **When** `show tools.1` runs, **Then** stdout is `b\n`; **When** `show tools` runs, **Then** exit code is 5, stdout empty, stderr names `tools`.
5. **Given** a path that does not exist, **When** `show` runs, **Then** exit code 5 and stderr names the path.
6. **Given** a theatre with neither or both of `troupe.yml`/`troupe.yaml`, or an include whose target is missing or forms a cycle, **When** any subcommand runs, **Then** exit code 4 and stderr names the offending file.
7. **Given** a theatre that was imported earlier and then hand-edited, **When** `show` runs, **Then** it prints the hand-edited value from disk.

---

### User Story 2 - Change a setting without disturbing the file (Priority: P1)

A theatre owner changes, adds, or appends a setting; the change is written into whichever file owns it, and a diff of that file shows only the changed value's bytes.

**Why this priority**: This is the core user value — people edit and review these files by hand, so any collateral reformatting is a defect.

**Independent Test**: For each fixture file, snapshot all bytes, run `set`, and assert the new bytes equal the expected bytes exactly (whole-file comparison), across every write-back rule below.

**Acceptance Scenarios**:

1. **Given** `  temperature: 0.2  # creativity` under `model:`, **When** `set model.temperature 0.75` runs, **Then** the line becomes `  temperature: 0.75 # creativity` (comment stays at its previous column) and no other byte in any file changes; **When** `set model.temperature 0.12345` then runs, **Then** the value reaches that column and the line becomes `  temperature: 0.12345 # creativity`.
2. **Given** `name: "Ada"`, **When** `set name Grace` runs, **Then** the line becomes `name: "Grace"` (quoting style kept).
3. **Given** `agents.coder` is `file:agents/coder.yaml`, **When** `set agents.coder.name Grace` runs, **Then** only `agents/coder.yaml` changes; **When** `set agents.coder x` runs, **Then** exit code 3 and no file changes.
4. **Given** a text include `prompt: file:sys.md` with CRLF endings, **When** `set prompt "a\nb\n"` runs, **Then** `sys.md` becomes `a\r\nb\r\n`; **When** `set prompt 5` runs, **Then** exit code 3.
5. **Given** `tools: [a, b]` in flow style, **When** `set tools.2 c` runs, **Then** the line becomes `tools: [a, b, c]`; **When** `set tools.5 c` runs, **Then** exit code 5.
6. **Given** a block mapping followed by trailing comment lines at its indentation, **When** a new key is added, **Then** it is written below those comments and before the next less-indented line.
7. **Given** `notes: short`, **When** `set notes "line one\nline two\n"` runs, **Then** it is written as a literal block `notes: |` with indented lines.
8. **Given** a folded (`>`) value of several paragraphs, **When** one paragraph's text changes, **Then** unchanged paragraphs keep their bytes and the changed paragraph is re-wrapped greedily at its previous longest content-line width.
9. **Given** an invalid invocation (missing arguments, unknown subcommand), **When** it runs, **Then** exit code 2.

---

### User Story 3 - Review what changed (Priority: P2)

A theatre owner lists the configuration's history, optionally filtered to a subtree, to audit what troupe changed and when.

**Why this priority**: Auditability is the purpose of event sourcing the configuration, but the system is usable without it.

**Independent Test**: Run `history` on a fresh theatre, then a sequence of `set` commands, and compare the JSON Lines output (seq, op, path, old, new).

**Acceptance Scenarios**:

1. **Given** a never-imported theatre, **When** `history` runs, **Then** it emits one `import` event per leaf with `old: null`, `seq` starting at 1, oldest first.
2. **Given** an imported theatre, **When** `set model.temperature 0.5` changes 0.2→0.5, **Then** one `set` event `{"op":"set","path":"model.temperature","old":0.2,"new":0.5}` is appended.
3. **Given** `tools: [a, b]`, **When** `set tools [c]` runs, **Then** events are `set tools.0 a→c` and `remove tools.1 b→null`.
4. **Given** a `set` whose value equals the current value, **When** it runs, **Then** no event is emitted.
5. **Given** history containing events under `model` and `models`, **When** `history model` runs, **Then** only events whose path equals `model` or starts with `model.` are printed.
6. **Given** a hand edit of a value after import, **When** `history` runs, **Then** no event reflects the hand edit; **When** a later `set` changes that value, **Then** its `old` is the hand-edited value.

### Edge Cases

- Neither or both root files → exit 4. Missing include target or include cycle → exit 4.
- `show` on a mapping or list → exit 5; path through a scalar or out-of-range index → exit 5.
- `set` at list index equal to length appends; any larger index → exit 5.
- `set` replacing a value whose whole value is an include → exit 3 with no file changed.
- `set` on a text include with a non-string `VALUE` and a CRLF target → exit 3; with an LF target, `set prompt 5` or `set prompt '{a: 1}'` writes `5` / `{a: 1}` as the file's content.
- A change that would put a more-indented line into a folded scalar → exit 3.
- Changed value grows past its end-of-line comment's column → exactly one space before the comment.
- Comment line indented less than a collection's entries ends that collection (new entries go above it).
- New key with multi-line string under a flow parent → double-quoted flow scalar.
- Scalar replaced by a block collection → key's line keeps its bytes through its end-of-line comment.
- Columns are counted in Unicode code points, not bytes.
- On any non-zero exit, stdout is empty and stderr names the offending path or file.

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Invocation | As an owner, I run `troupe config <subcommand> --theatre <dir> [arguments]`; `--theatre` defaults to the current directory; malformed invocations exit 2. | High | Open |
| FR-002 | Root file discovery | As an owner, my config is `<dir>/.troupe/troupe.yml` or `.troupe/troupe.yaml`; neither or both exits 4 naming the file(s). | High | Open |
| FR-003 | Path addressing | As an owner, I address nodes with `.`-separated keys where a digit-only segment indexes a list (0-based). | High | Open |
| FR-004 | VALUE parsing | As an owner, `VALUE` is parsed as one YAML 1.2 core-schema flow node (`0.2` float, `true` bool, `null`, `abc`/`"0.2"` strings, `{a: 1}` mapping, `[a, b]` list, escaped multi-line strings); a VALUE that cannot be parsed, or is a block-style node (e.g. `a: 1`), exits 2. | High | Open |
| FR-005 | Scalar printing | As an owner, a scalar prints as: strings exactly plus `\n` unless already ending in `\n`; `true`/`false`; `null`; integers in decimal; floats as Python `repr()`. | High | Open |
| FR-006 | Exit codes and errors | As an owner, outcomes use exit 0/2/3/4/5 as contracted; on any non-zero exit stdout is empty and stderr names the offending path or file. | High | Open |
| FR-007 | Includes | As an owner, a string starting `file:` includes the path after it, relative to the containing file's directory: `.yml`/`.yaml` targets embed their content in place; other targets yield the file's exact text; includes resolve recursively; a missing target or cycle exits 4. | High | Open |
| FR-008 | Files are source of truth | As an owner, `show` and `set` always read the current files on disk; hand edits are visible to `show`, produce no history event, and a later `set` records the on-disk value as `old`. | High | Open |
| FR-009 | show | As an owner, `show PATH` prints the scalar at PATH (a text include is a string); a mapping or list, or a missing path, exits 5. | High | Open |
| FR-010 | set: owning file | As an owner, `set` changes an existing value in the file that contains it; for a text include the target file's content becomes VALUE exactly, converted to CRLF if the target used CRLF (VALUE must then be a string, else exit 3); with an LF target any VALUE is accepted — a string is written as parsed, a non-string (scalar, mapping or list) as the VALUE argument exactly as typed. | High | Open |
| FR-011 | set: new keys | As an owner, a new key is written into the file containing the deepest existing ancestor mapping of PATH, creating missing intermediate mappings there. | High | Open |
| FR-012 | set: list append | As an owner, a PATH whose final index equals the list's length appends; a larger index exits 5. | High | Open |
| FR-013 | set: include replacement refused | As an owner, replacing a value whose whole value comes from a YAML include (a `file:` target ending `.yml`/`.yaml`) exits 3 and changes no file; text includes are rewritten per FR-010. | High | Open |
| FR-014 | Byte-surgical write-back | As an owner, after a successful `set` the only bytes that differ in any file are those FR-015–FR-021 require. | High | Open |
| FR-015 | Scalar quoting | As an owner, a changed scalar keeps its quoting style if it can represent the new value, else plain, else single-quoted, else double-quoted; new keys and new string values copy the preceding sibling's quoting style, else plain or minimal quoting; double-quoted output escapes only `\\`, `\"` and control characters (as `\t`, `\n`, …). | High | Open |
| FR-016 | New collections | As an owner, a new collection value is written in block style at the file's indentation (default 2), or in flow style if its parent is a flow collection; replacing a scalar by a block collection keeps the key's line bytes through its end-of-line comment. | High | Open |
| FR-017 | Multi-line strings | As an owner, a multi-line string replacing a plain/quoted scalar, or as a new key's value, is written as a literal block (`|`, or `|-` without trailing newline); under a flow parent a new multi-line value is a double-quoted flow scalar; an existing block scalar keeps its indicator and chomping unless the value's trailing newlines require different chomping. | High | Open |
| FR-018 | Folded values | As an owner, in a `>` value unchanged paragraphs keep their bytes; a changed paragraph is re-wrapped greedily by word at its previous longest content-line width (an over-long word takes its own line); a new paragraph wraps at the value's longest old content-line width; a change that would introduce a more-indented line exits 3. | Medium | Open |
| FR-019 | Placement of new entries | As an owner, a new block list item or mapping key goes after the collection's last entry and below any comment lines following it, before the next less-indented line; a comment line indented less than the entries ends the collection. In a flow collection, the new entry is appended after the last entry on that entry's line. | High | Open |
| FR-020 | End-of-line comments | As an owner, when a changed value's length changes, its line's comment returns to its previous column (Unicode code points); if the value reaches that column, exactly one space separates value and comment; no other line changes. | High | Open |
| FR-021 | Persistent event-sourced history | As an owner, configuration changes are held as an event-sourced projection persisted under `<dir>/.troupe/` so it survives between commands. | High | Open |
| FR-022 | Import | As an owner, the first command against a theatre (including `history`) imports it: one `import` event per leaf with `old` null; importing never reconciles later hand edits. | High | Open |
| FR-023 | set events | As an owner, a `set` emits one `set` event per leaf it changes or creates and one `remove` event (`new` null) per leaf that no longer exists; a no-op `set` emits nothing; a refused or failed `set` emits nothing. | High | Open |
| FR-024 | history output | As an owner, `history [PATH]` prints events as JSON Lines, oldest first, each with at least `seq` (from 1), `op`, `path`, `old`, `new`; with PATH, only events whose path equals PATH or starts with `PATH.`; a PATH matching no event prints nothing and exits 0; a syntactically invalid PATH (empty segment) exits 2. | High | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Byte preservation proven | 100% of `set` acceptance tests compare every byte of every theatre file before/after; 0 unexpected differing bytes allowed. | Reliability | High | Open |
| NFR-002 | No partial writes | A refused or failed command (exit ≠ 0) leaves 100% of configuration files byte-identical; file replacement is all-or-nothing per file. | Reliability | High | Open |
| NFR-003 | State confinement | 0 files are created or modified outside `<dir>/.troupe/` by any command, other than include targets changed by `set` as contracted. | Reliability | High | Open |
| NFR-004 | Quality gates | Test suite, strict type check, lint and format check all pass with 0 failures/errors before delivery. | Maintainability | High | Open |
| NFR-005 | Error clarity | 100% of non-zero exits have empty stdout and a stderr message containing the offending path or file name. | Usability | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Runtime | Python 3.12+, managed with uv; the CLI runs as `uv run troupe config …` from the repository root. | Technical | High | Open |
| C-002 | Event store library | The event-sourced projection uses the `eventsourcing` library. | Technical | High | Open |
| C-003 | Platforms | macOS and Linux only. | Technical | Medium | Open |
| C-004 | Out of contract | Not supported (undefined behaviour, untested): TAB before an end-of-line comment, multi-document files, anchors/aliases/merge keys, concurrent writers, keys containing `.`, mappings with digit-only keys. | Business | Medium | Open |
| C-005 | Step scope | Build only step-1 behaviour; rule FR-011 is expected to change at step 5 and anchors at step 6, so these decisions must live in one named place each. | Business | Medium | Open |
| C-006 | Delivery | Work is committed on `main`; no push, no pull request. | Business | High | Open |

### Key Entities

- **Theatre**: a project directory; owns the root file, include targets and the persisted history under `.troupe/`.
- **Configuration document**: the merged tree of mappings, lists and scalars obtained by resolving includes; each node knows which file and byte span it came from.
- **Include**: a link from a string value to a target file; YAML includes contribute a subtree, text includes contribute a string leaf.
- **Change event**: `seq`, `op` (`import`/`set`/`remove`), `path`, `old`, `new` for one leaf.
- **History projection**: the ordered sequence of change events for a theatre, persisted between commands.

## Assumptions

- Files on disk are authoritative; history records only changes made by troupe commands plus the initial import (confirmed decision).
- `set` computes events by comparing leaves before and after the write, so replacing a subtree yields `set`/`remove` events per affected leaf.
- A `set` that is refused (exit 3/4/5) neither writes files nor appends events.
- Import happens even when the first command subsequently fails with exit 5, provided the configuration loads; if loading fails (exit 4) nothing is recorded.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For every contracted write-back rule, a reviewer diffing the edited file sees only the changed value's bytes (plus contracted comment-column moves) — 100% of fixture cases.
- **SC-002**: Every contracted error condition produces its specified exit code with empty stdout and a message naming the path or file — 100% of cases.
- **SC-003**: Any setting reachable through includes can be read with one command and changed with one command, without the user knowing which file holds it.
- **SC-004**: After any sequence of commands, the history lists exactly one event per changed leaf per command, in order, and survives across separate command runs.
