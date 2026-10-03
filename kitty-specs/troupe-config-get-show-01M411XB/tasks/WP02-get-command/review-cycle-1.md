---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-get-show-01M411XB
reproduction_command: spec-kitty agent tasks move-task WP02 --to approved --mission troupe-config-get-show-01M411XB
reviewed_at: '2026-10-03T14:56:31Z'
reviewer_agent: user
wp_id: WP02
---

Approved by user: Review passed (reviewer-renata): get PATH byte-identical to step-1 show on scalars (27 cases ported), refuses sections exit 5 with config show hint from one constant, show untouched; gates green (1312 passed, mypy strict, ruff)
