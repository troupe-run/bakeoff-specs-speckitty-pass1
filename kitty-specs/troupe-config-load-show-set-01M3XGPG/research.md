# Research: troupe configuration: load, show, set

Each entry: Decision · Rationale · Alternatives considered. Product-owner decisions are cited by id;
the rest are implementer choices where the contract is silent (charter TROUPE-008/009).

## R-01 Write-back technique — span splice, never re-serialise (DM-01M3XGW5Z97R8VC909JF3TVPTT)

- **Decision**: compose each file with `ruamel.yaml` to get nodes with `start_mark`/`end_mark`
  (code-point `index`, `line`, `column`), scalar `style` (`None` plain, `'`, `"`, `|`, `>`) and
  collection `flow_style`. Renderers produce only the replacement text for the affected span(s);
  the result is `old_text[:start] + new + old_text[end:]`. Line-level context (indentation,
  end-of-line comment) is read from the original text, not from the parser.
- **Rationale**: untouched bytes are identical by construction, which is what FR-014 requires and
  what users reviewing diffs need. Verified locally: ruamel 0.19.1 compose gives exact indices and
  styles (e.g. `a: "x"  # c` → `"` style, span 3–6).
- **Alternatives**: ruamel round-trip load/modify/dump — rejected by the product owner; it normalises
  indentation, quoting, flow spacing, folded scalars and comment spacing. Hand-written YAML parser —
  rejected: large, risky, and ruamel's marks are sufficient.

## R-02 History persistence — eventsourcing SQLite (DM-01M3XGX935C4759B9DMK0BXXKT)

- **Decision**: `eventsourcing` 9.5.x `Application` subclass with environment
  `PERSISTENCE_MODULE=eventsourcing.sqlite`, `SQLITE_DBNAME=<theatre>/.troupe/history.sqlite`
  (passed via the application's `env` argument, not process environment). One `ConfigHistory`
  aggregate per theatre with a fixed id (`uuid5(NAMESPACE_URL, "troupe:config-history")` — the
  database is per theatre so a constant id suffices). Each leaf change is one domain event on the
  aggregate; `seq` = aggregate event version minus 1 (the creation event is version 1).
- **Rationale**: real library persistence (TROUPE-005); atomic per `save()`; state confined to
  `.troupe/` including `-journal`/`-wal`. The aggregate *is* the projection of the history.
- **Alternatives**: POPO recorder + JSON file — custom serialisation and partial-write risk.

## R-03 Source of truth (spec DM-01M3XGPT4E0D67ZJY8PT7Z9NAT)

- **Decision**: every command loads files from disk. The aggregate is consulted only to (a) know
  whether the theatre was imported and (b) list events. `set` diffs leaves of the on-disk tree
  before and after its own write; hand edits never generate events.

## R-04 Import timing

- **Decision**: any subcommand, after the configuration loads successfully and before executing,
  imports if the aggregate does not exist (one `import` event per leaf in document order, `old`
  null). If loading fails (exit 4) nothing is recorded. A `show`/`set` that then exits 5 or 3 keeps
  the import (the theatre was successfully read). Usage errors (exit 2) occur before loading.
- **Rationale**: "The first command run against a theatre imports it."

## R-05 Encoding and newlines

- **Decision**: read files as bytes; decode UTF-8 (with BOM preserved if present); keep the decoded
  text with its original newlines (`newline=''` semantics) so mark indices match characters exactly.
  New lines inserted into a file use the file's dominant line ending (CRLF if the file's first line
  break is `\r\n`, else `\n`). Text include CRLF rule (FR-010): if the target contains `\r\n`, every
  `\n` in VALUE not already preceded by `\r` becomes `\r\n`.
- **Alternatives**: platform default encoding — rejected (non-deterministic).

## R-06 File indentation

- **Decision**: the indentation step of a file is the column of the first indented block-mapping key
  or block-sequence entry's content relative to its parent; default 2 if the file has none.
  Sequence-in-mapping style (indented `- ` vs flush `- `) is copied from an existing sibling sequence
  when creating a new list, else indented by the step.

## R-07 Event paths

- **Decision**: event paths are dotted paths in the merged configuration tree (e.g.
  `agents.coder.name` even though the value lives in `agents/coder.yaml`). Text-include leaves are
  recorded at the path of the include string, with the file text as the value. `old`/`new` are JSON
  (floats as JSON numbers, null as `null`).

## R-08 Dependencies and supply chain (directive 051, advisory)

- **Decision**: runtime `eventsourcing>=9.5,<10`, `ruamel.yaml>=0.19,<0.20`; dev `pytest`, `mypy`,
  `ruff`; resolved by uv from PyPI with a committed hash-pinned `uv.lock`.
- **Checks**: both runtime packages are long-established PyPI projects (eventsourcing since 2015,
  ruamel.yaml since 2015), pure-Python wheels, no install-time scripts. No Node tooling involved.
- **Adversarial pass**: deferred_with_rationale — the decision is low-impact (pure-Python, no
  network or credential handling, lock-file pinned); the dominant risk (format corruption) is
  covered by R-01 and NFR-001 tests rather than by dependency choice.

## R-09 YAML 1.2 core for VALUE and file scalars

- **Decision**: `YAML(typ="safe", pure=True)` with version 1.2 to parse VALUE; file scalars resolved
  through the same constructor applied to composed nodes. Verified: `yes`→str, `0.2`→float,
  `"0.2"`→str, `0o17`→int, `{a: 1}`→dict, `"l1\nl2\n"`→multi-line str.

## R-10 Quoting representability (FR-015)

