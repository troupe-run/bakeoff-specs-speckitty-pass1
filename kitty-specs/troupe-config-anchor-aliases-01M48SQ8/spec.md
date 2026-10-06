# Mission Specification: troupe configuration: anchors and aliases stay honest

**Mission Branch**: `fix/troupe-config-anchor-aliases` (delivered by merging into `main`)
**Created**: 2026-10-06
**Status**: Draft
**Input**: Step 6 — bug `bakeoff-specs-speckitty-qht` ("Setting one agent's model changed another agent's model"). Contract section added: *Aliases*. Sections still in force from steps 1–5: General; Includes; Overrides; In-include; get and show; set PATH VALUE; history [PATH]; watch / reconcile-first; Lineage.

## Intent Summary (confirmed)

A theatre owner shares settings between agents with YAML anchors and aliases and runs `troupe config set PATH VALUE`:

```yaml
defaults: &d
  model: opus
coder:
  settings: *d
reviewer:
  settings: *d
```

Finding: on `main` before this step the file is not loadable at all (exit 4, `anchors and tags are not supported at line 1`), so the reported write cannot occur today. This step makes such files loadable and gives `set` the contract's alias rules.

Contract rules (Aliases section):

- Setting a path whose value is defined at an anchor (`&name`) changes it at the anchor, and so everywhere the alias is used. `set defaults.model sonnet` changes `coder` and `reviewer` too.
- Setting a path reached **through an alias** (`*name`) exits 3; stderr mentions `--expand-alias`. `set coder.settings.model sonnet` is refused and no file changes.
- `set --expand-alias PATH VALUE` replaces that alias with a block-style copy of the anchored node, puts the end-of-line comment `# expanded from *<name> by troupe` on the key's line (two spaces before `#`), and then sets the value in the copy. Nothing else changes; other aliases still refer to the anchor.
- Merge keys (`<<`) are never written.

**Rule that must always hold:** without `--expand-alias`, a `set` on a path reached through an alias changes nothing; only a `set` at the anchored node itself changes a shared value; with it, the only bytes that change are the alias (replaced by the copy and the comment) and the value set.

### Worked example (from the contract)

```yaml
# before                     # after `set --expand-alias coder.settings.model sonnet`
defaults: &d                 defaults: &d
  model: opus                  model: opus
coder:                       coder:
  settings: *d                 settings:  # expanded from *d by troupe
reviewer:                        model: sonnet
  settings: *d               reviewer:
                               settings: *d
```

### Agent choices (out of contract; recorded here, not as contract amendments)

The product owner confirmed these are the agent's choice (discovery, 2026-10-06).

