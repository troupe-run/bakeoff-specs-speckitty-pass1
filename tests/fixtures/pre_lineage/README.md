# Pre-lineage fixture

A real configuration history written by the step-3 code (commit `a589041`, the last commit on
`main` before lineage), used to test how the current code reads events recorded before lineage
existed (research D-9, FR-013).

It was produced by:

```bash
uv run python tests/fixtures/pre_lineage/make_fixture.py
```

The script checks out `a589041` in a temporary detached git worktree (always removed), runs that
code's CLI with the current interpreter, and records, in a scratch theatre:

1. `config history`: the import of the five leaves of the initial `troupe.yml` (seq 1-5);
2. `config set model.temperature 0.5` (seq 6);
3. a hand edit (`retries: 3` deleted, `name: gpt` changed to `name: claude`), reconciled by
   `config get model.name` (seq 7-8).

Regenerating gives new timestamps, so all three generated files must be committed together.

**Tests must copy these files into a temporary theatre and never open them in place.**

| File | What it is |
|---|---|
| `history.sqlite` | The eventsourcing SQLite store written by `a589041`, WAL checkpointed (self-contained). |
| `troupe.yml` | The configuration in its final, hand-edited state, matching the history. |
| `expected_history.jsonl` | Oracle: what `troupe config history` must print for this store once lineage exists (contracts/cli.md, "Events recorded before step 4"). Computed from the raw `stored_events` rows with `sqlite3`/`json`, not with troupe code. |
| `make_fixture.py` | The generator script above. Not collected by pytest. |
