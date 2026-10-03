# Decision Moment `01M411YHFR2PMJEJWMHX4KN9C4`

- **Mission:** `troupe-config-get-show-01M411XB`
- **Origin flow:** `specify`
- **Slot key:** `specify.show.scalar-sources`
- **Input key:** `show_scalar_sources`
- **Status:** `resolved`
- **Created:** `2026-10-03T14:16:06.392926+00:00`
- **Resolved:** `2026-10-03T14:16:48.215460+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

When show PATH --sources targets a single scalar, what is printed?

## Options

- YAML scalar with source comment
- Plain value unchanged (--sources ignored for scalars)
- Plain value then a separate from-line
- Other

## Final answer

YAML scalar with source comment: out of contract per PO; agent chose (A) - with --sources a scalar PATH prints as a YAML scalar (text include / multi-line string as a literal block) with '# from <file>' on its line (header line for blocks); without --sources it prints like get.

## Rationale

_(none)_

## Change log

- `2026-10-03T14:16:06.392926+00:00` — opened
- `2026-10-03T14:16:48.215460+00:00` — resolved (final_answer="YAML scalar with source comment: out of contract per PO; agent chose (A) - with --sources a scalar PATH prints as a YAML scalar (text include / multi-line string as a literal block) with '# from <file>' on its line (header line for blocks); without --sources it prints like get.")
