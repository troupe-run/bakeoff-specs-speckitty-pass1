# Mission Specification: troupe configuration: get for values, show for anything

**Mission Branch**: `feat/troupe-config-get-show` (delivered by merging into `main`)
**Created**: 2026-10-03
**Status**: Draft
**Input**: Step 3 brief — "`get` for values, `show` for anything". Contract section added: *get and show* (replaces *show PATH (step 1 and 2)*). Sections still in force from steps 1–2: General; Includes; set PATH VALUE; history [PATH]; watch / reconcile-first.

## Intent Summary (confirmed)

A theatre owner (or a harness acting for them) reads configuration with two commands:

- `troupe config get PATH` prints one scalar exactly as `show PATH` printed it in steps 1–2. Asking `get` for a mapping or list fails with exit 5 and a stderr message that points to `config show`.
- `troupe config show [PATH]` prints anything: a scalar is printed as `get` would print it; a mapping or list — or the whole configuration when PATH is omitted — is printed as block-style YAML with every include resolved and text includes shown as literal blocks.
- `show [PATH] --sources` prints the same YAML with `# from <file>` at the end of every line that holds a scalar, naming the file (relative to the theatre directory, `/`-separated) the scalar comes from; a text include's value comes from the included file.

Both commands reconcile hand edits first (step 2 rule: every command except `history`), so they always print what the files currently say. Neither command changes any configuration file.

**Decision DM 01M411YHFR2PMJEJWMHX4KN9C4 (out of contract, chosen by agent, PO-acknowledged):** `show PATH --sources` on a single scalar prints that scalar *as YAML* with its `# from <file>` comment (a text include or multi-line string as a literal block whose header line carries the comment). Reason: with `--sources` the output is then always valid YAML and every scalar is attributed, consistent with "the same YAML"; without `--sources` the scalar case is unchanged and identical to `get`.

## Domain Language

| Term | Meaning | Avoid |
|---|---|---|
| Theatre directory | The project directory given by `--theatre` / `$TROUPE_THEATRE` / cwd; source paths are relative to it | "project root", "repo" |
| Root file | `.troupe/troupe.yml` (or `.yaml`) | |
| Scalar | A string, number, bool or null leaf; a text include is a string scalar | "value" when a mapping/list is meant |
| Section | A mapping or list node (including one embedded from a YAML include) | "subtree", "block" |
| Source file | The file whose bytes define a scalar: the file containing it, or the target file for a text include | "owner", "origin" |
| Source comment | The end-of-line comment `# from <file>` added by `--sources` | "annotation" |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read a single value with `get` (Priority: P1)

A theatre owner reads one setting by path, wherever it is defined among the root file and its includes, and gets exactly the bare value — the output step 1/2 scripts relied on from `show`.

**Why this priority**: Scripts need a stable single-value reader; `get` takes over that role from `show`.

**Independent Test**: In a fixture theatre with nested mappings, lists, a YAML include and a text include, run `troupe config get PATH` for scalar paths and compare stdout byte-for-byte with the step-1 scalar printing rules; run it on a mapping, a list and a missing path and check exit codes and stderr.

**Acceptance Scenarios**:

1. **Given** `server: {port: 8080}`, **When** `get server.port` runs, **Then** stdout is `8080\n`, exit 0.
2. **Given** `prompt: file:sys.md` whose target text is `Hello\n`, **When** `get prompt` runs, **Then** stdout is `Hello\n`.
3. **Given** `server` is a mapping (or `tools` is a list), **When** `get server` runs, **Then** exit 5, stdout empty, and the single stderr line names `server` and mentions `config show`.
4. **Given** no `missing` key, **When** `get missing` runs, **Then** exit 5, stdout empty, stderr names `missing`.
5. **Given** the file was hand-edited since the last command, **When** `get` runs, **Then** it prints the edited value (and the edit is reconciled into history first).

---

### User Story 2 - See a section or the whole configuration with `show` (Priority: P1)

A theatre owner wants to see a whole section — or everything — as it resolves after includes, without opening each file.

**Why this priority**: This is the new capability of step 3.

**Independent Test**: Run `troupe config show`, `show server`, `show tools` on a fixture with includes; parse stdout as YAML and compare with the expected merged data; check the literal-block layout of text includes and the scalar case.

**Acceptance Scenarios**:

1. **Given** a root file with `server: file:server.yml` where `server.yml` holds `port: 8080` and `host: example.org`, **When** `show server` runs, **Then** stdout is
   ```
   port: 8080
   host: example.org
   ```
