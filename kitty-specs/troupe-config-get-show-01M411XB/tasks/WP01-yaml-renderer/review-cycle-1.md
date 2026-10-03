---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-get-show-01M411XB
reproduction_command:
reviewed_at: '2026-10-03T14:46:21Z'
reviewer_agent: user
wp_id: WP01
---

# WP01 review feedback — cycle 1

The reviewer approved the implementation against D-1…D-7. One read-back defect against NFR-001 / D-8 was found, and the planner turned it into a new rule, **D-10** (research.md, committed on `feat/troupe-config-get-show` in 91813c5). Spec FR-008 was amended to match.

## Required fix

1. **src/troupe/yamlout.py — string values and keys written plain.** A plain string must also read back as the same string with ruamel safe-load (`YAML(typ="safe", pure=True)`) under **both** YAML 1.2 and YAML 1.1 (`yaml.version = (1, 1)`):
   - **Values**: load `k: <s>\n` and require `{"k": s}`.
   - **Keys**: load `<s>: x\n` and require exactly `{s: "x"}`. This excludes the merge key `<<`.
   - If either check fails, use the next style: single quotes if `scalars.can_single(s)`, else double quotes.
   - Keep the check in one helper, used for both values and keys, and keep the existing key-compose check only if it is still needed.
   - Do **not** change `writeback/scalars.py`; the rule is `show`-only.
   - Strings that must now be quoted: `2001-12-14`, `1_000`, `-1_0`, `0x1_0`, `-0x10`, `+0x10`, `-0o7`, `0b101`, `yes`, `no`, `on`, `off`, `y`, `n`, `1:20`, `=`, and the key `<<`. Reviewer probe: `/tmp/renata/div.py`.
2. **tests/unit/test_yamlout.py.** Add a parametrised test over the strings above, as values and as keys. It must assert the exact quoted rendering and that the output reads back as the same string under both YAML 1.1 and 1.2 ruamel safe-load. Extend the read-back property test to load with both versions.
3. Run the gates again and paste the output.

No other changes requested. The 1024-character key gap stays out of scope (beads).
