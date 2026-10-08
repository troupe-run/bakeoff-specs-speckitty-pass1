# Research: troupe configuration: remote includes and a schema

Phase 0 of [plan.md](plan.md). Each entry gives the **decision**, the **rationale** and the **alternatives considered**. Product-level choices are spec S-1 to S-13. This file records how they are built. The code map behind these decisions was taken from `src/troupe/` at `edc9bbe`.

## R-1 Where a source lives: `Location = Path | Url`

- **Decision**: a new dependency-free module `troupe/location.py` defines `Url`, a frozen dataclass holding the absolute URL text, whose `__str__` is that text, and `Location = Path | Url`. `tree.SourceFile.path` keeps its name, but its type becomes `Location`; `SourceFile.remote` is `isinstance(path, Url)`. The loader cache (`_files`), the in-memory override map, the cycle stack and `load(..., overrides=...)` are all keyed by `Location`. Each remote document gets exactly one `SourceFile` per load, as files already do, so `placement._include_ref` keeps working by object identity.
- **Rationale**: Retyping the field makes `mypy --strict` flag every place that needs a file on disk: `atomic_write`, `watched_files`, `watch`'s baseline, `yamlout.Line.source`/`source_label`, `_include`'s `.parent`, and the `dict[Path, str]` override maps in `apply.py`. Each of those then has to decide explicitly what to do with a URL. Messages that only format the location in an f-string print the URL unchanged and need no edit. Read-only safety (S-4) gets a compile-time backstop on top of the runtime guard in R-7. Keeping the field name keeps the change local (DIRECTIVE_024): a rename would touch about 10 modules owned by different work packages, for no gain in safety.
- **Alternatives**:
  - Rename the field to `location`. Rejected during task planning: same safety, about 40 more edited lines.
  - Add a separate `url: str | None` field next to `path`. Rejected: every existing `.path` caller would silently keep working on a meaningless path.
  - Fake a `Path` for URLs. Rejected: one of them could end up in `atomic_write`.

## R-2 Fetching: `troupe/remote.py`, standard library only

- **Decision**: a new module `remote.py` owns all network access. `fetch(url: Url) -> str` uses `urllib.request` and works as follows:
  - **Request**: a `GET` with no credentials and no cookies. TLS uses `ssl.create_default_context()`, so certificates and host names are verified.
  - **Redirects**: a redirect handler that follows only `http`/`https` targets. A redirect to any other scheme is a failure.
  - **Timeout**: one **total deadline of 10 s** (`FETCH_TIMEOUT_SECONDS`). The body is read in chunks, and the socket timeout is set to whatever time remains, so a slowly trickling server cannot exceed 10 s (NFR-004).
  - **Status**: anything other than 2xx is a failure.
  - **Body**: decoded as strict UTF-8 without newline translation. A leading BOM is handled exactly as `read_source` handles it for local files.

  Every failure raises a `FetchError(LoadError)` naming the URL and the reason, for example `HTTP 404 Not Found`, `timed out after 10 s`, `redirect to ftp://… refused`, or `not valid UTF-8 at byte N`. The loader adds the including file and the path (S-2).
- **Rationale**: `urllib.request` covers redirects, TLS verification and timeouts with no new dependency. It is all S-2 needs. Keeping network access in one module means tests can count requests at the server, and no other code touches the network.
- **Alternatives**:
  - `httpx`/`requests`. Rejected: they are extra dependencies for features S-2 doesn't use.
  - An environment variable to set the timeout. Rejected: it would be a configuration surface nobody asked for. The single 10 s test costs about 10 s of run time.

## R-3 Include strings and target resolution: `troupe/includes.py`

