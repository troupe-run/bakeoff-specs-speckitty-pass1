# Mission Specification: troupe configuration: keep shared includes shared

**Mission Branch**: `feat/troupe-config-include-overrides` (delivered by merging into `main`)
**Created**: 2026-10-05
**Status**: Draft
**Input**: Step 5 — two change requests specified together. **CR-A** "keep shared includes shared": contract section added *Overrides* (replaces rule 2 under *set PATH VALUE*, i.e. step-1 FR-011 "new keys go into the file containing the deepest existing ancestor"). **CR-B** "but let me put it in the shared file when I mean to": contract section added *In-include*. Sections still in force from steps 1–4: General; Includes; get and show; set PATH VALUE (other rules); history [PATH]; watch / reconcile-first; Lineage.

## Intent Summary (confirmed)

Included YAML files are shared between projects. A theatre owner (or a harness acting for them) runs `troupe config set PATH VALUE` against a theatre whose sections come from such includes.

- **Mapping-form includes.** An include may be written as a mapping whose `$ref` key holds the include string; its other keys are **overrides**. The value is the included content deep-merged with the overrides: mappings merge recursively; scalars and lists in the override replace. `get`, `show` and `show --sources` all see the merged value; history and reconcile treat merged leaves like any others.
- **New keys become overrides (CR-A).** A new key whose deepest existing ancestor comes from an included file is written as an override in the **including file** — the file holding the include reference nearest that ancestor (for nested includes this may itself be an included file; DM 01M46FYYFFXXZE893KWDP2WJCW). A scalar-form include is first converted to mapping form, keeping any end-of-line comment on the key's line. The shared file is not touched.
- **Explicit opt-in (CR-B).** `set --in-include PATH VALUE` writes a new key into the included file instead — the step-1 rule.
- **Existing values change where they live.** An overridden value changes in its override; a value that is not overridden changes in the file it comes from. `--in-include` has no effect on existing values (DM 01M46G22P50PEX048YGJ9TV5N8, cancelled because the contract answers it).
- **Lists.** Appending a list item, or adding a key inside a list item, is written in the file that holds the list — overrides cannot address list items.
- **Errors.** A mapping-form include of a non-YAML file with sibling keys exits 4 (contract). A `$ref` whose value is not an include string exits 4 (agent choice, DM 01M46G0570NBW27MB152E1ZQ8K). Replacing a whole include still exits 3.

**Rule that must always hold:** without `--in-include`, adding a new key never changes a byte of the included file that holds the key's deepest existing ancestor; every file changes only where the write-back rules require (TROUPE-001).

### Worked example (from the contract)

```yaml
# .troupe/troupe.yml, before            # after `set coder.temperature 0.3`
coder: file:agents/coder.yaml  # c      coder:  # c
                                          $ref: file:agents/coder.yaml
                                          temperature: 0.3
```

`agents/coder.yaml` is unchanged. With `set --in-include coder.temperature 0.3`, `troupe.yml` is unchanged and `temperature: 0.3` is appended to `agents/coder.yaml`.

### Agent choices (out of contract; recorded here, not as contract amendments)

