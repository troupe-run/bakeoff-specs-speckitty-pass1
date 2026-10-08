---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-remote-includes-01M4BMJ5
reproduction_command:
reviewed_at: '2026-10-07T18:17:45Z'
reviewer_agent: user
wp_id: WP03
---

# WP03 review feedback (cycle 1)

**Verdict: changes requested**

1. **`src/troupe/schema.py:107-108`: an unresolvable `#anchor` reference gives an empty reason.**
   - **Problem:** `load_schema` accepts any `$ref`/`$dynamicRef` that starts with `#`, so `"$ref": "#foo"` passes even when no `$anchor: foo` exists. During `validate`, jsonschema raises `Unresolvable` wrapping `referencing.exceptions.NoSuchAnchor`, whose `ref == ''` (with `anchor == 'foo'`). The code special-cases only `PointerToNowhere`. The result is `LoadError("cannot load schema …/troupe.schema.json: cannot resolve ")`, and `$dynamicRef: "#nope"` gives the same. That does not meet the T013 contract `cannot resolve {ref}`, and the message gives no reason (TROUPE-003 spirit).
   - **Required:**
     - Name what the user wrote for every `Unresolvable` cause, e.g. `#{cause.anchor}` for `NoSuchAnchor`. As a general fallback, never print an empty ref.
     - Read the cause via the public `error.__cause__`, not the private `_wrapped` attribute.
     - Add a test for a dangling `#anchor` reference (and one for `$dynamicRef`) next to `test_unresolvable_local_reference_during_validation_is_a_load_error` in `tests/unit/test_schema.py`.

Non-blocking:
- `test_property_named_dollar_ref_is_not_a_reference` cannot fail. The meta-schema check forces schema values under `properties`, so the `_NAME_KEYWORDS` exemption is unreachable through `load_schema`. Note it as defensive, or simplify it.
- `len(path)` in `_order` is redundant.
