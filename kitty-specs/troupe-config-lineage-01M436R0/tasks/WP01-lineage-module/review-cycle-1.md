---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-lineage-01M436R0
reproduction_command:
reviewed_at: '2026-10-04T11:07:43Z'
reviewer_agent: user
wp_id: WP01
---

# WP01 review feedback (cycle 1)

The implementation in src/troupe/lineage.py is correct and complete against the WP prompt,
D-3..D-6, data-model.md and contracts/cli.md. Gates pass (38 passed; mypy --strict clean;
ruff check/format clean). One blocking item, a test-name/body mismatch under TROUPE-005 /
charter review checklist item 2.

## Blocking

**Issue 1 — tests/unit/test_lineage.py:179 `test_lineage_fields_are_flat_and_ordered`: the name claims key order, but the body does not check it.**
The body compares `lineage_fields(made)` to a dict literal with `==`. Dict equality ignores
insertion order, so the test still passes if the keys come back in a different order. The
"ordered" part of the name is never checked.
Fix (pick one):
- assert the order directly, e.g.
  `assert list(lineage_fields(made)) == ["actor_kind", "actor_id", "via", "at", "reason", "change"]`
  in addition to the existing equality; or
- rename to `test_lineage_fields_are_flat` if key order is not something this module promises.
  The history line order belongs to contracts/cli.md and WP03's serializer, so renaming is
  probably the better choice.

## Non-blocking (optional)

- src/troupe/lineage.py:182, :194: the `lineage_fields` / `lineage_from_fields` docstrings cite
  no FR/D/DM id. The module docstring covers the mapping, but citing data-model.md (Lineage) or
  FR-004/FR-005 would match the other functions.
- tests/unit/test_lineage.py:78-86: the parametrized exact-message check builds its expected
  message with the same f-string as the implementation, so it mirrors the code rather than the
  contract. That is fine because the literal check at :89 pins the contract text. Just noting it.