| # | Choice | Why |
|---|--------|-----|
| D-1 | **Malformed `$ref` → exit 4.** A mapping with a `$ref` key whose value is not a string starting `file:` (e.g. `$ref: 5`, `$ref: agents/coder.yaml`, `$ref: [a]`) makes the configuration unloadable: exit 4, stderr names the file and the `$ref` path. (DM 01M46G0570NBW27MB152E1ZQ8K) | The user evidently meant an include; treating it as data would silently drop the include, and `set` could then write "overrides" against a non-include. Refusing cannot lose data (TROUPE-002). |
| D-2 | **`$ref` is written first** when a scalar-form include is converted; override keys follow it. | Matches the contract example; reads as "this, plus these changes". |
| D-3 | **Flow-style parent → flow-style mapping form.** `agents: {coder: file:x.yaml}` becomes `agents: {coder: {$ref: file:x.yaml, temperature: 0.3}}`. | Same rule step 1 uses for new collections under a flow parent (step-1 FR-016); block lines cannot appear inside a flow collection. |
| D-4 | **An include that is a list item is converted the same way.** `- file:a.yaml` becomes `- $ref: file:a.yaml` with the override key on the next line at the item's content column. | The item is itself the include reference, and the file holding the list holds that reference, so the contract's conversion rule and its list rule agree. Items *inside* an included list are not affected: keys under them go to the file holding that list. |
| D-5 | **Conversion moves the include string's bytes verbatim** (including its quoting) to the `$ref:` line, and keeps the bytes between the removed value and `#` (two spaces in the contract example) so the comment follows the key, as in `coder:  # c`. | Byte preservation (TROUPE-001): the only change is the one the rule requires. |
| D-6 | **Override keys may not be named `$ref`.** A `set` whose PATH has a `$ref` segment exits 3 and changes no file; `get`/`show` of such a path exits 5 (the merged value has no `$ref` key). | Writing a `$ref` key would silently turn a mapping into an include or retarget one; refusing is the data-safe choice. |
| D-7 | **Overrides on non-mapping YAML content → exit 4.** A mapping-form include with sibling keys whose YAML target's content is not a mapping (a list, scalar, or empty document) exits 4 naming the target file. Inside the merge, where only one side is a mapping, the override value replaces the included one. | Deep-merging keys into a list or scalar has no meaning; replacing the whole included content would make the include pointless. Nested replacement follows "override wins". |
| D-8 | **Ancestor defined by both include and override.** When the deepest existing ancestor mapping already has an override mapping in the including file, the new key is added to that override mapping. With `--in-include`, the new key goes into the innermost included file that defines the ancestor; if only an override defines it, into the file holding that override. | Both are the contract rule applied to merged mappings; `--in-include` exists precisely to target the included file. |
| D-9 | **`--in-include` is accepted only by `set`**, anywhere among its options like `--reason`; other subcommands exit 2. It has no effect on existing values, list appends or keys inside list items. | Mirrors `--reason` (step 4); the contract scopes the flag to writing a new key. |

## Domain Language

| Term | Meaning | Avoid |
|---|---|---|
| Include reference | The `file:` string that names an include target, in scalar form or as a `$ref` value | "import" (reserved for history), "link" |
| Scalar form | An include written as a plain string value: `coder: file:agents/coder.yaml` | "short form" |
| Mapping form | An include written as a mapping with a `$ref` key holding the include string, plus optional overrides | "long form", "ref block" |
| Override | A key beside `$ref` in a mapping-form include; its value is deep-merged over the included content | "patch", "local value" |
| Including file | The file that contains the include reference | "parent file", "owner" |
| Included file | The include's target file (shared between projects) | "child file", "shared config" as a technical term |
| Deepest existing ancestor | The longest prefix of PATH that already exists in the merged configuration | |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Read configuration that uses mapping-form includes (Priority: P1)

A theatre owner writes an include in mapping form with overrides and reads the result with `get`, `show` and `show --sources`.

**Why this priority**: Every write rule in this step depends on mapping-form includes loading correctly.

**Independent Test**: A fixture theatre with `coder: {$ref: file:agents/coder.yaml, temperature: 0.3, tools: {web: true}}` where `agents/coder.yaml` holds `model: gpt`, `temperature: 0.7`, `tools: {shell: true}`, `stop: [a, b]`; run `get`/`show`/`show --sources` and compare stdout and exit codes.

**Acceptance Scenarios**:

1. **Given** the fixture, **When** `get coder.temperature` runs, **Then** it prints `0.3`; `get coder.model` prints `gpt`.
2. **Given** the fixture, **When** `show coder` runs, **Then** it prints the merged mapping with `tools` holding both `shell: true` and `web: true` and no `$ref` key.
3. **Given** an override `stop: [c]`, **When** `show coder.stop` runs, **Then** it prints only `- c` (lists replace).
4. **Given** the fixture, **When** `show coder --sources` runs, **Then** `temperature` and `tools.web` are attributed to `.troupe/troupe.yml` and `model` and `tools.shell` to `.troupe/agents/coder.yaml`.
5. **Given** `coder: {$ref: file:agents/coder.yaml}` with no overrides, **When** any read runs, **Then** output equals that for `coder: file:agents/coder.yaml`; `prompt: {$ref: file:p.md}` is the text of `p.md`.
6. **Given** `prompt: {$ref: file:p.md, x: 1}`, or `coder: {$ref: 5}`, or a `$ref` YAML target whose content is a list and that has sibling keys, **When** any command that loads the configuration runs, **Then** it exits 4, stdout is empty and stderr names the file.

