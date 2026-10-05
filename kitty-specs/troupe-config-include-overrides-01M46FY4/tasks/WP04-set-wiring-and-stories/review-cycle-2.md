---
affected_files: []
cycle_number: 2
mission_slug: troupe-config-include-overrides-01M46FY4
reproduction_command: spec-kitty agent tasks move-task WP04 --to approved --mission troupe-config-include-overrides-01M46FY4
reviewed_at: '2026-10-05T19:25:48Z'
reviewer_agent: user
wp_id: WP04
---

Approved by user: Review passed (cycle 2): _orders allows a new base key at the end of the base block in merged views, entries paired by key with exact one-key-added order check; quickstart and nested --in-include repros pass via CLI; 1813 passed, mypy/ruff clean. Non-blocking: chained mapping-form include (c.yaml itself $ref + overrides) with --in-include still refuses exit 3 safely; suggest follow-up bead.