- **Decision**: plain is usable iff re-parsing the plain text as YAML 1.2 core yields the same
  string and the text is single-line and safe in its context (block vs flow: flow contexts also
  forbid `,[]{}`); single-quoted iff the value has no line breaks and no characters requiring
  escapes (control characters); double-quoted always works. "Keeps its style if it can represent
  the value" is checked first; then plain → single → double. A non-string new value (int, bool,
  float, null) is always written plain (its YAML 1.2 core canonical text: `true`, `null`, decimal,
  Python `repr` for floats); quoting it would change its type.

## R-11 Folded re-wrap (FR-018)

- **Decision**: split old and new values into paragraphs (by the folding rules: a line break between
  non-empty, non-more-indented lines folds to a space). Match paragraphs by position; unchanged text
  keeps its original lines; changed ones are greedily re-wrapped at their old longest content-line
  width; extra paragraphs use the value's longest old content line. Any new line that would start
  with whitespace (more-indented) → exit 3.

## R-12 Atomic multi-file writes

- **Decision**: compute every new file text first; then for each changed file write a sibling temp
  file in the same directory, `fsync`, and `os.replace`. Only the files that actually change are
  touched; file mode is copied from the original. A `set` in step 1 changes exactly one file.

## R-13 ruamel's 1.2 resolver is not the YAML 1.2 core schema (found during /spec-kitty.tasks)

- **Finding**: `YAML(typ="safe", pure=True)` (default version 1.2) resolves `2001-12-14` to a
  `date`, `1_000` to `1000`, and treats `=`/`<<` specially — none of which the YAML 1.2 core schema
  does.
- **Decision**: use ruamel only to **compose** (nodes, marks, styles, already-unescaped scalar text).
  Resolve plain scalars with our own core-schema rules in one place, `src/troupe/yamlcore.py`:
  null `null|Null|NULL|~|<empty>`; bool `true|True|TRUE|false|False|FALSE`; int `[-+]?[0-9]+`,
  `0o[0-7]+`, `0x[0-9a-fA-F]+`; float `[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?`,
  `[-+]?\.(inf|Inf|INF)`, `\.(nan|NaN|NAN)`; everything else a string. Quoted and block scalars are
  always strings. `yamlcore.py` is the only module importing ruamel (mypy/typing boundary).

## R-14 Byte-order mark

- **Finding**: ruamel mark indices count a leading U+FEFF as one character.
- **Decision**: decode files with plain `utf-8` (not `utf-8-sig`), so the BOM stays in the text as a
  character; indices align with the text and writing `text.encode("utf-8")` preserves the BOM.
  Supersedes the BOM note in R-05.

## R-15 eventsourcing application lifetime

- **Finding**: an `Application` whose last reference is dropped closes its SQLite connection pool
  (`ConnectionPoolClosedError` on a temporary). Versions start at 1 with the creation event; WAL
  mode creates `history.sqlite-wal`/`-shm` beside the database (inside `.troupe/`).
- **Decision**: one `HistoryStore` instance per command held by the session context manager and
  closed explicitly; `seq = originator_version - 1`.

## R-16 Text include with a non-string VALUE (contract leaves a choice open)

- **Contract**: "For a text include, the target file's content becomes `VALUE` exactly, except that if
  the target file used CRLF line endings, the new content uses CRLF line endings too (`VALUE` must
  then be a string, else exit 3)."
- **Decision** (revised 2026-10-02 after product-owner review): the only refusal is the one the
  contract states — CRLF target + non-string VALUE → exit 3. With an LF (or line-break-free) target
  there is no type restriction: a string VALUE becomes the content as parsed (so
  `"line one\nline two\n"` writes real line breaks); any **non-string** VALUE — scalar, mapping or
  list — becomes the content as the VALUE argument's text exactly as typed (`5`, `true`, `0.20`,
  `{a: 1}`, `[a, b]`). "Uses CRLF" = the target text contains `\r\n`.
- **Rationale**: "the target file's content becomes VALUE exactly"; for a non-string VALUE the only
  exact text is the argument itself. The earlier draft refused mappings/lists; the product owner
  ruled that the contract gives no such refusal, so it was removed.
- **Consequence**: after such a `set`, the text include's leaf is the written text (a string), and
  history records `new` as that string.

## R-17 Verify before write

- **Decision**: `set` builds all new file texts, re-loads the configuration **in memory** from them
  (`loader.load(..., overrides=...)`), and checks that (a) the value at PATH equals the new value
  (type-aware) and (b) every other leaf is unchanged except those under PATH. If not, the command
  refuses with exit 3 ("cannot write PATH byte-surgically") and no file changes. If the value at
  PATH already equals VALUE, nothing is written and no event is emitted.
- **Rationale**: the costliest failure is corrupting a user's file (charter); this turns any
  renderer bug into a refusal instead of a corruption.

## R-18 Implementation handoff (engineer's decision; brief silent)

- **Question**: should implementation proceed via `/spec-kitty.analyze` and then implement + review
  of every WP to completion?
- **Decision**: yes. Run `/spec-kitty.analyze`; implement every WP in dependency order and review
  each independently (rejecting any WP whose gates — `uv run pytest`, `uv run mypy --strict`,
  `uv run ruff check`, `uv run ruff format --check` — fail, or whose `set` tests do not assert whole
  file bytes); merge lanes into `feat/troupe-config-load-show-set`, then merge that branch into
  `main` locally. Never push; never open a pull request.
- **Rationale**: the delivery requirement is a commit on `main`; nothing in this path publishes
  externally; independent review plus verify-before-write (R-17) is the option least likely to
  corrupt a user's file or contradict the contract.
- **Note**: recorded here because `spec-kitty agent decision open` returns `MISSION_NOT_FOUND`
  after `finalize-tasks` (it resolves the mission in the coordination worktree, which holds only
  status files).
