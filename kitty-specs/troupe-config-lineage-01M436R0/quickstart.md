# Quickstart: lineage

Run from the repository root. The examples use a scratch theatre.

```bash
T=$(mktemp -d); mkdir -p "$T/.troupe"
printf 'limits:\n  max: 5\nname: demo\n' > "$T/.troupe/troupe.yml"

# 1. First command imports: two import events, one change, actor unknown, via import
uv run troupe config --theatre "$T" history

# 2. An agent changes a value, with a reason
TROUPE_ACTOR=agent:planner uv run troupe config --theatre "$T" set limits.max 10 --reason "raise limit"

# 3. A hand edit, then a read: the edit is recorded via file, actor unknown, its own change
sed -i.bak 's/name: demo/name: prod/' "$T/.troupe/troupe.yml" && rm "$T/.troupe/troupe.yml.bak"
uv run troupe config --theatre "$T" get name

# 4. Unset TROUPE_ACTOR: the actor is the login name
uv run troupe config --theatre "$T" set limits.max 12

# 5. Read the lineage (survives restarts: run it twice, the output is identical)
uv run troupe config --theatre "$T" history
uv run troupe config --theatre "$T" history limits

# 6. Invalid actors exit 2 and record nothing
TROUPE_ACTOR=robot:x uv run troupe config --theatre "$T" get name; echo "exit $?"
TROUPE_ACTOR=human:  uv run troupe config --theatre "$T" history; echo "exit $?"
```

Expected, in outline:
- Step 1: lines with `"via": "import"` and `"actor": {"kind": "unknown", "id": null}` that share one `change`.
- Step 2: `"actor": {"kind": "agent", "id": "planner"}`, `"via": "cli"`, `"reason": "raise limit"`.
- Step 3: `"via": "file"`, actor unknown, `reason` null, and a `change` different from every earlier one.
- Step 4: `"actor": {"kind": "human", "id": "<your login>"}`.
- Step 6: `exit 2` and a stderr line naming `TROUPE_ACTOR`; `history` output unchanged.

Gates: `uv run pytest && uv run mypy --strict && uv run ruff check && uv run ruff format --check`.