---

### User Story 2 - Add a setting under a shared section without touching the shared file (Priority: P1)

A theatre owner adds a new setting under a section that comes from a shared include. The setting is written as an override in the including file; the shared file is byte-for-byte unchanged.

**Why this priority**: This is the purpose of CR-A.

**Independent Test**: Run `set` for new keys in fixtures with scalar-form, mapping-form, flow-style, list-item and nested includes; compare every file's bytes before and after; check `get` and `history`.

**Acceptance Scenarios**:

1. **Given** `coder: file:agents/coder.yaml  # c` in `troupe.yml`, **When** `set coder.temperature 0.3` runs (no `temperature` in `coder.yaml`), **Then** `troupe.yml` reads `coder:  # c` / `  $ref: file:agents/coder.yaml` / `  temperature: 0.3`, `coder.yaml` is byte-identical, and history records one `set` event for `coder.temperature`.
2. **Given** a file indented with 4 spaces, **When** a scalar-form include is converted, **Then** `$ref` and the override are indented 4 spaces beyond the key.
3. **Given** a mapping-form include already having overrides, **When** a new key is set, **Then** it is appended after the last override per the step-1 placement rule and no conversion happens.
4. **Given** `coder.yaml` holds `limits: {max: 5}`, **When** `set coder.limits.min 1` runs, **Then** the override `limits:` / `min: 1` is created inside `coder`'s mapping form in `troupe.yml`; `get coder.limits.max` still prints `5`.
5. **Given** `troupe.yml` → `coder: file:agents/coder.yaml` and `coder.yaml` → `model: file:models/base.yaml`, **When** `set coder.model.temperature 0.3` runs, **Then** `agents/coder.yaml` gets `model:` / `$ref: file:models/base.yaml` / `temperature: 0.3` in block form, and `troupe.yml` and `base.yaml` are byte-identical.
6. **Given** `agents: {coder: file:x.yaml}`, **When** `set agents.coder.t 1` runs, **Then** the line becomes `agents: {coder: {$ref: file:x.yaml, t: 1}}` (D-3).
7. **Given** a block list `list:` whose item is `- file:a.yaml`, **When** `set list.0.k 1` runs, **Then** the item becomes `- $ref: file:a.yaml` with `k: 1` on the next line (D-4) and `a.yaml` is unchanged.
8. **Given** a new key whose deepest existing ancestor is in the root file itself, **When** `set` runs, **Then** it is written there as in step 1.

---

### User Story 3 - Change existing settings and lists where they live (Priority: P1)

Existing values and lists keep the step-1 behaviour: they change in the file that holds them, which may be an override or the shared file.

**Why this priority**: The contract keeps this rule; getting it wrong would write a duplicate value.

**Independent Test**: Fixture with overridden and non-overridden values and included lists; run `set` on each and compare files.

**Acceptance Scenarios**:

1. **Given** `coder: {$ref: file:agents/coder.yaml, temperature: 0.3}` and `temperature: 0.7` in `coder.yaml`, **When** `set coder.temperature 0.5` runs, **Then** only the override changes to `0.5`; `coder.yaml` is byte-identical.
2. **Given** `model: gpt` only in `coder.yaml`, **When** `set coder.model claude` runs, **Then** `coder.yaml` changes and `troupe.yml` is byte-identical.
3. **Given** `stop: [a, b]` only in `coder.yaml`, **When** `set coder.stop.2 c` runs, **Then** the item is appended in `coder.yaml`.
4. **Given** `steps: [{name: x}]` only in `coder.yaml`, **When** `set coder.steps.0.retry 2` runs, **Then** `retry: 2` is written in `coder.yaml`.
5. **Given** an override list `stop: [c]` in `troupe.yml`, **When** `set coder.stop.1 d` runs, **Then** the item is appended in `troupe.yml`.
6. **Given** a scalar- or mapping-form include at `coder`, **When** `set coder '{a: 1}'` runs, **Then** exit 3 and no file changes (step 1). **When** `set coder.$ref x` runs, **Then** exit 3 and no file changes (D-6).

