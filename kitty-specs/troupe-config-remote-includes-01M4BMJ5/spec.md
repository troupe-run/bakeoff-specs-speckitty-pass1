# Mission Specification: troupe configuration: remote includes and a schema

**Mission Branch**: `feat/troupe-config-remote-includes` (delivered by merging into `main`)
**Created**: 2026-10-07
**Status**: Draft
**Input**: Step 7 — "remote includes and a schema". Contract section added: *Remote includes and schema*. Sections still in force from steps 1–6: General; Includes; set PATH VALUE; history [PATH]; Sync with files (watch / reconcile-first); get and show; Lineage; Overrides; In-include; Aliases.

## Intent Summary (confirmed)

A theatre owner whose team shares configuration from a URL writes, for example:

```yaml
# .troupe/troupe.yml
team: https://cfg.example.com/team.yaml
coder:
  $ref: https://cfg.example.com/coder.yaml
  temperature: 0.3
webhook: https://hooks.example.com/notify   # a URL setting, not an include
```

and keeps a JSON Schema at `.troupe/troupe.schema.json` that marks `webhook` with `"format": "uri"`. They run `troupe config get|show|set|history|watch`.

Contract rules (Remote includes and schema section):

- A string starting `https://` or `http://` is also an include. It is fetched when the configuration loads: YAML if the URL path ends `.yml`/`.yaml`, otherwise text. A failed fetch → exit 4.
- Changing a value that comes from a remote include → exit 3; stderr contains the include string exactly as written in the local file. New keys under a remote include become local overrides (step 5).
- `<dir>/.troupe/troupe.schema.json` (JSON Schema 2020-12), if present, describes the configuration. A string whose schema (found through `properties`, `items` and `additionalProperties`) has `"format": "uri"` is a literal, not an include. A string tagged `!literal` is a literal.
- The loaded configuration must validate against the schema, else exit 4. A `set` that would make it invalid → exit 3.
- `set PATH VALUE`, where VALUE is a string that would be read as an include and the schema does not mark PATH as `format: uri`, writes it tagged `!literal`, unless `--include` is given.

**Rule that must always hold:** no troupe command writes, or causes a write to, content that comes from a remote include. Every `set` that exits 2, 3 or 4 changes no file and records no event.

### Agent choices (out of contract; recorded here, not as contract amendments)

The product owner confirmed (discovery, 2026-10-07) that S-1 to S-12 are behaviour the contract leaves open and so are the agent's choice. S-13 follows from the contract.

