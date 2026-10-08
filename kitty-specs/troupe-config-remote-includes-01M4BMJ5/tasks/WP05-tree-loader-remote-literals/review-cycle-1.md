---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-remote-includes-01M4BMJ5
reproduction_command:
reviewed_at: '2026-10-07T19:55:25Z'
reviewer_agent: user
wp_id: WP05
---

# WP05 review feedback (cycle 1)

**Verdict: changes requested**

1. **The inline `<<` remount lets a step-6 `set` silently change a value outside PATH (data safety, TROUPE-002).**
   - **Where:** `src/troupe/loader.py`, in `_entries` (the `_is_merge_key(raw_key)` branch calling `_convert(raw_value, file, steps, merge_source=True)`) and the `steps if merge_source else ...` line in `_content`.
   - **Problem:** Anchors inside an inline `<<` value now get the holding mapping's path as `Anchor.path` instead of `holder.<<[.i]...`. `writeback/apply.py` `_same_alias` uses `_anchor_path` (via `_same_outside`, R-8 rule 1) to tell apart two anchored nodes with the same name, and anchor redefinition is allowed. So an inline merge-source anchor and a written anchor of the same name can now share one path, and the verifier no longer sees an alias rebinding.
   - **Failing scenario:**
     ```yaml
     m:
       <<: {k: {r: &a 1}}
       k: {r: &a 2}
     z: *a
     ```
     Run `apply_set(root, ["m","k"], "m.k", parse_value("{r: 3}"), "{r: 3}")`.
     - Base and `672f1f0`: refused (`m.k: cannot write this change byte-surgically; no file changed`).
     - HEAD `d963d6a`: the plan is accepted and writes `k:\n    r: 3`, and `z` silently changes from 2 to 1.
     - The list form `<<: [{k: {r: &a 1}}, {j: 0}]` behaves the same.
     - Reproduction: `/tmp/wp05r/probe.py`.
   - **Required:**
     - Keep the S-7 schema lookup (`_uri` / `_holds_include`) at the merge mount point.
     - Keep `Anchor.path` (anchor identity) as before for merge-source content (`holder.<<[.i]...`). For example, thread a separate identity path next to the schema steps.
     - Add a regression test: this exact case is refused with exit 3 and no file changed, at the `apply_set` level, which is the only place the verifier is reachable before WP08. Put it in `tests/unit/test_loader_literals.py` or `tests/unit/test_loader_remote.py`.
     - `test_inline_merge_source_strings_are_judged_at_the_merged_path` must keep passing.

Non-blocking:
- The tagged-key check runs per mapping, so an earlier sibling include can be fetched before a later `!literal` key is refused. That is acceptable; the spec does not require "before any fetch".

Everything else was verified as specified. Keep it unchanged.