| # | Choice | Why |
|---|--------|-----|
| A-0 | **Merge keys are read with standard YAML merge semantics.** `<<: *a`, `<<: {…}` and `<<: [*a, *b]` merge the referenced mappings into the mapping holding `<<`; keys written in that mapping win, and in a list earlier sources win over later ones. A value that arrives through `<<` is reached through an alias: `set` exits 3 with stderr mentioning `--expand-alias`; `set --expand-alias` on it also exits 3 and stderr says expanding would require writing a merge key, which troupe never does. A key that does not yet exist added directly under the mapping holding `<<` is an ordinary write (step-1 placement) and `<<` is not touched. A `<<` value that is not a mapping, an alias to a mapping, or a list of those → exit 4. Because `<<` is never written, three more writes exit 3 with no file changed (found during implementation): adding a new key named `<<`; replacing as a whole a mapping that holds `<<`; and `--expand-alias` when the copy would contain a `<<` entry. (DM 01M48SQVABR08ZCXGCZD5S8GXV) | This is the meaning every YAML reader gives the file, so reads agree with the user's expectation. Refusing writes through `<<` cannot lose data (TROUPE-002), never writes `<<`, and honours the reporter's "do not silently change anyone else". Writing a local key beside `<<` instead would override a shared value without the explicit opt-in the reporter asked for. |
| C1 | **Reads resolve aliases.** `get`, `show [PATH]`, history leaves and reconcile use resolved values; `show` output contains no `&`, `*` or `<<`. `show --sources` attributes an aliased scalar to the file holding the anchored node. | `show` already prints the effective configuration, not the file text; aliases are a way of writing values, not values. |
| C2 | **Tags (`!tag`) still make a file unloadable (exit 4).** | The contract adds anchors and aliases only; tags keep the step-1 rule. |
| C3 | **Anchors and includes do not mix; anchors only on values.** A file is unloadable (exit 4, stderr names the file and line) if it puts an anchor on an include reference (scalar `file:` string or a `$ref` mapping), on a node that contains an include reference, or on a mapping key; or if it uses an alias as a mapping key. | Aliasing an include would make one include reference reachable from several paths, which neither the Includes/Overrides sections nor this one define; refusing keeps step 5's statement that anchored includes never reach conversion, and cannot corrupt data. Keys must stay plain names for paths to work. |
| C4 | **A value that is itself an alias is reached through an alias.** For `model: *m`, `set coder.model x` exits 3 (mentions `--expand-alias`); with `--expand-alias` the line becomes `model: x  # expanded from *m by troupe`. | The final segment's value is shared; replacing it silently would break the link the user wrote. The contract's expansion rule applied to a scalar gives exactly this line. |
| C5 | **Replacing a whole anchored collection keeps the anchor.** `set defaults '{model: x}'` writes the new value with `&d` kept, so every alias sees it. If the anchor of the replaced value is not on its key's (or dash's) line (`defaults:` with `&d` alone on the next line), the `set` exits 3 and changes no file (research R-9). | Contract rule 1 ("changes it at the anchor, and so everywhere") applied to collections; dropping the anchor would leave dangling aliases and an unloadable file. Moving an anchor off its own line would rewrite a line the user did not ask to change (TROUPE-001). |
| C6 | **New keys follow the same rule.** A new key whose deepest existing ancestor is reached through an alias exits 3 (mentions `--expand-alias`); with `--expand-alias` the key is added to the copy. A new key under the anchored node itself is added there and appears through every alias. | Adding a key under a shared node changes every user of it, exactly like changing a value. |
| C7 | **Nested aliases are expanded outermost first, each with its own comment.** If PATH goes through several aliases (an alias inside an anchored node that is itself reached through an alias), `--expand-alias` expands every alias on PATH, from the root outwards, so the value can be set in a copy; aliases inside a copy that are not on PATH stay aliases. | The value cannot be set otherwise without changing a shared node; aliases off PATH are "other aliases" and still refer to their anchors. |
| C8 | **What the copy contains.** The copy has the anchored node's values; anchors inside the copied node are not copied (their nodes are copied without `&name`); aliases inside it stay aliases; comments inside the anchored node are not copied; scalars keep their written form (quoting/style) where they fit on one line, otherwise the step-1 quoting rules apply; indentation follows the file (step-1 detection). | Copying an anchor would define the name a second time and repoint later aliases to the copy, changing other values. Comments describe the original. Keeping written forms changes the least. |
| C9 | **Where the comment goes / when expansion is refused.** For a list-item alias (`- *d`) the comment goes on the dash line (`-  # expanded from *d by troupe`) and the copy starts on the next line at the item's content column. An alias inside a flow collection (`{settings: *d}`) → exit 3, no file changes (a block copy cannot be written there). If the alias's line already carries an end-of-line comment → exit 3, no file changes. If the alias is not written on its key's (or dash's) line (`settings:` with `*d` on the next line) → exit 3, no file changes. Also exit 3, no file changes (found during implementation): a copy whose last value is a keep-chomping block scalar (`\|+`) followed by more lines (the copy would absorb them); a copy holding an alias whose anchor name is redefined between the anchored node and the alias (the copied alias would refer to a different node); and an alias in an included file when the new key would, by the step-5 rule, be written as an override in another file (C-005: one write of one file; `--in-include` puts the key into the copy). When a value is set on a line the expansion created, the troupe comment there is written with two spaces before `#` (`settings: 5  # expanded from *d by troupe` for `set --expand-alias coder.settings 5`); user comments elsewhere keep their columns. | The contract fixes the comment text; a line can hold one comment, so dropping or merging the user's comment would change their bytes (TROUPE-001). Refusing is the data-safe choice (TROUPE-002); the user can move their comment and retry. The contract puts the comment on the key's line; moving an alias from its own line onto the key's line would rewrite a line the user did not ask to change (DM 01M48T5X483RCHEXYJ60R4N35P). |
| C10 | **`--expand-alias` is accepted only by `set`**, anywhere among its options and combinable with `--reason` and `--in-include`; other subcommands exit 2. On a PATH that is not reached through an alias it has no effect. | Mirrors `--reason` (step 4) and `--in-include` (step 5); the flag only grants permission to expand. |
| C11 | **History records resolved leaves.** A `set` at an anchor records one `set` event per leaf path whose resolved value changed (for the example: `defaults.model`, `coder.settings.model`, `reviewer.settings.model`) in one batch with the `set`'s lineage. An expand-and-set records only the leaves whose resolved values changed (normally just PATH). `watch` and reconcile behave the same for hand edits. | The history section records one event per leaf whose value changes; leaves are resolved paths (C1). |
| C12 | **Earlier behaviour kept.** Files with no anchors, aliases or merge keys behave exactly as in steps 1–5. | Locality of change (DIRECTIVE_024). |
| C13 | **A merge key beside `$ref` makes the file unloadable (exit 4)**, naming the file and path: `coder: {$ref: file:x.yaml, <<: *d}`. (DM 01M48T5X483RCHEXYJ60R4N35P) | Combining YAML merge keys with step-5 overrides has no defined meaning (which wins, and where would a new key go?); refusing at load cannot corrupt anything (TROUPE-002). |
| C14 | **Anchors and aliases in a `set` VALUE are refused (exit 2)**, as tags already are: `set x '*d'` or `set x '&a 1'`. (DM 01M48T5X483RCHEXYJ60R4N35P) | VALUE is one standalone flow node; an alias there could only name an anchor in the file, which the contract does not offer, and writing an anchor from the command line would create sharing nobody asked for. Unchanged from steps 1–5. |