2. **Given** `tools: [a, b]` (flow style in the file), **When** `show tools` runs, **Then** stdout is `- a\n- b\n` (block style).
3. **Given** `prompt: file:sys.md` with target text `line one\nline two\n`, **When** `show` (no PATH) runs, **Then** the output contains
   ```
   prompt: |
     line one
     line two
   ```
4. **Given** a scalar path, **When** `show server.port` runs, **Then** stdout equals what `get server.port` prints (`8080\n`).
5. **Given** any theatre, **When** `show` runs with no PATH, **Then** stdout parsed as YAML equals the whole resolved configuration (every include replaced by its content; text includes as their exact text), keys in file order.
6. **Given** a missing path, **When** `show missing` runs, **Then** exit 5, stdout empty, stderr names `missing`.

---

### User Story 3 - Find out which file a value comes from with `--sources` (Priority: P2)

A theatre owner sees a value and wants to know which file to edit.

**Why this priority**: Builds on story 2; answers "where is this set?" across includes.

**Independent Test**: Run `show --sources` and `show PATH --sources` on a fixture whose scalars live in the root file, a YAML include in a subdirectory and a text include; check every scalar line ends with the right `# from <file>` and no other line has one.

**Acceptance Scenarios**:

1. **Given** the fixture of story 2 scenario 1 plus `name: demo` in the root, **When** `show --sources` runs, **Then** stdout is
   ```
   name: demo # from .troupe/troupe.yml
   server:
     port: 8080 # from .troupe/server.yml
     host: example.org # from .troupe/server.yml
   ```
2. **Given** `prompt: file:prompts/sys.md` in `.troupe/troupe.yml`, **When** `show --sources` runs, **Then** the header line is `prompt: | # from .troupe/prompts/sys.md` and the block lines that follow carry no comment.
3. **Given** a list of scalars `tools: [a, b]`, **When** `show tools --sources` runs, **Then** stdout is `- a # from .troupe/troupe.yml\n- b # from .troupe/troupe.yml\n`.
4. **Given** a scalar path, **When** `show server.port --sources` runs, **Then** stdout is `8080 # from .troupe/server.yml\n` (decision DM 01M411YHFR2PMJEJWMHX4KN9C4).
5. **Given** `--sources` output, **When** it is parsed as YAML, **Then** the data equals the output of `show` without `--sources` for the same PATH.

### Edge Cases