- **Decision**: a new module `includes.py` is the one place that decides what an include string is and what it points at. Today that test is duplicated in `loader._content`, `_is_include_string` and `_ref_include`. The module provides:
  - **`include_kind(text) -> "file" | "remote" | None`**: `file:` → file; `https://` or `http://` → remote. The test is a case-sensitive prefix match, as it already is for `file:`.
  - **`resolve_target(text, containing: Location) -> Location`**:
    - `file:` inside a local file → `containing.parent / rest`, as today.
    - `file:` inside remote content → `Url(urljoin(containing.text, rest))` (S-1).
    - A remote string → `Url(text)`, used as written.
  - **`is_yaml_target(location)`**: for a `Path`, the suffix is `.yml`/`.yaml`, as today. For a `Url`, the same test is applied to `urlsplit(url).path`, so query and fragment are ignored (S-2).
  - **`reads_as_include(text, tagged=, uri=)`**: the S-7/S-10 rule. A string is an include only if `include_kind` is not `None`, it is not tagged `!literal`, and the schema does not mark its path `format: uri`. A `$ref` value is always an include string (S-3).

  Cycle detection keys on the resolved `Location`. For URLs that is the `urljoin` result. A cycle message lists the locations as written.
- **Rationale**: TROUPE-007 (one decision, one place). S-1 and S-7 both change what an include is, and three copies of that rule would drift.
- **Alternatives**:
  - Keep the rule inside `loader.py`. Rejected: `writeback/apply.py` and the value tagging in R-8 also need it.

## R-4 `!literal` in the composer

- **Decision**: in file mode (`compose(..., allow_anchors=True)`), `yamlcore._Composer` accepts the tag `!literal` on a scalar, and only there.
  - `RawScalar` gains `tag: RawTag | None`, which holds the tag's span.
  - The scalar's `start` moves past the tag (and past an anchor, in either order: `&a !literal x` and `!literal &a x`) to the content, exactly as anchored nodes already do (step-6 R-2). Every writer therefore keeps its assumption that `origin.start` is where the value begins, including `blocks.parse_block`, which expects `|`/`>` there.
  - The composer refuses with exit 4 `!literal` on a mapping or sequence, and every other tag.
  - VALUE mode (the default, used by `values.parse_value`) still refuses every tag (S-11, step-6 C14).
- **Rationale**: The code map shows that ruamel puts a tagged scalar's `start_mark` at the `!`. Without this change, a replacement would delete the tag, which breaks S-11's "tag is kept", and the alias copy renderer would copy the tag text.
- **Alternatives**:
  - Strip the tag text out in the writers. Rejected: span knowledge would spread across about eight writers.
- **Other composer callers**:
  - `collections.detect_indent` and `_check_open_end` already compose in file mode, so they accept `!literal`.
  - `scalars._round_trips_plain` only composes rendered values.
  - `apply._include_string` composes in VALUE mode and is rewritten to use the tree (R-9).

## R-5 Literal strings in the tree

- **Decision**: `ScalarNode` gains `literal: Origin | None`, the span of the `!literal` token and the whitespace after it.
  - The loader builds a `ScalarNode` (never an include) when `includes.reads_as_include` says it is not an include. The value is the scalar's text as a string; for a plain scalar that is the text unresolved, so `!literal 5` is `'5'`.
  - `!literal` on a `$ref` value → exit 4 (S-3).
  - Reads (`get`, `show`, history leaves) see an ordinary string. `yamlout` never prints the tag (S-10).
  - C3 (no anchors on include references) applies only to strings that are includes. A literal may carry an anchor (S-10).
- **Rationale**: Writers need the tag's span to keep it or drop it (R-8). Readers need nothing new.

## R-6 Schema: `troupe/schema.py` and the `jsonschema` dependency

