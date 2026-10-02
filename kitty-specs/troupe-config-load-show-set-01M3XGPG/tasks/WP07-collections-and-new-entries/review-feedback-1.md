# WP07 review feedback (cycle 1): changes requested

Reviewed commit `92d020b` (`src/troupe/writeback/collections.py`, `tests/unit/test_collections.py`).
Gates are green: `uv run pytest` 936 passed, `mypy --strict` clean, `ruff check` clean,
`ruff format --check` clean. Most of the work is solid. I ran about 110 adversarial cases, re-loaded
each result with `loader.load(..., overrides=...)` and compared the whole configuration. Nearly all
of them were correct and byte-minimal: nested and trailing comments at several indents, blank lines,
BOM+CRLF, 4-space files, compact `- k: v`, multi-line flow, empty `[]`/`{}`, copying a sibling's
quoting, intermediate mappings, scalar to collection and collection to scalar with and without
comments, and comment-column preservation.

Two defects remain. Each one changes the value of an **existing** entry that the user did not ask
to change. The renderer produces those edits without raising an error. R-17 (verify before write)
in WP08 would turn them into refusals, but the renderers must not depend on that safety net. Both
fixes are small.

## D1. Appending after a clip/keep block scalar at the end of a file with no final newline changes that scalar

`_insert_entry` (and the same pattern in `_below_edits`) puts a line break before the new entry.
When the file's last value is a `|`, `>`, `|+` or `>+` block scalar and the file has no final line
break, that new break becomes the scalar's final line break. The scalar's value goes from `"x"` to
`"x\n"`. `|-`/`>-` are fine.

Reproductions (`new_key_edits` / `new_item_edits`, then re-load):

| Input | Operation | Result | `s` before -> after |
|---|---|---|---|
| `"a:\n  s: >\n    x"` | new key `a.t = 1` | `"a:\n  s: >\n    x\n  t: 1"` | `'x'` -> `'x\n'` |
| `"a:\n  s: \|+\n    x"` | new key `a.t = 1` | same shape | `'x'` -> `'x\n'` |
| `"s: \|\n  x"` | new root key `t = 1` | `"s: \|\n  x\nt: 1"` | `'x'` -> `'x\n'` |
| `"l:\n  - \|\n    x"` | append `y` | `"l:\n  - \|\n    x\n  - y"` | `'x'` -> `'x\n'` |

Required: when the insertion point is the open end of the text and the content just before it ends
a block scalar whose chomping is not strip, do not emit an edit that changes that scalar. The
simplest contract-safe option is to raise `WriteRefused` with a clear message, because changing the
header to `|-` would touch another line. Add a test for each entry point (new key, new item, and the
kind-change path that inserts lines below an anchor at the end of the file).

## D2. The flow-append `":"` heuristic fires when the last entry's own text ends with `:`

`flow_append_edits` checks `text[at - 1] == ":"` for both sequences and mappings, and it does not
check whether that `:` belongs to the last scalar's span. `_replace_in_flow` has the same problem.
Results:

| Input | Operation | Result | Effect |
|---|---|---|---|
| `"l: [C:, D:]  # drives\n"` | append `E` | `l: [C:, D: , E] # drives` | item `'D:'` becomes mapping `{'D': None}` |
| `"m: {a:}\n"` (key `'a:'`) | new key `c = 1` | `m: {a: , c: 1}` | key `'a:'` is renamed `'a'` |
| `"m: {x: 1, a:}\n"` | new key `c = 1` | `m: {x: 1, a: , c: 1}` | key `'a:'` is renamed `'a'` |
| `"m: {a:}\n"` | `replace_value_edits(..., "a:", ..., [1])` | `m: {a: [1]}` | key `'a:'` is renamed `'a'` |
| `"m: {a: b:}\n"` | new key `c = 1` | `m: {a: b: , c: 1}` | file no longer parses |

Required: apply the empty-value colon handling only to a **flow mapping** entry whose value is
empty, and only when the `:` is a separate indicator after `key_origin.end`. A `:` inside the key or
value span does not count. The documented `{a: }` case (`test_flow_mapping_append_after_empty_value`)
must keep working. Add the cases above as tests, and re-load each result to check that the existing
entries are unchanged.

## Deviations judged (no change needed)

- Local `Value` alias, extra `path`/`seq_offset` keyword parameters: acceptable, documented.
- Kind-changing replacement refuses instead of dropping a comment (multi-line value containing `#`;
  comment after a value that starts below its key): acceptable and safe; tested.
- `|+`/`>+` trailing blank lines stay inside the scalar: correct (they are part of its value).
- No-final-newline handling: correct except D1.
- Flush-list rule: a column-0 comment after a column-0 flush list is not "indented less than the
  entries", so the new item goes below it. That is the literal reading of FR-019 and it is
  documented. Accepted.
- `{a: }` append fix: the idea is right, but the trigger is too broad (D2).

## Anti-pattern checklist

1. Dead code: N/A by design. The only consumer is WP08's `apply_set`, which depends on this WP. No
   production caller exists yet.
2. Synthetic-fixture test: PASS. The tests apply real edits and re-load them.
3. Silent empty return: PASS. The `[]` returns are documented "no change" cases.
4. FR coverage: PASS (FR-011/012/016/019 all have named tests).
5. Frozen surface: PASS (only the two owned files are touched).
6. Locked decision: PASS.