## Domain Language

| Term | Meaning | Avoid |
|---|---|---|
| Anchor | `&name` on a node; the node it marks is the **anchored node** | "label", "variable" |
| Alias | `*name`, a reference to the anchored node | "pointer", "link" |
| Reached through an alias | PATH, or the deepest existing ancestor of a new key, is resolved by passing through an alias or a merge key `<<` (including when the value at PATH is itself an alias) | "shared path" |
| Expand (an alias) | Replace the alias with a block-style copy of the anchored node plus the troupe comment | "inline", "dereference", "unlink" |
| Merge key | `<<` in a mapping, merging referenced mappings into it | "inherit" |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read configuration that uses anchors, aliases and merge keys (Priority: P1)

A theatre owner's file uses anchors, aliases and merge keys; `get`, `show` and `show --sources` show the resolved values.

**Why this priority**: Nothing else in this step works unless such files load; today they exit 4.

**Independent Test**: Fixture theatres with the reporter's file, a scalar alias, a merge key and an alias inside an included file; run reads and compare stdout and exit codes.

**Acceptance Scenarios**:

1. **Given** the reporter's file, **When** `get coder.settings.model` runs, **Then** it prints `opus` and exits 0; `show` prints `coder`/`reviewer` with `settings: {model: opus}` in block form and no `&`, `*` or `<<`.
2. **Given** `base: &b {model: opus, t: 1}` and `coder: {<<: *b, t: 2}`, **When** `get coder.t` and `get coder.model` run, **Then** they print `2` and `opus`.
3. **Given** `coder: {<<: [*a, *b]}` where both define `model`, **When** `get coder.model` runs, **Then** it prints `*a`'s value.
4. **Given** the reporter's file, **When** `show coder --sources` runs, **Then** `model` is attributed to `.troupe/troupe.yml`.
5. **Given** an included file using anchors and aliases internally, **When** reads run, **Then** they resolve as in the root file.
6. **Given** a tag, an anchored include reference (`coder: &c file:x.yaml`), an anchor on a node containing an include, an anchored or aliased key, an undefined alias, `<<: 5`, or `<<` beside `$ref`, **When** any command that loads the configuration runs, **Then** it exits 4, stdout is empty and stderr names the file.