- **Decision**: a new module `schema.py` provides the following.
  - **`load_schema(state_dir) -> Schema | None`** reads `<state_dir>/troupe.schema.json` and returns `None` when the file is absent.
    - It reads the file as strict UTF-8 and parses it with `json.loads`. `NaN` and `Infinity` are refused through `parse_constant`, because they are not JSON.
    - A `$schema` key, if present, must equal `https://json-schema.org/draft/2020-12/schema`.
    - `Draft202012Validator.check_schema` checks the schema against the 2020-12 meta-schema.
    - Every `$ref`/`$dynamicRef` value anywhere in the document must start with `#`.

    Any failure is a `LoadError` naming the schema file (S-8).
  - **`Schema.uri_at(steps) -> bool`** is the S-7 walk; each step is `("key", name)` or `("index", n)`. A mapping key `k` goes to `properties[k]` when present, otherwise to `additionalProperties` when it is an object. A list index goes to `items` when that is an object. The answer is `True` only if the final schema is an object with `"format": "uri"`. Boolean subschemas, `$ref`, combinators, `patternProperties` and `prefixItems` are never followed. Each step carries its container kind (mapping or list), because a segment like `"0"` could be either.
  - **`Schema.validate(tree) -> Violation | None`** converts the resolved tree (via `leaves`/`paths.unwrap`; text includes as strings, `!literal` strings as strings) to plain JSON data. It runs `Draft202012Validator(schema, registry=Registry())` with no `format_checker`, so `format` is an annotation only (S-8). An empty `Registry` resolves nothing outside the document. The first violation is the one with the smallest JSON path, comparing list indexes numerically and mapping keys by name (not by position in the file), then the shortest path, then the validator name; this makes it deterministic, and its dotted path and message are used. (Wording corrected after the post-merge mission review, D-1: the spec's "first failure" does not fix an order, and key-name order is what the code does.) An `Unresolvable` raised during validation is a `LoadError` naming the schema file.
- **Dependency decision**: DM 01M4BMXJXSNEY2QMXYA1W16W04. The product owner asked for the safest assumption. The plan adds `jsonschema>=4.26,<5` as a runtime dependency, locked in `uv.lock`.
- **Rationale**: A hand-written 2020-12 validator that is subtly wrong would accept or refuse configurations against the contract. The reference implementation passes the official JSON-Schema-Test-Suite.
- **Alternatives**:
  - A hand-written validator. Rejected: correctness risk (see the decision).
  - `fastjsonschema`. Rejected: its 2020-12 support is incomplete.

## R-7 Read-only remote content: one guard, two checkpoints

- **Decision**: `writeback/placement.py` gains `remote_refusal(found, dotted) -> WriteRefused | None`. Walking the route from the root, it finds the first include whose target is remote: a `YamlInclude`/`TextInclude`, or the `ref` of a `MergedMapping`. That include is the **outermost** remote include, and its `origin` lies in a local file. The message is:

  `{dotted}: value comes from remote include {written} ({local file} line N); troupe does not change remote content — change that include line instead; no file changed`

  where `{written}` is `origin.source`, the include string exactly as written (S-4).

  The guard runs at two checkpoints:
  1. **In `place`, right after `walk`, before alias routing.** For an existing PATH, the guard refuses when the node at PATH comes from remote content. That covers a scalar or collection whose origin file is remote, a remote `YamlInclude`/`TextInclude` (whole replacement or text write), and a `MergedMapping` whose `ref` is remote. Because this check comes first, a value reached through an alias inside remote content reports the remote include, not `--expand-alias`.
  2. **In `apply_set`, before verification.** If any `SourceFile` in the planned files is remote, the guard refuses using the same message builder on the route. This catches every new-key route that would land in remote content: list append, a key inside a remote list item, `--in-include`, and an `--expand-alias` copy.

  As a last safety net, `writeback.fileio.write_files` asserts that every location is a `Path`. The type already requires it (R-1).
- **Rationale**: Checkpoint 2 cannot miss a route, because it looks at what would actually be written. Checkpoint 1 gives the contract's message before the other step 1–6 refusals can claim the case. New keys under a remote include still reach S-5's local override through the unchanged step-5 placement.
- **Alternatives**:
  - Add a check in every placement branch. Rejected: there are about eight branches, and one could be missed.

## R-8 Writing `!literal`: `LiteralStr` marker

- **Decision**: after `parse_value`, `apply_set` calls `includes.mark_literals(value, segments, schema, include_flag)`. It walks VALUE, and every include-looking string whose resulting path the schema does not mark `uri` becomes a `LiteralStr`, a `str` subclass used only as a marker (S-11, S-13). With `--include`, nothing is marked. In that case, if any include-looking string's path is marked `uri`, the `set` is refused with exit 3 (S-12).

  With `--include`, include-looking strings become `IncludeStr` instead (a second marker), so a later no-op check can tell an include from a literal (R-9).

  Renderers (WP07):
  - `scalars.render_scalar`, the shared single-line renderer for **new** values, writes `!literal ` before a `LiteralStr`. `render_string`, which also renders keys, never does.
  - `blocks.render_new_multiline` writes `!literal ` before the `|`/`>` indicator, or before the double-quoted string in flow context.
  - Alias copies (`aliases.py`) keep the `!literal` tag on copied scalars; otherwise a copy of a literal would become an include.
  - Kind-changing replacement (`collections.replace_value_edits`) removes the tag when a tagged scalar becomes a collection.

  Replacing an existing scalar by a scalar (WP08, `apply._scalar_edits`): the value is rendered as a plain `str`, and the tag is a separate edit next to the content. Its span starts at the content (R-4).
  - `LiteralStr` and no tag → insert `!literal ` at the content start.
  - Existing tag and new value a `LiteralStr` or plain `str` → keep (S-11).
  - Existing tag and new value an `IncludeStr` or non-string → remove the tag span.
  - Text-include writes (`_plan_text`) write file text, so the markers are dropped.
- **Rationale**: A `str` subclass travels unchanged through every existing renderer, comparison and verification. Only the two choke points learn about it.
- **Alternatives**:
  - Pass a per-path predicate down every renderer. Rejected: it changes about 15 signatures.

## R-9 No-op and read-back: include vs literal

- **Decision**: `apply._matches` compares strings with the markers from R-8. An include node matches only an `IncludeStr` equal to its written include string. A `ScalarNode` (including a literal) matches a `str` with the same value only when it is not an `IncludeStr`. `_include_string` keeps reading the include string from the node's source text; includes are never tagged, so VALUE-mode composing still works.
- **Rationale**: Without this rule, a VALUE that repeats an existing include's string inside a collection (e.g. `set agents '{coder: file:p.md}'` where `agents.coder` already is the include `file:p.md`) would be a no-op, although S-11/S-13 say the string is written `!literal file:p.md`. A scalar `set b file:p.md` on `b: file:p.md` never reaches this check: for a text include the step-1 rule rewrites `p.md`, and a YAML include cannot be replaced as a whole (exit 3). (Corrected after WP08/WP10.) Likewise, `set --include b file:x` on `b: !literal file:x` must write.

## R-10 Configuration loading: one entry point with the schema

- **Decision**: a new function `configuration.load_configuration(theatre, overrides=None, fetched=None) -> Loaded(tree, schema, fetched)`:
  1. `schema = load_schema(state_dir)`.
  2. `tree = loader.load(config_file, overrides, schema=schema, fetched=fetched)`.
  3. If the schema exists, `schema.validate(tree)`; a violation raises `LoadError`: `configuration does not match schema {schema file} at {path}: {message}` (exit 4, S-8).

  It is used by `session.open_session`, `watch` and the in-memory reloads in `apply._verify` and `_plan_expansion`. In `_verify`, the outcomes are:
  - a schema violation → `WriteRefused`: `{PATH}: the change would not match schema {schema file} at {path}: {message}; no file changed` (S-9, exit 3);
  - any other `LoadError` from the new text, such as a new include that is missing or fails to fetch → `WriteRefused`: `{PATH}: {cause}; no file changed` (S-12, exit 3).

  **Fetch once per command**: `fetched: dict[Url, str]` is filled by the first load and reused by every reload in the same command. Only URLs the `set` introduces are fetched again, and the whole command sees one snapshot of the remote content.
- **Rationale**: One place decides "loaded and valid" (TROUPE-007). The command's own reloads cannot fail on a remote change that happens mid-command.
- **Alternatives**:
  - Validate inside `loader.load`. Rejected: a `set` needs a different exit code (3) for the same violation.

## R-11 Sources, watch and history

- **Decision**:
  - `yamlout.Line.source` becomes a `Location`. `source_label` prints `Url.text` verbatim (S-6).
  - `reconcile.watched_files` skips remote sources.
  - `watch` adds `<state_dir>/troupe.schema.json` to its baseline as a candidate path that may be absent, as it does today for the two root names. A change to the schema file triggers a reconcile.
  - History and reconcile need no change: remote leaves are ordinary leaves.
- **Rationale**: S-6. Watched files must be readable local paths, and the schema decides what is a literal.

## R-12 CLI

- **Decision**: `set` gains `--include` (store-true) in `cli.py` beside `--in-include` and `--expand-alias`. It is passed through `set_value.run` → `apply_set`. Other subcommands reject it as an unknown option (exit 2, S-12).

## R-13 Test harness for remote content

- **Decision**: a new `tests/remote_server.py` and a `remote` fixture in `conftest.py`:
  - **Server**: a `ThreadingHTTPServer` on `127.0.0.1:0`, running in a thread in the test process. It is reachable from the CLI subprocess.
  - **Routes**: a mutable route table, path → status, body bytes and optional `Location` header. Special routes: `hang` (sleeps longer than the deadline) and `trickle` (sends one byte per second).
  - **Request log**: method and path of every request, so tests can assert "nothing fetched" (S-7, S-10), "fetched once" (S-2) and "only GET" (NFR-001).

  TLS verification is tested by serving `https` with a throwaway self-signed certificate made with the `openssl` CLI; the test expects exit 4. If `openssl` is not installed, that one test is skipped and reports why. Everything else uses `http://127.0.0.1`. No test touches the outside network (C-006).
- **Rationale**: TROUPE-005 (real CLI, real files, real HTTP).

## Supply-chain review (directive 051, advisory)

| Package | Version at plan time | Released | Source | Notes |
|---|---|---|---|---|
| jsonschema | 4.26.0 | 2026-01-07 | PyPI, pure-Python wheel | long-lived reference implementation of JSON Schema for Python |
| referencing | 0.37.0 | 2025-10-13 | PyPI, pure-Python wheel | same maintainer |
| jsonschema-specifications | 2025.9.1 | 2025-09-08 | PyPI, pure-Python wheel | bundles the meta-schemas, so no network access at runtime |
| rpds-py | 2026.9.1 | 2026-10-04 | PyPI, 127 prebuilt wheels incl. cp312+ manylinux/musllinux/macOS | compiled Rust; only prebuilt wheels must be used |
| attrs | 26.1.0 | 2026-03-19 | PyPI, pure-Python wheel | widely used |

- **Registry authenticity**: only PyPI, through uv. `uv.lock` pins exact versions and sha256 hashes.
- **Freshness**: `rpds-py` was released three days before planning. Lock with uv's default resolution and record the locked versions in the work-package review.
- **Lifecycle scripts**: Python wheels run no install scripts. The only risk is a source build of `rpds-py`, which would need a Rust toolchain and run its build backend. Mitigation: `[tool.uv] no-build-package = ["rpds-py"]` in `pyproject.toml`, so uv refuses to build it from source.
- **Node LTS**: not applicable (no JavaScript).

## Adversarial challenge pass

A single-reviewer challenge pass was done during planning. A multi-agent squad was **deferred with rationale**: the only security-relevant dependency decision was directed by the product owner ("safest assumption"), and its risk is covered by the supply-chain mitigations above. Contested findings:

| # | Challenge | Disposition |
|---|---|---|
| A-1 | A remote server could return a huge body and exhaust memory. | **deferred_with_rationale**: there are no performance targets (TROUPE-004), and the spec sets no size limit, so inventing one would be a new requirement. Recorded under Risks. |
| A-2 | Redirects could reach `file://` URLs and read local files. | **accepted**: the R-2 redirect handler refuses every non-http(s) scheme (S-2). |
| A-3 | A `file:` include in remote content could escape to local disk. | **accepted**: S-1/R-3 resolve it against the URL, so it never becomes a local path. |
| A-4 | `jsonschema` might fetch remote `$ref`s. | **accepted**: there is an empty `Registry` and every `$ref`/`$dynamicRef` must start with `#` (R-6). |
| A-5 | A source build of `rpds-py` runs arbitrary build code. | **changed**: `no-build-package` added (supply-chain review). |
| A-6 | `http://` sends shared configuration in clear text. | **deferred_with_rationale**: the contract explicitly allows `http://`, and the spec assumption is that no warning is printed. |
| A-7 | A remote write could happen through a route nobody listed. | **accepted**: R-7 checkpoint 2 inspects the actual planned files, and `write_files` asserts local paths. |