| # | Choice | Why |
|---|--------|-----|
| S-1 | **Includes inside remote content resolve against the URL.** A `file:` include inside fetched content names a target relative to that URL (standard relative-URL resolution: `file:prompts/sys.md` inside `https://cfg.example.com/team.yaml` is `https://cfg.example.com/prompts/sys.md`) and is fetched. Nested `https://`/`http://` includes are allowed. A cycle of URLs → exit 4 naming the URLs, as for files. Everything reached through a remote include is remote. A reference that resolves outside http(s) is refused (exit 4); a scheme-relative one such as `file://host/x` resolves to `http(s)://host/x` by standard URL rules, which gives nothing a remote file could not name directly. (DM 01M4BMKNXT8SSZTQ8ZX7H562MN) | It keeps the step-1 meaning of a relative include ("relative to the file containing it") for remote files, so a team can split its shared configuration the same way it splits local files. A shared file cannot sensibly point at a path on each user's disk. |
| S-2 | **Fetching.** Every load fetches every remote include anew, with no cache between runs; one URL is fetched at most once per load. Each fetch has a 10-second timeout, follows redirects (to `http`/`https` only), verifies TLS certificates and sends no credentials. The body must be strict UTF-8 and is used without newline translation. YAML or text is decided by the URL's path (query and fragment ignored), with the same case-sensitive `.yml`/`.yaml` test as local includes. A network error, timeout, non-2xx status or non-UTF-8 body → exit 4; stderr names the URL and the location holding the include: the local file, or the remote URL for an include inside remote content (S-1; aligned with contracts/cli.md after the post-merge review, D-3). | Files are already read fresh on every run (step 1); a cache could show stale shared values. A timeout keeps a dead server from hanging every command. Refusing an unverified or undecodable response cannot corrupt anything (TROUPE-002). |
| S-3 | **Mapping form accepts remote includes.** `$ref` may hold an `https://`/`http://` string, with or without overrides; the step-5 rules apply unchanged (overrides on a non-YAML remote target → exit 4). A `$ref` value is always an include: the schema does not make it a literal, and `!literal` on a `$ref` value → exit 4. | The contract says new keys under a remote include become local overrides, which needs the mapping form. A `$ref` that is not an include was already refused in step 5 (D-1). |
| S-4 | **What "read-only" covers.** Each of these exits 3 and changes no file: changing an existing value that comes from remote content (YAML or text); replacing as a whole a value that is a remote include or comes from remote content; `--in-include` when the included file is remote; appending to a list in remote content, or adding a key inside an item of such a list; `--expand-alias` of an alias in remote content. Stderr names PATH, contains the include string exactly as written in the local file, and says to change that include line instead. For nested remote includes the reported include is the outermost one, the one written in a local file. A value from a local override of a remote include is local and is changed in its override as in step 5. | These are every write the earlier steps would otherwise land in the remote content. The contract asks troupe to tell the user which include line to change; only a line in a local file can be changed. |
| S-5 | **New keys under a remote include become overrides** in the local including file, converting a scalar-form include to mapping form exactly as in step 5. The step-6 alias rule still applies (a new key whose deepest existing ancestor is reached through an alias exits 3). | The contract states it; step 5 defines the conversion; the step-6 ruling (C6) says the alias rule does not depend on which file a write lands in. |
| S-6 | **History, watch and sources.** Leaves from remote content are leaves like any other: `get`, `show`, `history` and reconcile use them, and a reconcile records upstream changes it sees as file-lineage events (actor unknown). `watch` does not poll URLs: it reconciles when a local watched file or the schema file changes, and picks up remote changes then. `show --sources` attributes a remote scalar to its resolved URL. While the configuration cannot be loaded, `watch` keeps the step-3 rule of retrying on every tick, so a failing remote include is fetched again on each retry, each bounded by the 10-second deadline (added after analysis finding I1). | Remote values are part of the configuration, so the history must account for them; polling a server on a timer is behaviour nobody asked for. The schema file can change what is a literal, so it must trigger a reconcile. |
| S-7 | **Schema lookup.** For a string at configuration path P, the schema is found by walking P's segments from the root schema: a mapping key `k` → `properties[k]` if present, else `additionalProperties` if it is a schema object; a list index → `items` if it is a schema object. Nothing else is followed (`$ref`, `allOf`/`anyOf`/`oneOf`, `patternProperties`, `prefixItems`, `if`/`then`); then no format is found. Only `"format": "uri"` counts. P is the path at which the string appears in the resolved configuration; for a string reached through an alias it is the path of the anchored node. | The contract names exactly these three keywords. Following more would guess at the meaning of combinators. The anchored node is where the string is written, so its meaning cannot differ from alias to alias. |
| S-8 | **Schema handling.** The schema file is read fresh on every load as strict UTF-8 JSON. It must be a valid JSON Schema 2020-12 document (a `$schema`, if present, must name 2020-12) whose `$ref`s are all fragments within the file. Otherwise → exit 4 naming the schema file. `format` is an annotation and is not asserted. The instance validated is the resolved configuration (includes fetched and read, overrides and merge keys applied, aliases resolved, `!literal` strings and text includes as strings). A failure → exit 4; stderr names the schema file and the configuration path of the first failure. No schema file → no validation and no literal-by-schema. | Validating what every read sees matches "the loaded configuration must validate". JSON Schema 2020-12 treats `format` as an annotation by default. Not fetching schema references keeps loading offline-safe and predictable. |
| S-9 | **`set` and the schema.** A `set` whose resulting configuration fails validation exits 3; stderr names PATH and the schema file; no file changes and no event is recorded. | The contract; refusing before writing cannot corrupt anything (TROUPE-002). |
| S-10 | **`!literal` in files.** `!literal` is allowed on a scalar of any style; the value is the scalar's text as a string (`!literal 5` is the string `5`). `!literal` on a mapping or list → exit 4. Every other tag still → exit 4 (step 6 C2). `get` and `show` print the string without the tag; `show` output contains no `!literal`. An anchor may sit on a `!literal` string (it is not an include reference). `!literal` on a mapping key → exit 4 naming the file and line (keys are never includes; added after analysis finding U1). | The contract makes `!literal` mean "take this string literally"; only scalars are strings. Reads print values, not file syntax (step 6 C1). |
| S-11 | **How `set` writes include-looking strings.** The S-13 rule applies to every string in VALUE: a string VALUE, and each string inside a mapping or list VALUE, each judged at its own resulting path. A tagged string is written as `!literal ` followed by the string exactly as step 1 would write it. When the value replaced at a path already carried `!literal` and the new value is a string, the tag is kept. Writing a local text include's content (step 1) writes file text, not YAML, and is never tagged. Tags in VALUE itself are still refused (exit 2). | A nested string would otherwise become an include nobody asked for, contrary to the contract's purpose. Keeping an existing tag keeps the user's stated intent and changes the fewest bytes (TROUPE-001). |
| S-12 | **`--include`.** Accepted only by `set`, anywhere among its options and combinable with `--reason`, `--in-include` and `--expand-alias`; other subcommands given it exit 2. With it, include-looking strings in VALUE are written untagged and so are includes; an existing `!literal` tag on a replaced value is removed (added after analysis finding U2). On a VALUE with no include-looking string it has no effect. A `set --include` whose new include cannot be read or fetched exits 3 (as step 1 refuses a missing include target). If the schema marks the string's path `format: uri`, `--include` exits 3, because the string would be a literal anyway. | Mirrors `--in-include` and `--expand-alias`. Writing an include the configuration cannot load would make it unloadable; refusing a request that cannot be honoured is the conservative choice (TROUPE-002). |
| S-13 | **Include-looking strings are written literal by default** (contract). `set b file:p.md` now writes `b: !literal file:p.md`, where step 1 wrote an include. The step-1 behaviour needs `set --include b file:p.md`. | Follows from the Remote includes and schema section. |
| S-14 | **A fetched body is at most 1 MiB** (added after delivery, bead 1j5.3; product owner 2026-10-08: out of contract, agent's choice). A larger body is a failed fetch: exit 4, stderr `cannot fetch <url> (included from <location>, at <path>): larger than 1 MiB, the limit for a remote include`. The limit is checked against `Content-Length` and again while reading, so an undeclared or false length cannot get past it. | Configurations are small (under 1,000 leaves in under 50 files), so a real include is a few kilobytes and 1 MiB is far above it. Reading an unbounded body into memory could exhaust it; refusing cannot lose or corrupt data (TROUPE-002), and a failed fetch is already contracted as exit 4. |
| S-15 | **A redirect from `https` to `http` is a failed fetch** (exit 4, `redirect to <url> refused (https may not redirect to http)`; added after delivery, bead 1j5.4, agent's choice). Every hop is checked; `http` → `https` and same-scheme redirects are followed. | The owner asked for an encrypted source; following a downgrade would silently drop that protection. Refusing is the conservative choice (TROUPE-002); an owner who wants plain http writes an `http://` include. |
| S-16 | **No warning for `http://` includes** (bead 1j5.4, agent's choice). | The contract makes `http://` a first-class include, written deliberately by the owner. A warning on every load would add stderr noise to every successful `get`/`show`/`set` that harnesses read, with no contract basis; stdout is untouched either way. |

## Domain Language

| Term | Meaning | Avoid |
|---|---|---|
| Remote include | An include whose include string starts `https://` or `http://` | "import" (reserved for history), "remote file" |
| Local include | An include whose include string starts `file:` and resolves to a file on disk | |
| Remote content | Everything reached through a remote include, including what its own includes bring in (S-1) | "shared config" as a technical term |
| Include-looking string | A string that would be read as an include: it starts `file:`, `https://` or `http://` | "URL string" |
| Literal | A string that is never an include: tagged `!literal`, or its schema has `"format": "uri"` | "escaped", "raw" |
| Schema | `<dir>/.troupe/troupe.schema.json`, a JSON Schema 2020-12 document | "spec" |

## User Scenarios & Testing *(mandatory)*

Tests serve remote content from a local HTTP server started by the test, so they need no outside network.

### User Story 1 - Read configuration that includes shared team settings from a URL (Priority: P1)

The owner includes a team file by URL and reads the result as if it were local.

**Why this priority**: Every other part of this step depends on remote includes loading.

**Independent Test**: A fixture theatre including YAML and text from a test HTTP server; run `get`, `show`, `show --sources` and `history`; compare stdout and exit codes.

**Acceptance Scenarios**:

1. **Given** `team: http://127.0.0.1:<port>/team.yaml` serving `model: opus`, **When** `get team.model` runs, **Then** it prints `opus` and exits 0.
2. **Given** `prompt: http://127.0.0.1:<port>/sys.md?v=2`, **When** `get prompt` runs, **Then** it prints the body exactly (text, because the URL path does not end `.yml`/`.yaml`).
3. **Given** `coder: {$ref: http://…/coder.yaml, temperature: 0.3}` where the remote file has `temperature: 0.7` and `model: gpt`, **When** reads run, **Then** `temperature` is `0.3` and `model` is `gpt`; `show coder --sources` attributes `model` to the URL and `temperature` to `.troupe/troupe.yml` (S-3, S-6).
4. **Given** a remote `team.yaml` containing `prompt: file:prompts/sys.md` and `extra: http://…/x.yaml`, **When** `get team.prompt` runs, **Then** it prints the body served at `…/prompts/sys.md` (S-1).
5. **Given** a URL returning 404, a server that does not answer within 10 s, a non-UTF-8 body, or a URL cycle, **When** any command that loads the configuration runs, **Then** it exits 4, stdout is empty and stderr names the URL and the local file (S-2, S-1).
6. **Given** an imported theatre whose remote value changes upstream, **When** a command other than `history` runs, **Then** one `set` event with file lineage is recorded for the changed leaf (S-6).

---

### User Story 2 - Be told which include line to change (Priority: P1)

The owner tries to change a shared value; troupe refuses and points at the include line.

**Why this priority**: Remote content is read-only; a refusal without directions leaves the owner stuck.

**Independent Test**: Run `set` on remote-sourced paths; check exit code, stderr, file bytes and history.

**Acceptance Scenarios**:

1. **Given** `team: https://cfg.example.com/team.yaml` (served locally in tests as `http://…`), **When** `set team.model sonnet` runs, **Then** it exits 3, stdout is empty, stderr names `team.model` and contains the include string exactly as written in `troupe.yml`, no file changes and no event is recorded.
2. **Given** a remote text include `prompt: http://…/sys.md`, **When** `set prompt "x"` runs, **Then** exit 3 as above (S-4).
3. **Given** remote content with a list `tools`, **When** `set team.tools.2 x`, `set --in-include team.newkey 1` or `set team '{a: 1}'` runs, **Then** exit 3 as above (S-4).
4. **Given** a remote file that itself includes another URL, **When** a value from the inner file is set, **Then** stderr contains the outermost include string, the one in the local file (S-4).
5. **Given** `coder: {$ref: http://…/coder.yaml, temperature: 0.3}`, **When** `set coder.temperature 0.5` runs, **Then** only `0.3` becomes `0.5` in `troupe.yml` (S-4).

---

### User Story 3 - Add a local override under a remote include (Priority: P1)

The owner adds a setting under a shared section; it becomes a local override.

**Why this priority**: The contract's way to customise shared configuration.

**Independent Test**: Run `set` adding new keys under scalar-form and mapping-form remote includes; compare whole files byte-for-byte.

**Acceptance Scenarios**:

1. **Given** `team: http://…/team.yaml  # shared`, **When** `set team.temperature 0.3` runs, **Then** `troupe.yml` becomes `team:  # shared` / `  $ref: http://…/team.yaml` / `  temperature: 0.3` and `get team.temperature` prints `0.3` (S-5).
2. **Given** a mapping-form remote include with overrides, **When** a new key is set, **Then** it is added beside the existing overrides.

---

### User Story 4 - URL settings stay strings (Priority: P1)

The owner keeps settings that are URLs, marked in the schema or tagged `!literal`, without troupe fetching them.

**Why this priority**: Without this, every URL setting would be fetched and fail to load.

**Independent Test**: Fixtures with a schema marking `format: uri` at various depths and with `!literal` strings; reads must not contact the server; compare output.

**Acceptance Scenarios**:

1. **Given** a schema with `properties.webhook.format: uri` and `webhook: https://hooks.example.com/notify`, **When** `get webhook` runs, **Then** it prints the URL and nothing is fetched.
2. **Given** a schema with `properties.agents.additionalProperties.properties.urls.items.format: uri`, **When** `get agents.coder.urls.0` runs, **Then** it prints the URL literally (S-7).
3. **Given** a schema that marks the path only through `$ref`, `allOf` or `patternProperties`, **When** the configuration loads, **Then** the string is an include (S-7).
4. **Given** `note: !literal file:readme.md`, `docs: !literal https://x.example/y`, `n: !literal 5`, **When** `show` runs, **Then** it prints the strings `file:readme.md`, `https://x.example/y` and `'5'` (as a string) without `!literal` (S-10).
5. **Given** `!literal` on a mapping or list, another tag, or `!literal` on a `$ref` value, **When** any loading command runs, **Then** exit 4, stderr names the file (S-10, S-3).

---

### User Story 5 - The configuration matches its schema (Priority: P1)

**Why this priority**: The contract requires the loaded configuration to validate; a `set` must not break it.

**Independent Test**: Fixtures with valid and invalid configurations and schemas; run loads and `set`s; compare exit codes, stderr and file bytes.

**Acceptance Scenarios**:

1. **Given** a schema requiring `model` to be a string and `model: 5` (in any file, local or remote), **When** any loading command runs, **Then** exit 4, stderr names the schema file and `model` (S-8).
2. **Given** a schema file that is not valid JSON, not a valid 2020-12 schema, or has a non-fragment `$ref`, **When** any loading command runs, **Then** exit 4 naming the schema file (S-8).
3. **Given** a valid configuration, **When** `set model 5` would violate the schema, **Then** exit 3, stderr names `model` and the schema file, no file changes, no event (S-9).
4. **Given** `"format": "uri"` on `webhook` and `webhook: not a uri`, **When** the configuration loads, **Then** it loads (format is not asserted, S-8).
5. **Given** no schema file, **When** commands run, **Then** behaviour is as in steps 1–6 apart from remote includes and `!literal`.

---

### User Story 6 - `set` writes include-looking strings safely (Priority: P1)

**Why this priority**: Without this, setting a URL value would silently turn it into an include.

**Independent Test**: Run `set` with include-looking VALUEs, with and without `--include` and schema marks; compare whole files byte-for-byte.

**Acceptance Scenarios**:

1. **Given** no schema, **When** `set docs https://x.example/y` runs, **Then** the file gets `docs: !literal https://x.example/y` and `get docs` prints the URL (S-13).
2. **Given** `p.md` exists, **When** `set b file:p.md` runs, **Then** `b: !literal file:p.md` is written; **When** `set --include b file:p.md` runs, **Then** `b: file:p.md` is written and `get b` prints the content of `p.md` (S-13, S-12).
3. **Given** the schema marks `webhook` `format: uri`, **When** `set webhook https://h.example/n` runs, **Then** it is written untagged; **When** `set --include webhook https://h.example/n` runs, **Then** exit 3, no file changes (S-12).
4. **Given** `set agents '{coder: {docs: https://x.example/y, n: 1}}'`, **When** it runs, **Then** only the include-looking string is tagged `!literal` (S-11).
5. **Given** `docs: !literal https://old.example`, **When** `set docs plain-text` runs, **Then** the line becomes `docs: !literal plain-text` (S-11).
6. **Given** `set --include team http://…/missing.yaml` (404), **When** it runs, **Then** exit 3, no file changes (S-12).
7. **Given** `--include` passed to `get`, `show`, `history` or `watch`, **When** it runs, **Then** exit 2 with empty stdout (S-12).
8. **Given** a local text include `prompt: file:sys.md`, **When** `set prompt https://x` runs, **Then** `sys.md` holds `https://x` and nothing is tagged (S-11).

### Edge Cases

- The same URL included twice is fetched once per load (S-2).
- An anchor on a remote include reference, or on a node containing one, → exit 4 (step 6 C3 applies to all include references).
- Remote YAML may use anchors, aliases and merge keys internally; they resolve as in step 6, and are read-only (S-4).
- A string reached through an alias whose anchored node is literal by schema stays literal at every alias (S-7).
- A redirect to a non-`http(s)` scheme is a failed fetch → exit 4 (S-2).
- A redirect from `https` to `http` is a failed fetch → exit 4 (S-15); a body over 1 MiB → exit 4 (S-14).
- `watch` reports a failed fetch like any other load failure and keeps running (step 3 behaviour).
- A `set` on a path unrelated to remote content still fetches every remote include (the configuration is loaded and verified as a whole); a failed fetch then → exit 4.

## Requirements *(mandatory)*

### Functional Requirements

| ID | Title | User Story | Priority | Status |
|----|-------|------------|----------|--------|
| FR-001 | Remote includes load | As an owner, a string starting `https://` or `http://` that is not a literal is an include fetched when the configuration loads: YAML if the URL path ends `.yml`/`.yaml`, otherwise text; scalar and `$ref` forms both work, `$ref` with overrides as in step 5 (S-2, S-3). | High | Open |
| FR-002 | Includes inside remote content | As an owner, `file:` includes inside remote content resolve against the containing URL and are fetched; nested remote includes are allowed; a URL cycle exits 4 (S-1). | High | Open |
| FR-003 | Failed fetch | As an owner, a network error, timeout (10 s), non-2xx status, redirect to another scheme or from `https` to `http` (S-15), body over 1 MiB (S-14), or non-UTF-8 body exits 4 with stderr naming the URL and the location holding the include (the local file, or the remote URL for an include inside remote content) (S-2). | High | Open |
| FR-004 | Remote content is read-only | As an owner, every `set` that would change remote content (existing value, whole-include replacement, `--in-include`, list append or key inside a remote list item, `--expand-alias` in remote content) exits 3 with stderr naming PATH and containing the outermost local include string exactly as written; no file changes (S-4). | High | Open |
| FR-005 | Local overrides under remote includes | As an owner, a new key under a remote include is written as a local override, converting a scalar-form include as in step 5; values from local overrides are changed in place (S-4, S-5). | High | Open |
| FR-006 | Remote leaves in reads and history | As an owner, `get`, `show` and history see remote leaves; reconcile records upstream changes with file lineage; `show --sources` attributes remote scalars to the resolved URL; `watch` reconciles on local file and schema file changes, not by polling URLs (S-6). | High | Open |
| FR-007 | Schema marks literals | As an owner, a string whose schema, found by walking `properties`, `additionalProperties` and `items` only, has `"format": "uri"` is a literal, never fetched or read as an include (S-7). | High | Open |
| FR-008 | `!literal` tag | As an owner, a scalar tagged `!literal` is the string of its text and never an include; reads print it without the tag; `!literal` on a mapping, list or `$ref` value, or any other tag, exits 4 (S-10, S-3). | High | Open |
| FR-009 | Configuration validates against the schema | As an owner, when `.troupe/troupe.schema.json` exists, the resolved configuration is validated against it as JSON Schema 2020-12 (format not asserted); an invalid configuration, or an unreadable or invalid schema, exits 4 naming the schema file (and the first failing path) (S-8). | High | Open |
| FR-010 | `set` keeps the configuration valid | As an owner, a `set` whose result would fail validation exits 3 naming PATH and the schema file; no file changes, no event (S-9). | High | Open |
| FR-011 | Include-looking strings written literal | As an owner, `set` writes every include-looking string in VALUE whose path the schema does not mark `format: uri` as `!literal <string>`; an existing `!literal` on a replaced string value is kept; text-include content is never tagged (S-11, S-13). | High | Open |
| FR-012 | `--include` | As an owner, `set --include` writes include-looking strings untagged so they are includes; it exits 3 if the new include cannot be read or fetched, or the path is marked `format: uri`; it has no effect on VALUEs without include-looking strings; other subcommands given it exit 2 (S-12). | High | Open |

### Non-Functional Requirements

| ID | Title | Requirement | Category | Priority | Status |
|----|-------|-------------|----------|----------|--------|
| NFR-001 | Remote content never written | In 100% of `set` scenarios touching remote content, 0 requests other than reads are sent to any server and 0 local files change unless S-5 makes a local override. | Reliability | High | Open |
| NFR-002 | Refusals change nothing | 100% of commands exiting 2, 3, 4 or 5 change 0 configuration files and record 0 events of their own. | Reliability | High | Open |
| NFR-003 | Byte-surgical writes | After any successful `set`, 0 bytes differ in any file beyond those this spec and the step 1–6 write-back rules require (TROUPE-001). | Reliability | High | Open |
| NFR-004 | Bounded waiting | No single fetch blocks a command for more than 10 seconds before it fails with exit 4. | Reliability | Medium | Open |
| NFR-005 | Behaviour coverage | Every functional requirement and agent choice S-1–S-13 has at least one test against real files, the real CLI, a real local HTTP server and the real event store that fails if the behaviour breaks; `uv run pytest`, `uv run mypy --strict`, `uv run ruff check` and `uv run ruff format --check` pass. | Maintainability | High | Open |

### Constraints

| ID | Title | Constraint | Category | Priority | Status |
|----|-------|------------|----------|----------|--------|
| C-001 | Contract as written | The Remote includes and schema section is implemented as written; out-of-contract choices (S-1–S-12, S-14–S-16) are recorded here, never as contract amendments. | Business | High | Open |
| C-002 | Fixed platform | Python 3.12+ with uv; CLI as `uv run troupe config …`; `eventsourcing` event store under `<theatre>/.troupe/`; macOS/Linux only (TROUPE-004). | Technical | High | Open |
| C-003 | Earlier behaviour kept | All step 1–6 behaviour is unchanged for configurations without remote includes, schema file or `!literal`, except S-13 (include-looking `set` VALUEs are written literal unless `--include`). | Technical | High | Open |
| C-004 | Errors name the path, file or URL | Every new error message names the path, file or URL involved (TROUPE-003). | Technical | Medium | Open |
| C-005 | Atomic writes | Every file a `set` changes is replaced atomically (temp file + rename). | Technical | High | Open |
| C-006 | Tests are offline | Tests use a local HTTP server they start themselves; no test depends on outside network access. | Technical | High | Open |

### Key Entities

- **Remote include**: an include string `https://…`/`http://…` in scalar or `$ref` form; its target is fetched content (YAML or text).
- **Remote content**: the fetched documents and everything they include; read-only.
- **Schema**: the JSON Schema 2020-12 document at `.troupe/troupe.schema.json`; decides literals (through `format: uri`) and validity.
- **Literal**: a string that is never an include (`!literal` or schema `format: uri`).

## Assumptions

- A JSON Schema 2020-12 validator library may be added as a dependency; the schema is checked against the 2020-12 meta-schema.
- `http://` is accepted as the contract says; no warning is printed.
- A failed fetch during a `set`'s own load (before any write) is a load failure → exit 4; a failed fetch of an include the `set` itself introduces (`--include`) → exit 3 (S-12).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of scenarios, a value from a remote include reads the same through `get` and `show` as it would from an equal local file.
- **SC-002**: 100% of attempts to change remote content are refused, and every refusal message contains the local include string the owner must change.
- **SC-003**: 0 strings marked `format: uri` or tagged `!literal` are fetched or read as includes.
- **SC-004**: 100% of configurations that fail their schema are refused at load, and 100% of `set`s that would make them fail are refused with no file changed.
- **SC-005**: 100% of the existing step 1–6 test suite still passes, except tests asserting that a `set` of an include-looking VALUE creates an include (S-13), which are updated to pass `--include`.
