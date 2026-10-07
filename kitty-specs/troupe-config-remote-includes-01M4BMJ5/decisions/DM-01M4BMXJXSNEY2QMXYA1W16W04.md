# Decision Moment `01M4BMXJXSNEY2QMXYA1W16W04`

- **Mission:** `troupe-config-remote-includes-01M4BMJ5`
- **Origin flow:** `plan`
- **Slot key:** `plan.dependencies.schema-validator`
- **Input key:** `schema_validator`
- **Status:** `resolved`
- **Created:** `2026-10-07T17:00:02.361856+00:00`
- **Resolved:** `2026-10-07T17:03:09.960268+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

How should the configuration be validated against JSON Schema 2020-12: add the jsonschema package (pulls in attrs, referencing, rpds-py, jsonschema-specifications) or hand-write a validator?

## Options

- Add jsonschema (Draft202012Validator, meta-schema check) as a runtime dependency
- Hand-write a validator for the 2020-12 vocabulary
- Other

## Final answer

Agent decision (product owner 2026-10-07: brief silent, take the safest assumption): add jsonschema as a runtime dependency and validate with Draft202012Validator, checking the schema against the 2020-12 meta-schema, with a referencing registry that resolves no remote references and format not asserted. Reason: a hand-written validator that is subtly wrong would wrongly accept or refuse configurations, contradicting the contract's validate rule; the reference implementation passes the official test suite.

## Rationale

_(none)_

## Change log

- `2026-10-07T17:00:02.361856+00:00` — opened
- `2026-10-07T17:03:09.960268+00:00` — resolved (final_answer="Agent decision (product owner 2026-10-07: brief silent, take the safest assumption): add jsonschema as a runtime dependency and validate with Draft202012Validator, checking the schema against the 2020-12 meta-schema, with a referencing registry that resolves no remote references and format not asserted. Reason: a hand-written validator that is subtly wrong would wrongly accept or refuse configurations, contradicting the contract's validate rule; the reference implementation passes the official test suite.")
