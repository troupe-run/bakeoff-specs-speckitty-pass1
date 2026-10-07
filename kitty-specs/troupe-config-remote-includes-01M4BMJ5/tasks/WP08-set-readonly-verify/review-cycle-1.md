---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-remote-includes-01M4BMJ5
reproduction_command:
reviewed_at: '2026-10-07T21:55:27Z'
reviewer_agent: user
wp_id: WP08
---

# WP08 review feedback (cycle 1)

**Verdict: changes requested**

1. **The remote check for planned writes runs too late, so renderer refusals answer first** (`src/troupe/writeback/apply.py:250-251`, in `apply_set`).
   - **Problem:** `_refuse_remote(root, segments, dotted, [file])` runs only after `file, edits = _edits(placement, dotted, value)`. The renderers that `_edits` calls (`new_key_edits`, `new_item_edits`, `convert_include_edits`) have their own refusals. When the plan would write remote content, one of those can fire first. The command still exits 3 and changes no file, but the message lacks the outermost local include string, which S-4/FR-004 require. R-7 requires the contract message before "the other step 1–6 refusals can claim the case". Reproduced with the CLI:
     - **(a)** Remote `t2.yaml` = `tools:\n  - a\nitems:\n  - n: 1\nnote: |\n  text` (no trailing newline); local `t: http://127.0.0.1:PORT/t2.yaml`.
       - Command: `set --in-include t.newk 2`.
       - Output: `troupe: cannot write t.newk in http://…/t2.yaml: the file ends inside a block scalar without a final line break, …`
     - **(b)** Remote `t3.yaml` = `x: >-\n  http://127.0.0.1:PORT/inner.yaml\n` (a nested remote include written as a folded block scalar); local `u: http://127.0.0.1:PORT/t3.yaml`.
       - Command: `set u.x.newk 1`.
       - Output: `troupe: u.x.newk: the include at http://…/t3.yaml line 1 spans several lines; cannot convert it …` (names the remote file, not the outermost local include).
   - **Required:**
     - Decide the file to be written from the placement itself, before rendering any edits:
       - `ConvertInclude` → `include.origin.file`
       - `AddKeys` → `mapping.origin.file`
       - `AppendItem` → `sequence.origin.file`
       - `ReplaceCollection` / `ReplaceScalar` → `node.origin.file`
     - Call `_refuse_remote` on that file before `_edits`. The post-`_edits` call may stay as a second check.
     - Add a regression test for each case (a) and (b), asserting the contract's remote-refusal message.

Non-blocking:
- Setting a remote include to its own current string (`set --include docs <same URL>`) is refused rather than treated as a no-op. That is consistent with "refusal before no-op".
- Deviations (a)–(d) declared in the implementer's report are accepted.

Everything else was verified, including the three handoff notes. Keep it unchanged.
