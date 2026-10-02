---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-load-show-set-01M3XGPG
reproduction_command:
reviewed_at: '2026-10-02T07:17:26Z'
reviewer_agent: user
wp_id: WP06
---

# WP06 Review Feedback (cycle 1)

**Verdict:** REJECT (one blocking contract defect)
**Reviewed commit:** `6892730` (`src/troupe/writeback/blocks.py`, `tests/unit/test_blocks.py`)

Gates in the lane-f worktree all pass: `uv run pytest` (768 passed), `uv run mypy --strict` (clean), `uv run ruff check` (clean), `uv run ruff format --check` (clean).

## Blocking

### B1. Folded values that already contain more-indented lines must be refused (product-owner ruling)

The product owner confirmed that changing a folded (`>`) value whose old content already contains a more-indented line must exit 3. Their reasoning: "writing back a folded value that keeps more-indented lines would put a more-indented line into a folded value". The implementation does the opposite. Deviation 2 in the module docstring, and `replace_folded` at `blocks.py:437-443`, allow the edit when the more-indented unit stays byte-for-byte unchanged. They also allow it when the more-indented unit is removed. Reproduced:

```
a: >
  intro text

    code line
  outro
b: 1
```

- `set` to `"new intro\n\n  code line\ndone\n"` is written as `a: >\n  new intro\n\n    code line\n  done\n`. It should be refused.
- `set` to `"intro text\noutro\n"`, which removes the more-indented line, is written. It should be refused, because the old value contains a more-indented line.
- `set` to `"  code line\noutro\n"` is written with a new `>2` header. It should be refused.

**Required fix:**
1. In `replace_folded`, raise `WriteRefused` (exit 3, message naming `path` and saying "more-indented") when either of these is true:
   - the old value has any `spaced` unit (`any(p.spaced for p in old)`), including whitespace-only lines longer than the content indent, which `folded_paragraphs` already classifies as spaced;
   - the new value would produce a more-indented line. This check exists already.
   Do the check before any other work. A write that leaves the value identical, which produces no edits, may still return `[]`. Do not refuse a no-op.
2. Change the module docstring (the "Folded values are split into units..." bullet) so it says that any change to a folded value with more-indented lines is refused. Remove "written only if it is byte-for-byte an unchanged old one".
3. Tests:
   - Rewrite `test_folded_unchanged_more_indented_line_keeps_its_bytes_when_others_change` and `test_folded_more_indented_line_moving_first_gets_an_indentation_indicator` so they expect `WriteRefused` with exit code 3.
   - Add a case where the new value removes the more-indented line, and one where the old more-indented line is whitespace-only. Both must be refused.
   - Update `test_random_edits_of_hand_written_folded_blocks_read_back_or_refuse` if its oracle assumes such edits succeed.
   - Keep `test_folded_changed_more_indented_line_is_refused`.
4. The `>`-only digit-insertion path in `_rewrite_block` can only fire now for literal blocks, or for folded blocks whose new first line is space-led, which is refused. Check that nothing else depends on it for folded blocks.

## Non-blocking (recommended while you are in there)

### N1. A reordered paragraph with unchanged text is re-wrapped

`difflib` alignment marks only one of two swapped paragraphs as `equal`. The other gets no counterpart and is re-wrapped at the overall width, so its bytes can change even though its text did not:

```
a: >  # c
  one two
  three four five

  six seven
  eight
```

`set` to `"six seven eight\none two three four five\n"` writes `six seven eight` on one line (overall width 15). The original bytes were `six seven` / `eight`. The contract says "paragraphs whose text is unchanged keep their bytes". A cheap fix: when a new text unit is not paired as `equal` but its text equals an old unit's text that is not otherwise used, copy that old unit's lines verbatim. If you prefer the current reading, which only aligns in order, write it down in the docstring as a deliberate interpretation.

### N2. Accepted deviations (no change needed; just confirming)

The difflib alignment otherwise interprets "paragraph with no counterpart" correctly. For example, inserting or removing a paragraph leaves the bytes of later paragraphs unchanged. Position-only matching would not do that. These deviations are acceptable and documented:
- Extra refusals: `keep` chomping followed by blank lines, a following deeper-indented line, trailing non-comment text on the line, and an indicator greater than 9.
- Body lines always end with a line break at EOF.
- A value without a newline that replaces a block stays a block with `-`.
- An empty old folded value has width 0, so each word goes on its own line.

## Verified OK (adversarial, re-composed through `troupe.yamlcore`)

All of these read back exactly:
- CRLF plain-to-literal with the header comment column kept.
- Nested indents (4/6).
- Sequence items and mappings inside sequence items, with and without a space-led first line (`|2` relative to the dash or key column is correct).
- Header comment column kept on chomp changes (`|-` to `|+` and to `|`).
- Greedy-wrap boundary: a line exactly equal to the width fits, and width + 1 breaks.
- EOF without a final newline, for both clip and strip.
- `|+` at EOF.
- Trailing spaces inside folded lines.
- Tab-led literal lines.
- A folded value with a tab or space-led line is refused.
- A leading whitespace-only line in a literal gets an indicator.
- Duplicate paragraphs.

## Orchestrator decision on N1
N1 is REQUIRED, not optional: the contract says "paragraphs whose text is unchanged keep their bytes".
When a new paragraph's text equals an old paragraph's text that has not been used yet, copy that old
paragraph's lines verbatim (including when paragraphs are reordered). Add a test swapping two paragraphs
and asserting both keep their original line breaks/bytes.
