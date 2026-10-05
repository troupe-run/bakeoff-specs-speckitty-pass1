---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-include-overrides-01M46FY4
reproduction_command:
reviewed_at: '2026-10-05T19:07:57Z'
reviewer_agent: user
wp_id: WP04
---

# WP04 review feedback (cycle 1): changes requested

## Issue 1 (blocking): verifier falsely refuses `set --in-include` for a new key under an include that already has override-only keys

**Where:** `src/troupe/writeback/apply.py`, `_same_outside`, MappingNode branch:

```python
if new_keys != old_keys:
    added = target[len(here)] if on_route else None
    if added is None or added in old_keys or new_keys != [*old_keys, added]:
        return False
```

**Problem:** A merged view lists the included (base) keys first, then the override-only keys (FR-002, research R-1). If `--in-include` adds a key to the *included* file while the view already has override-only keys, the new key appears in the middle of the merged key list, not at the end. The verifier only accepts `[*old_keys, added]`, so it refuses a correct rendering with exit 3. FR-010 is broken in this case, and so is the mission's own quickstart.

**Reproduction (quickstart.md run verbatim):**

```
printf 'coder: file:agents/coder.yaml  # c\n' > $T/.troupe/troupe.yml
printf 'model: gpt\ntemperature: 0.7\n' > $T/.troupe/agents/coder.yaml
troupe config set coder.top_p 0.9 --theatre $T                  # exit 0
troupe config set coder.temperature 0.5 --theatre $T            # exit 0
troupe config set coder.top_p 0.8 --theatre $T                  # exit 0
troupe config set --in-include coder.max_tokens 100 --theatre $T
# -> troupe: coder.max_tokens: cannot write this change byte-surgically; no file changed  (exit 3)
```

Expected (quickstart): `max_tokens: 100` is appended to `coder.yaml`, and `show coder --sources` lists `model`, `temperature`, `max_tokens` from coder.yaml and `top_p` from troupe.yml.

With `_same_outside` bypassed, the rendering is correct: `coder.yaml` becomes `model: gpt\nmax_tokens: 100\n`, and the merged key order is `['model', 'max_tokens', 'top_p']` against the old `['model', 'top_p']`. Only the verification is wrong.

The nested form fails the same way:
`troupe.yml = "coder:\n  $ref: file:c.yaml\n  limits:\n    x: 1\n"`, `c.yaml = "limits:\n  a: 1\n"`, `set --in-include coder.limits.b 2` gives exit 3, although it should append `b: 2` under `limits` in c.yaml.

The control case passes: when every override key is also a base key, `set --in-include coder.b 2` gives exit 0.

**Required fix:**
- Allow the added key's position to follow from the merge rule. When old and new are both `MergedMapping` on the route, accept `new_keys` equal to `old_keys` with `added` inserted either at the end (new override-only key) or at the end of the base-key block (new base key). Keep everything else strict. One way to do this is to compute the expected order from the sides (the base keys of `new.base` plus the override-only keys) instead of the plain-mapping rule. Do not loosen the check for plain mappings or off the route.
- Add CLI story tests to `tests/integration/test_set_in_include.py` that snapshot every file:
  - (a) Flat: `coder: {$ref, top_p}` + `set --in-include coder.max_tokens 100`. `coder.yaml` gets the key and `troupe.yml` is byte-identical.
  - (b) Nested: the `limits` case above.
- Add a crafted-rendering verifier test showing that a key inserted at any other position in a merged view is still refused.
- Ideally, add one test that runs the quickstart sequence end to end.

## Non-blocking notes

- `_same_outside` compares a `MergedMapping` with a `MergedMapping` only by `ref` target and merged entries. A value that moves between the override side and the base side with an identical merged result would not be caught by verification. Placement prevents this today and it is not a WP04 regression. Consider a follow-up bead to also compare which side each key comes from.
- The `_gains_override` docstring says "that file is not the one being written", but the code does not check this. Either drop the sentence or assert it.