- Empty mapping or list (including an empty YAML include target) prints as `{}` / `[]`; such a line holds no scalar and gets no source comment. `show` on an empty root file prints `{}\n`.
- A string that would read back as another type or is otherwise not representable plain (`'true'`, `'123'`, `''`, `': x'`, leading/trailing spaces, `#` after a space, leading indicator characters) is quoted so the YAML reads back as the same string; a key needing quotes is quoted the same way.
- A multi-line string (from a text include or written in a file) prints as a literal block; chomping (`|-` no final newline, `|` exactly one, `|+` more than one) preserves the exact text; a first line starting with a space gets an indentation indicator.
- Text that a literal block cannot hold exactly (e.g. carriage returns from a CRLF text include, other control characters) prints double-quoted with escapes; it still counts as one scalar line for `--sources`.
- A YAML include whose target is just a scalar: that scalar's source file is the included file.
- An include target outside the theatre directory: the source path is relative with `..` segments (e.g. `../shared/x.yml`), still `/`-separated.
- A list of mappings prints in compact form (`- name: x` then sibling keys indented two spaces); the scalar on the `- name: x` line gets its comment.
- PATH with an empty segment → exit 2 (unchanged usage rule). Configuration that cannot be loaded → exit 4 (unchanged).
- `get PATH --sources` is not a valid option → exit 2 (usage).

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | get: scalar | As an owner, `troupe config get PATH` prints the scalar at PATH exactly as step-1 `show PATH` did (step-1 scalar printing rules; a text include prints its target's exact text). | High | Open |
| FR-002 | get: sections refused | As an owner, `get` on a mapping or list exits 5 with empty stdout and one stderr line that names PATH and mentions `config show`. | High | Open |
| FR-003 | get/show: missing path | As an owner, `get` or `show` on a path that does not exist (unknown key, out-of-range index, path through a scalar) exits 5 with empty stdout and stderr naming the path. | High | Open |
| FR-004 | show: scalar | As an owner, `show PATH` on a scalar prints exactly what `get PATH` prints. | High | Open |
| FR-005 | show: section as YAML | As an owner, `show PATH` on a mapping or list prints it as block-style YAML whose data, when read back, equals the resolved section (includes replaced by their content, text includes by their exact text), keys and items in file order. | High | Open |
| FR-006 | show: whole configuration | As an owner, `show` with no PATH prints the whole resolved configuration per FR-005. | High | Open |
| FR-007 | show: text includes as literal blocks | As an owner, a text include's value (and any other multi-line string) is printed as a literal block whose chomping/indentation indicators preserve the exact text; text a literal block cannot represent exactly is printed double-quoted with escapes. | High | Open |
| FR-008 | show: YAML layout | As an owner, show output uses 2-space indentation, list items `- ` indented under their key, compact `- key: value` for list items that are mappings, `{}`/`[]` for empty collections, `true`/`false`/`null`, integers in decimal, floats as `get` prints them except infinities and NaN, which are `.inf`/`-.inf`/`.nan` (plan D-3), and exponent forms without a `.`, which get `.0` before the `e` (e.g. `1.0e+20`, plan D-10), so they read back as floats, and no document markers; strings and keys are plain only when common YAML readers (YAML 1.2 and 1.1) read them back as the same string (plan D-10), otherwise single-quoted, otherwise double-quoted. | Medium | Open |
| FR-009 | show --sources | As an owner, `show [PATH] --sources` prints the same YAML as without `--sources`, with ` # from <file>` appended to every line that holds a scalar and to no other line. | High | Open |
| FR-010 | Source file | As an owner, `<file>` is the file the scalar comes from — the file containing it, or the included file for a text include — relative to the theatre directory with `/` separators (`..` segments when outside it). | High | Open |
| FR-011 | Block scalar sources | As an owner, for a scalar printed as a literal block the source comment is on the block's header line (`key: | # from <file>`), never inside the block. | High | Open |
| FR-012 | Scalar PATH with --sources | As an owner, `show PATH --sources` on a scalar prints that scalar as a YAML scalar (per FR-007/FR-008) followed by its source comment (DM 01M411YHFR2PMJEJWMHX4KN9C4). | Medium | Open |
| FR-013 | Reconcile first | As an owner, `get` and `show` reconcile hand edits into history before reading, so they print the current file values. | High | Open |
| FR-014 | Read-only | As an owner, `get` and `show` never modify any configuration or include file. | High | Open |
| FR-015 | Help text | As an owner, `troupe config --help` lists `get` ("print the scalar at PATH") and `show` ("print PATH, or everything, as YAML"; documents `--sources`). | Low | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Round-trip fidelity | For 100% of fixture configurations in the test suite, `show` output (with and without `--sources`) parses as YAML to data equal to the resolved configuration. | Correctness | High | Open |
| NFR-002 | Error discipline | 100% of non-zero exits of `get`/`show` have empty stdout and exactly one stderr line `troupe: <message>` naming the offending path or file. | Usability | High | Open |
| NFR-003 | Quality gates | Test suite, strict type check, lint and format check pass with 0 failures/errors before delivery. | Maintainability | High | Open |
| NFR-004 | Backward compatibility of scalar reads | 100% of step-1/2 acceptance checks of `show PATH` on scalars pass unchanged against both `get PATH` and `show PATH`. | Compatibility | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Contract sections | The step-3 "get and show" contract section replaces "show PATH (step 1 and 2)"; all other step-1/2 sections (General, Includes, set, history, watch/reconcile-first, exit codes) stay in force unchanged. | Business | High | Open |
| C-002 | Delivery | Work is done when committed on `main` of this repository; no push, no pull request. | Business | High | Open |
| C-003 | State confinement | Commands may create/modify only `<theatre>/.troupe/history.sqlite` and its side files (unchanged from step 1). | Technical | High | Open |
| C-004 | Contract docs | The mission's CLI contract documents `get`, `show [PATH] [--sources]` and the recorded layout decisions. | Technical | Medium | Open |

### Key Entities

- **Resolved configuration**: the merged tree of mappings, lists and scalars after includes; each scalar knows its source file.
- **Source file**: a file under (or relative to) the theatre directory that defines a scalar.

## Assumptions

- Recorded agent choices where the contract is silent (PO confirmed "no corrections"): YAML layout per FR-008; multi-line strings as literal blocks (FR-007); comment on the block header line (FR-011); `..` paths for targets outside the theatre (FR-010); exactly one space before `#` in a source comment; `get` does not accept `--sources`.
- `show` keeps its name; scripts that used `show PATH` on scalars keep working (FR-004), so no rename across the code base is needed — existing tests that expect `show` to refuse a mapping/list move to `get`.
- Source comments are not part of the data: the YAML with comments reads back the same as without.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An owner can see the full resolved configuration with one command, without opening any file.
- **SC-002**: For every scalar shown, the owner can name the file to edit from the output alone (100% of scalar lines attributed with `--sources`).
- **SC-003**: Every step-1/2 single-value read keeps producing byte-identical output via `get` (0 regressions).
- **SC-004**: 100% of `show` outputs in the acceptance suite read back as data equal to the configuration they describe.
