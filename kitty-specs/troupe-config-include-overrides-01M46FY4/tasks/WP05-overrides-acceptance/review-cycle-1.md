---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-include-overrides-01M46FY4
reproduction_command: spec-kitty agent tasks move-task WP05 --to approved --mission troupe-config-include-overrides-01M46FY4
reviewed_at: '2026-10-05T19:58:05Z'
reviewer_agent: user
wp_id: WP05
---

Approved by user: Review passed: c3z fix in apply._orders walks nested base levels; structure-based check still requires every old key present and exactly one key added, at the end of the view or the end of a nested base block (crafted wrong-position, dropped-key, wrong-value and two-key writes refused). CLI repro: --in-include changes only b.yaml, no-flag adds an override to troupe.yml only. The verifier does not check which file the new key lands in (crafted c.yaml-end/troupe.yml-end writes accepted); this was already true before WP05 (c22 family), and placement decides the file. 35 acceptance tests; 1848 passed, mypy/ruff/format clean.