---

### User Story 2 - Change a shared value at its anchor (Priority: P1)

The owner changes the shared value where it is defined; every agent using it follows.

**Why this priority**: The contract's first rule and the purpose of anchors ("changing `defaults.model` changes everyone").

**Independent Test**: Run `set` on anchored paths; compare file bytes; check `get` through each alias and `history`.

**Acceptance Scenarios**:

1. **Given** the reporter's file, **When** `set defaults.model sonnet` runs, **Then** only `opus` on line 2 becomes `sonnet`, `get coder.settings.model` and `get reviewer.settings.model` print `sonnet`, and history records `set` events for `defaults.model`, `coder.settings.model` and `reviewer.settings.model` (C11).
2. **Given** `model: &m opus` and `x: *m`, **When** `set model sonnet` runs, **Then** the line becomes `model: &m sonnet` and `get x` prints `sonnet`.
3. **Given** the reporter's file, **When** `set defaults '{model: x}'` runs, **Then** `defaults` keeps `&d` and `get coder.settings.model` prints `x` (C5).
4. **Given** the reporter's file, **When** `set defaults.temperature 0.2` runs, **Then** the key is added under `defaults` and `get coder.settings.temperature` prints `0.2` (C6).

---

### User Story 3 - Refuse a change that would silently affect others (Priority: P1)

The bug: changing one agent's value through an alias must not change anyone else.

**Why this priority**: This is the reported bug.

**Independent Test**: Run `set` on paths reached through aliases and merge keys; check exit code, stderr, file bytes and history.

**Acceptance Scenarios**:

1. **Given** the reporter's file, **When** `set coder.settings.model sonnet` runs, **Then** it exits 3, stdout is empty, stderr names the path and mentions `--expand-alias`, no file changes and no event is recorded.
2. **Given** `model: *m` under `coder`, **When** `set coder.model x` runs, **Then** exit 3 as above (C4).
3. **Given** the reporter's file, **When** `set coder.settings.temperature 0.2` runs, **Then** exit 3 as above (C6).
4. **Given** `coder: {<<: *d}`, **When** `set coder.model x` runs, **Then** exit 3 mentioning `--expand-alias`; **When** `set --expand-alias coder.model x` runs, **Then** exit 3, stderr says merge keys are never written, no file changes (A-0).
5. **Given** `coder:` / `  <<: *d`, **When** `set coder.temperature 0.2` runs (no `temperature` anywhere in `coder`), **Then** `temperature: 0.2` is added under `coder` and the `<<` line is unchanged (A-0).

---

### User Story 4 - Explicitly give one agent its own copy (Priority: P1)

The owner asks for the alias to be expanded so that agent's value can differ.

**Why this priority**: The contract's way out of the refusal; without it the owner cannot override.

**Independent Test**: Run `set --expand-alias` in fixtures with mapping, scalar, list-item, nested and flow aliases; compare whole files byte-for-byte with expected text.

**Acceptance Scenarios**:

