# Research & Decisions: troupe-config-get-show

Every choice here is one the contract leaves open. The PO delegated these choices to the agent, provided they are recorded (specify, 2026-10-03).

## R-1 Renderer: own emitter vs. `ruamel.yaml` dumper

- **Decision**: Emit the YAML with our own small renderer (`troupe/yamlout.py`), reusing `writeback.scalars` (quoting) and `writeback.blocks` (literal blocks).
- **Rationale**: `--sources` needs to know which output line holds which scalar, and a dumper does not expose that. Quoting would also be decided twice (ruamel's representer vs. our FR-015 rules), which breaks TROUPE-007. The renderer only needs block mappings, block sequences and scalars, about 150 lines.
- **Alternatives**: the ruamel round-trip dumper with comment injection (it gives no reliable line↔node mapping and its quoting differs from `set`'s); dumping and then post-processing lines (fragile for multi-line scalars).

## D-1 Layout

- **Decision**:
  - 2-space indentation.
  - Sequences under a key are indented: `key:` then `  - item`.
  - List items that are mappings use compact form (`- k: v`, siblings indented 2 more).
  - Lists nested in lists are compact (`- - a`).
  - Empty collections are `{}` and `[]` (inline after `key: ` or `- `, or alone at the root).
  - No `---`; output ends with `\n`.
- **Rationale**: This is common hand-written YAML style, and matches the default indent step that `set` uses for new collections (FR-016 of step 1).

## D-2 Literal blocks

- **Decision**: A literal block is used for:
  - (a) every text-include value, including one-line or empty text, because the contract names text includes explicitly;
  - (b) every other string that contains `\n`.

  The value must pass `blocks.can_block`; otherwise D-4 applies. All other strings are one-line flow scalars (D-5).
  - Header: `blocks.literal_header(value, chomp)`, with chomp from `blocks.required_chomps`, preferring clip, then strip, then keep. Indentation digit `2` when the first content line starts with a space.
  - Body: `blocks.literal_lines(value, n + 2)`.
  - Verified with ruamel: a root-level `|2-` reads content at column 2. An empty text include renders as `|-` with no body lines.
- **Rationale**: Exact read-back via the same chomping logic `set` uses (step-1 FR-017). Multi-line values are readable as in the source files.

## D-3 Float specials

- **Decision**: YAML output renders non-strings with `scalars.render_nonstring`:
  - `.inf`, `-.inf` and `.nan` for the special values;
  - `repr()` otherwise, which equals `get`'s output.
- **Rationale**: `get` prints `inf`/`nan`, which YAML would read back as strings and so break FR-005/NFR-001. Scalar output from `show` without `--sources` is unchanged and identical to `get` (FR-004). Spec FR-008 was amended in this commit.

## D-4 Text a literal block cannot hold

- **Decision**: If `blocks.can_block(value)` is false, the string is double-quoted with `scalars.render_string(value, "double")`. This covers CR from CRLF files, other control characters, U+FEFF, U+2028 and similar. For `--sources` it is still one scalar line.
- **Rationale**: This follows TROUPE-002: data is never altered, and the output still reads back exactly.

## D-5 Strings and keys on one line

- **Values**: `scalars.choose_style(s, None, "block")`, i.e. plain, then single, then double quotes. So `'true'`, `'123'`, `''` and `'a: b'` are quoted.
- **Keys**: the same `choose_style` in block context, plus a key-specific check.
  - A plain key must also round-trip as a key: `compose(f"{k}: x")` must give a single plain key with text `k`.
  - Otherwise the key is quoted the same way.
  - Keys containing `\n` (only possible with quoted keys) are double-quoted.
- **Rationale**: One quoting rule shared with `set` (FR-015).

## D-6 Source label

- **Decision**: `source_label(file_path, theatre_dir) = PurePath(os.path.relpath(file_path, theatre_dir)).as_posix()`. Both paths are resolved (`SourceFile.path` and `Theatre.directory` already are).
  - A file outside the theatre gives `../…`.
  - The comment is one space, `#`, one space and the label. The label is printed verbatim, because a comment holds any text up to the end of the line.
  - File names containing a line break cannot be represented. They are vanishingly rare and the contract is silent, so they are printed as-is, with no special handling.
- **Rationale**: The contract asks for paths relative to the theatre directory with `/` separators. `relpath` is the conservative rule, because it also covers targets outside the theatre.

## D-7 Which lines get a comment

- **Decision**:
  - Lines get a comment when they end with a flow scalar (`k: v`, `- v`, `- k: v`, or a bare root scalar), or when they are a literal-block header line (`k: |`, `- |`, root `|`).
  - Lines that only open a collection (`k:`, `-` never emitted alone, `- k:`) get none.
  - Lines whose value is `{}`/`[]` get none.
  - Block body lines never get a comment.
- **Rationale**: These are exactly the lines that "hold a scalar". A comment inside a block body would become content.

## D-8 Verification

- **Decision**: There is no runtime self-check in `show`. Correctness is proven by unit tests that parse each rendering with ruamel safe-load and compare it with `leaves`-style resolved data, and by integration tests that do the same on whole fixtures.
- **Rationale**: The renderer is pure and deterministic, so a runtime check would only turn a bug into a confusing error.

## D-9 Tests and helpers

- **Decision**:
  - Step-1 `show` scalar tests move to `tests/integration/test_get.py` (renamed `test_get_*`). The mapping/list refusal tests now assert the `config show` hint.
  - Value-reading helpers in other integration tests call `get`.
  - `test_cli_basics` "missing PATH → exit 2" uses `get`, and the help test checks `get` is listed.
  - New `show` tests cover sections, the whole configuration, `show scalar == get scalar`, and reconcile-first.
- **Rationale**: `get` is now the value reader (C-001). `show`'s scalar path is covered by an explicit equality test (NFR-004).

## get refusal wording

- **Decision**: `"{path} is a {mapping|list}, not a scalar; use 'troupe config show {path}'"`, in one constant/format in `commands/get.py`.

## D-10 Plain only when every common YAML reader agrees (added during WP01 review)

- **Decision**: In `show` output a string value or key is written plain only if (a) `scalars.choose_style` allows plain (D-5) **and** (b) the plain text, placed as a value (`k: <s>`) or as a key (`<s>: x`), loads with ruamel safe-load (`YAML(typ="safe", pure=True)`) as the same string under both YAML 1.2 and YAML 1.1 (`version = (1, 1)`). For a key, the loaded document must be exactly `{s: "x"}`, which rules out the merge key `<<`. Otherwise the next style that can hold the string is used: single quotes, else double quotes.
- **Rationale**: The reviewer found strings that are plain under the YAML 1.2 core schema but that common readers turn into something else. Examples: `2001-12-14` reads as a date, `1_000`, `0x1_0` and `0b101` as ints, `yes`/`on` as bools under 1.1, `=` fails, and `<<` is read as a merge key. This breaks NFR-001 as tested (D-8). Quoting more never changes the data, so this is the conservative choice (TROUPE-002). The rule lives in `yamlout.py` only; `set`'s write-back quoting (step-1 FR-015) is unchanged.
