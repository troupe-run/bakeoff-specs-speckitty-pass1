---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-include-overrides-01M46FY4
reproduction_command: spec-kitty agent tasks move-task WP02 --to approved --mission troupe-config-include-overrides-01M46FY4
reviewed_at: '2026-10-05T17:49:23Z'
reviewer_agent: user
wp_id: WP02
---

Approved by user: Review passed: convert_include_edits covers block key-line (contract example byte-exact), next-line value, block list item, document root (BOM-safe), flow mapping/list (FR-020 comment column); D-11 refusal before any edit, exit 3, names PATH and file; CRLF, 4-space step, quoted bytes verbatim; refactors (_add_new_keys/_flow_entries/_insert_lines) behaviour-preserving, existing tests untouched; 201 collections tests pass, mypy/ruff/format clean; only collections.py + test_collections.py changed. Deviations 1-3 accepted per D-5.