1. **Given** the reporter's file, **When** `set --expand-alias coder.settings.model sonnet` runs, **Then** the file equals the worked example's "after", `get reviewer.settings.model` and `get defaults.model` print `opus`, and history records one `set` event for `coder.settings.model`.
2. **Given** `defaults: &d {model: opus, t: 1}` (flow), **When** `set --expand-alias coder.settings.t 2` runs, **Then** `settings:  # expanded from *d by troupe` is followed by block lines `model: opus` and `t: 2` at the file's indentation.
3. **Given** `coder:` / `  model: *m`, **When** `set --expand-alias coder.model x` runs, **Then** the line becomes `  model: x  # expanded from *m by troupe` (C4).
4. **Given** `agents:` / `  - *d`, **When** `set --expand-alias agents.0.model x` runs, **Then** the item becomes `  -  # expanded from *d by troupe` followed by `    model: x` (C9).
5. **Given** `d` contains `limits: *l` and `coder.settings: *d`, **When** `set --expand-alias coder.settings.limits.max 9` runs, **Then** both aliases on the path are expanded, each line carrying its own comment, and `defaults` and the `l` anchor are unchanged (C7).
6. **Given** the anchored node contains another anchor `&x` and a comment, **When** it is expanded, **Then** the copy has no `&x` and no comment, and aliases `*x` elsewhere still resolve to the original (C8).
7. **Given** `coder: {settings: *d}`, or `settings: *d  # mine`, or `settings:` with `*d` on the next line, **When** `set --expand-alias coder.settings.model x` runs, **Then** exit 3, stderr names the path, no file changes (C9).
8. **Given** a path not reached through an alias, **When** `set --expand-alias PATH VALUE` runs, **Then** the result equals `set PATH VALUE` (C10).
9. **Given** `--expand-alias` passed to `get`, `show`, `history` or `watch`, **When** it runs, **Then** exit 2 with empty stdout (C10).
10. **Given** `set --expand-alias PATH VALUE --reason r`, **When** it succeeds, **Then** lineage is recorded as for any `set`.

### Edge Cases

- An alias used before its anchor is defined is invalid YAML (undefined alias) → exit 4 (FR-002).
- A redefined anchor name (`&a` twice) follows YAML: each alias refers to the most recent definition before it; the copy never adds a definition (C8).
- An anchored node with no aliases behaves like any value; `set` writes keep the anchor.
- A hand edit that only adds or removes an alias without changing resolved leaves records nothing at reconcile; one that changes an anchored value records every changed resolved leaf (C11).
- Anchors are per file: an alias cannot refer to an anchor in another file (YAML rule; undefined alias → exit 4).
- `--expand-alias` together with `--in-include`: `--in-include` first decides where a new key goes (step-5 meaning); only aliases on that route are expanded (an alias on an override side is not expanded under `--in-include`). If the expansion and the key would land in different files, the `set` exits 3 and changes no file (C9, C-005).

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Anchors, aliases and merge keys load | As an owner, a file using anchors, aliases and merge keys loads; reads, history leaves and reconcile use resolved values with YAML merge semantics (A-0, C1); `show` output contains no anchor, alias or merge-key syntax. | High | Open |
| FR-002 | Unsupported anchor uses refused at load | As an owner, loading exits 4 with stderr naming the file when a file uses a tag, anchors or aliases an include reference or a node containing one, anchors or aliases a mapping key, uses an undefined or recursive alias, has a `<<` value that is not a mapping or aliases/list of mappings, or has `<<` beside `$ref` (C2, C3, C13, A-0). | High | Open |
| FR-003 | Set at the anchor | As an owner, `set` on a path whose value is defined at an anchor changes it at the anchor (keeping `&name`, also when a whole collection is replaced), so every alias sees the new value; a new key under the anchored node is added there (C5, C6). | High | Open |
| FR-004 | Refuse through an alias | As an owner, `set` on a path, or on a new key whose deepest existing ancestor is, reached through an alias or a merge key, including a value that is itself an alias, exits 3 with stderr naming the path and mentioning `--expand-alias`; no file changes (C4, C6, A-0). This refusal comes before the no-op rule: an unchanged VALUE through an alias still exits 3; with `--expand-alias` and an unchanged VALUE nothing is written (exit 0). | High | Open |
| FR-005 | Expand then set | As an owner, `set --expand-alias PATH VALUE` replaces each alias on PATH (outermost first) with a block-style copy of its anchored node, puts `  # expanded from *<name> by troupe` at the end of the key's (or list item's dash) line, then sets VALUE in the copy; other aliases still refer to their anchors and no other bytes change (C7, C8, C9). | High | Open |
| FR-006 | Expansion refusals | As an owner, `set --expand-alias` exits 3 and changes no file when the alias to expand is inside a flow collection, its line already has an end-of-line comment, it is not written on its key's or dash's line, PATH arrives through `<<` (stderr says merge keys are never written), the copy would contain `<<`, the copy ends in a `\|+` block followed by more lines, an anchor name used inside the copy is redefined before the alias, or the expansion and a new key would land in different files (C9, A-0). | High | Open |
| FR-007 | Merge keys never written | As an owner, no `set` ever writes, moves or removes a `<<` entry: a new key named `<<`, replacing a whole mapping that holds `<<`, and an expansion whose copy would contain `<<` exit 3; a new key added under a mapping holding `<<` is written as an ordinary key (A-0). | High | Open |
| FR-008 | `--expand-alias` only on `set` | As an owner, `--expand-alias` is accepted only by `set`, combinable with `--reason` and `--in-include`; other subcommands given it exit 2; on a path not reached through an alias it has no effect (C10). | Medium | Open |
| FR-010 | No anchors or aliases in VALUE | As an owner, a `set` VALUE containing an anchor, alias or tag exits 2 and nothing is loaded or changed (C14). | Medium | Open |
| FR-009 | History of shared changes | As an owner, a `set` records one `set` event per resolved leaf whose value changed, with the `set`'s lineage; `watch` and reconcile do the same for hand edits (C11). | High | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | No silent shared changes | In 100% of `set`s without `--expand-alias` on paths reached through an alias or merge key, 0 files change and 0 events are recorded. | Reliability | High | Open |
| NFR-002 | Byte-surgical writes | After any successful `set` (with or without `--expand-alias`), 0 bytes differ in any file beyond those this spec and the step 1–5 write-back rules require (TROUPE-001). | Reliability | High | Open |
| NFR-003 | Refusals change nothing | 100% of `set`s exiting 2, 3, 4 or 5 change 0 configuration files and record 0 events of their own. | Reliability | High | Open |
| NFR-004 | Behaviour coverage | Every functional requirement and agent choice (A-0, C1–C14) has at least one test against real files, the real CLI and the real event store that fails if the behaviour breaks; `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` pass. | Maintainability | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Contract as written | The Aliases section is implemented as written; out-of-contract choices (A-0, C1–C14) are recorded here, never as contract amendments. | Business | High | Open |
| C-002 | Fixed platform | Python 3.12+ with uv; CLI as `uv run troupe config …`; `eventsourcing` event store under `<theatre>/.troupe/`; macOS/Linux only (TROUPE-004). | Technical | High | Open |
| C-003 | Earlier behaviour kept | All step 1–5 behaviour is unchanged for files without anchors, aliases or merge keys (C12). | Technical | High | Open |
| C-004 | Errors name the path or file | Every new error message names the path or file involved (TROUPE-003). | Technical | Medium | Open |
| C-005 | Atomic writes | Every file a `set` changes is replaced atomically (temp file + rename); an expansion and its set are one write of one file. | Technical | High | Open |

