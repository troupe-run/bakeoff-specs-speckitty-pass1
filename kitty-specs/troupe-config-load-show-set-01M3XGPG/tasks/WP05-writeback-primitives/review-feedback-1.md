# WP05 review feedback (cycle 1)

Reviewed commit `5a28161`. Gates: pytest 474 passed, mypy --strict clean, ruff check clean,
ruff format --check clean. Data safety holds: across ~140 adversarial inputs (`true`, `0x1`, `1e3`,
`~`, `null`, `'a`, `a:`, `- a`, `? a`, `a #b`, `@x`, `%x`, `---`, leading/trailing spaces, NBSP,
`file:x`, `1_000`, `2001-12-14`, `<<`, U+0085/2028, surrogates, U+FFFE/FFFF), in both block and
flow context, every rendered string read back through `troupe.yamlcore` as exactly the same string.
`render_nonstring` round-trips `1e+20`, `-0.0`, `5e-324`, `.inf`, `-.inf`, `.nan`. The comment
column rule (including `#` inside quotes, flow lines, and CJK columns), `atomic_write`, and
`apply_edits` all behave correctly.

## Blocking issue (1)

### B1: `can_single` (and `can_plain`) reject YAML-printable characters, which breaks FR-015 style selection

`scalars.py` uses `str.isprintable()` as its "printable" test. Python returns False for every
Unicode category Z* except ASCII space, and for every C* category, including Cf (format), Co
(private use), and Cn (unassigned). YAML 1.2 `c-printable` accepts all of these, and so does
`troupe.yamlcore`: plain, single-quoted, and flow forms all compose back to the identical text.
R-10 says single-quoted works "iff the value has no line breaks and no characters requiring escapes
(control characters)". ZWJ, NBSP, and similar characters are not control characters.

Observable contract violations (verified):

- `choose_style("👩‍💻 dev", None, "block")` returns `double`. The contract says plain (`k: 👩‍💻 dev` round-trips).
  The emoji ZWJ sequence (U+200D) is a realistic input.
- `choose_style("a b", "single", "block")` returns `double`. The contract says **keep single**,
  because single-quoted can represent NBSP. "A changed scalar keeps its quoting style if that style can represent the new value."
- The same happens for U+200B, U+00AD, U+3000, U+200E, private-use characters, and so on.

Fix: replace `isprintable()` with a YAML c-printable predicate, minus what this module must still
refuse:
- `can_single`: allow `\t`, `0x20-0x7E`, `0xA0-0xD7FF`, `0xE000-0xFFFD` except U+FEFF (keep it
  refused if you want to be conservative), and `0x10000-0x10FFFF`. Exclude U+0085, U+2028, and
  U+2029, because ruamel treats them as line breaks.
- `can_plain`: use the same predicate without `\t`. Keep the existing syntactic rules and the
  round-trip check. Optionally keep refusing non-ASCII whitespace (NBSP, U+3000) at the very start or end.
  That is a defensible conservative choice, as long as single-quoted is still chosen for those values.
- Add tests: `👩‍💻 dev` gives plain; `a b` with preferred `single` stays single; `a​b` with
  `None` gives plain. All three must round-trip through `yamlcore`.

## Non-blocking notes (no action needed for approval)

- **Tab goes to single-quoted instead of the WP prompt's example of double.** The WP prompt's example is
  wrong and the implementation is right. YAML single-quoted scalars allow tab, the contract says
  "else single-quoted, else double-quoted", and the round-trip is verified. Accepted.
- **Extra `\uXXXX` escapes for surrogates and U+FFFE/FFFF.** These characters are not YAML-printable,
  so escaping them is something "YAML requires". This is consistent with the contract. Accepted.
- **Refusing `---`/`...` as plain, and refusing a leading `-?:` before a non-space (`-v`, `:x`).**
  This is conservative and was sanctioned by the WP prompt, but strictly it falls short of "plain if possible": `-v` becomes
  `'-v'`. Consider relying on the round-trip check for `-`/`?`/`:` followed by a non-space, or escalate the
  deviation to the planner. Not blocking.
- **The quote-start rule in `find_comment_start`.** When `from_col` precedes an unquoted plain
  scalar that contains ` '` or ` "`, e.g. `[a, x 'y]  # c` with `a` replaced, the scan wrongly enters
  quote state and misses the comment. This is unreachable for the normal block "value then comment" case,
  and rare in flow lines. Consider documenting it, or skipping quote tracking inside a plain scalar.
- **`atomic_write` requires the file to already exist.** This fits R-12, which only replaces changed existing
  files. If a later WP ever creates files, it needs a separate path.

## Orchestrator addition (contract "otherwise plain if possible")

B2 (required): `can_plain` must accept a leading `-`, `?` or `:` when the next character is a
non-space "safe" character and the round-trip check through `yamlcore` confirms a plain scalar with
the same text (e.g. `-v`, `:x`, `?x` in block context; in flow context `-x` only if the round-trip
check passes). Keep refusing `---` / `...` prefixes and everything that fails the round-trip.
Add tests: `choose_style("-v", None, "block") == "plain"`, `choose_style(":x", None, "block") == "plain"`,
and a test that every accepted plain string round-trips to an identical `str` through `yamlcore`.