---

### User Story 4 - Deliberately put a new setting in the shared file (Priority: P2)

When a new setting really belongs to every project using the shared file, the owner says so with `--in-include`.

**Why this priority**: CR-B; an explicit escape hatch from CR-A.

**Independent Test**: Repeat the User Story 2 fixtures with `--in-include`; compare files; check exit codes for `--in-include` on other subcommands.

**Acceptance Scenarios**:

1. **Given** `coder: file:agents/coder.yaml  # c`, **When** `set --in-include coder.temperature 0.3` runs, **Then** `temperature: 0.3` is appended in `coder.yaml` and `troupe.yml` is byte-identical.
2. **Given** the nested fixture of US2-5, **When** `set --in-include coder.model.temperature 0.3` runs, **Then** the key is written in `models/base.yaml` and both other files are byte-identical.
3. **Given** an ancestor defined only in the root file, **When** `set --in-include a.b 1` runs, **Then** the result equals `set a.b 1`.
4. **Given** an overridden existing value, **When** `set --in-include coder.temperature 0.5` runs, **Then** the override changes, exactly as without the flag.
5. **Given** `--in-include` passed to `get`, `show`, `history` or `watch`, **When** it runs, **Then** exit 2 with empty stdout.
6. **Given** `set --in-include PATH VALUE --reason r`, **When** it succeeds, **Then** lineage is recorded as for any `set`.

### Edge Cases