### Key Entities

- **Anchored node**: a node marked `&name`; the single place its value lives.
- **Alias**: `*name`; resolves to the most recent anchored node of that name before it in the same file.
- **Merge key**: `<<` whose value contributes keys to the mapping holding it.
- **Resolved configuration**: the tree every read, history leaf and reconcile uses; aliases and merges resolved, each scalar knowing its source file.

## Assumptions

- "Reached through an alias" is evaluated on the resolved configuration, after includes and overrides.
- The file's indentation is detected as in step 1 (default 2).
- YAML 1.1 merge-key semantics are used for `<<` even though files are otherwise read as YAML 1.2, because merge keys exist only in 1.1 and every common reader applies them.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In the reporter's scenario, `set coder.settings.model sonnet` changes 0 files and `reviewer.settings.model` and `defaults.model` still read `opus`.
- **SC-002**: In 100% of anchor scenarios, a change at the anchor is visible through every alias of it.
- **SC-003**: In 100% of `--expand-alias` scenarios, the resulting file matches the expected text exactly and every other alias still resolves to its anchor.
- **SC-004**: Every refused scenario (exit 2, 3 or 4) leaves all files and the history unchanged.
- **SC-005**: 100% of the existing step 1–5 test suite still passes unchanged except tests asserting that anchors and aliases are rejected at load.