- `$ref` target missing, or an include cycle through `$ref` → exit 4 (step-1 rule, both forms).
- Overrides may themselves contain includes (scalar or mapping form); they resolve as usual.
- An override whose value is a mapping where the included value is a scalar (or vice versa) replaces it (D-7).
- A hand edit that converts an include to mapping form without changing any merged leaf records nothing at reconcile; a hand edit adding an override records the changed leaves as `set` events (step 2).
- A `set` that converts an include to mapping form records exactly the leaf it adds; no `remove`/`set` events for unchanged merged leaves.
- `watch` and reconcile see changes in any file reachable through `$ref` exactly as through scalar-form includes.

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Mapping-form include | As an owner, a mapping with a `$ref` key whose value is an include string is an include in mapping form; its other keys are overrides; with no overrides it behaves exactly like the scalar form (YAML or text target). | High | Open |
| FR-002 | Deep merge | As an owner, a mapping-form include's value is the included content deep-merged with the overrides: mappings merge recursively, keys in file order with included keys first and new override keys after; where an override value is a scalar or list, or either side is not a mapping, the override replaces (D-7). | High | Open |
| FR-003 | Load errors | As an owner, loading exits 4 with stderr naming the file when: a mapping-form include of a non-YAML target has sibling keys; a `$ref` value is not an include string (D-1); a YAML target with sibling keys has non-mapping content (D-7); a `$ref` target is missing or forms a cycle. | High | Open |
| FR-004 | Reads see merged values | As an owner, `get`, `show [PATH]` and the history/reconcile leaves use the merged configuration; no `$ref` key appears in output; `show --sources` attributes each scalar to the file whose bytes define it (an override's scalar to the including file). | High | Open |
| FR-005 | New key under an include becomes an override | As an owner, a `set` whose PATH is a new key and whose deepest existing ancestor comes from an included file writes the key, and any missing intermediate mappings, as an override in the including file — the file holding the include reference nearest that ancestor; the included file is not modified. | High | Open |
| FR-006 | Scalar-form conversion | As an owner, before adding the first override a scalar-form include is converted to mapping form at the file's indentation: the key's line keeps its end-of-line comment, `$ref` comes first with the include string's bytes verbatim, overrides follow (D-2, D-5); under a flow parent the mapping form is written in flow style (D-3); a list-item include is converted in place (D-4). | High | Open |
| FR-007 | Existing overrides extended | As an owner, a new key whose ancestor already has an override mapping is added to that override mapping using the step-1 placement and quoting rules (D-8). | High | Open |
| FR-008 | Existing values change where they live | As an owner, `set` on an existing overridden value changes the override; on an existing value that is not overridden it changes the file the value comes from (step-1 rules unchanged). | High | Open |
| FR-009 | Lists stay in their file | As an owner, appending a list item, and adding a new key inside a list item, is written in the file that holds the list. | High | Open |
| FR-010 | `set --in-include` | As an owner, `set --in-include PATH VALUE` writes a new key into the file that holds its deepest existing ancestor (the step-1 rule), preferring the innermost included file that defines it (D-8); it does not change where existing values, list appends or keys inside list items are written (D-9). | High | Open |
| FR-011 | `--in-include` only on `set` | As an owner, `--in-include` is accepted only by `set`, combinable with `--reason`; any other subcommand given it exits 2. | Medium | Open |
| FR-012 | Include replacement and `$ref` paths refused | As an owner, replacing a whole include (either form) still exits 3; a `set` PATH with a `$ref` segment exits 3; in both cases no file changes (D-6). | High | Open |
| FR-013 | History unchanged in shape | As an owner, a `set` that adds an override records one `set` event per leaf it creates with the usual lineage; converting to mapping form records nothing by itself; reconcile compares merged leaves. | High | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Shared files untouched | In 100% of new-key `set`s without `--in-include` whose ancestor comes from an include, the included file's bytes are identical before and after. | Reliability | High | Open |
| NFR-002 | Byte-surgical writes | After any successful `set`, 0 bytes differ in any file beyond those this spec and the step-1 write-back rules require (TROUPE-001). | Reliability | High | Open |
| NFR-003 | Refusals change nothing | 100% of `set`s exiting 2, 3, 4 or 5 change 0 configuration files and record 0 events of their own. | Reliability | High | Open |
| NFR-004 | Behaviour coverage | Every functional requirement and agent choice has at least one test against real files, the real CLI and the real event store that fails if the behaviour breaks; `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` pass. | Maintainability | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Contract as written | The Overrides and In-include sections are implemented as written; out-of-contract choices (D-1…D-9) are recorded here and in project docs, never as contract amendments. | Business | High | Open |
| C-002 | Fixed platform | Python 3.12+ with uv; CLI as `uv run troupe config …`; `eventsourcing` event store under `<theatre>/.troupe/`; macOS/Linux only (TROUPE-004). | Technical | High | Open |
| C-003 | Earlier behaviour kept | All step 1–4 behaviour (quoting, placement, comments, folded values, history, lineage, reconcile, watch, exit codes) is unchanged except the new-key rule replaced by FR-005/FR-010 and the additions above. Theatres without `$ref` keys behave exactly as before, except new keys under scalar-form includes. | Technical | High | Open |
| C-004 | Errors name the file | Every new error message names the path or file involved (TROUPE-003). | Technical | Medium | Open |
| C-005 | Atomic writes | Every file a `set` changes is replaced atomically (temp file + rename); a conversion and its override are one write of one file. | Technical | High | Open |

### Key Entities

- **Include reference**: the `file:` string, in scalar form or as a `$ref` value, held in an including file; points to an included file.
- **Mapping-form include**: `$ref` plus overrides; its value is the deep merge of included content and overrides.
- **Override**: a key (possibly nested) in a mapping-form include; source file is the including file.
- **Merged configuration**: the tree every read, history leaf and reconcile uses; each scalar knows its source file.

## Assumptions

- "Deepest existing ancestor" is evaluated on the merged configuration.
- The file's indentation is detected as in step 1 (default 2).
- Merged key order for `show` is included keys in included-file order, then override-only keys in override order.
- Existing `$ref` keys in users' files before this step are assumed to be intended as includes; D-1 makes any non-include `$ref` value a load error rather than silently data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of acceptance scenarios that add a new key under a shared section without `--in-include`, the shared file is byte-identical afterwards.
- **SC-002**: In 100% of `--in-include` scenarios, the new key lands in the included file and every other file is byte-identical.
- **SC-003**: For every override fixture, reading a setting returns the override where one exists and the included value otherwise, with the correct source file shown.
- **SC-004**: Every malformed include in the scenarios is rejected with exit 4 (load) or 3 (write) and leaves all files and the history unchanged.
- **SC-005**: 100% of the existing step 1–4 test suite still passes, adjusted only where the new-key rule changed by contract.
