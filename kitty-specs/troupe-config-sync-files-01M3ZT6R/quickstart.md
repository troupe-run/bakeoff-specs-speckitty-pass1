# Quickstart: sync with files

From the repository root (bash or zsh on macOS or Linux):

```bash
T=$(mktemp -d)
mkdir -p "$T/.troupe"
printf 'model:\n  temperature: 0.2  # creativity\n' > "$T/.troupe/troupe.yml"
edit() { perl -pi -e "$1" "$T/.troupe/troupe.yml"; }   # portable in-place edit (GNU/BSD sed differ)

# Edit while nothing runs; the next command picks it up
uv run troupe config history --theatre "$T"          # import event only
edit 's/0\.2 /0.5 /'
uv run troupe config history --theatre "$T"          # unchanged: history never reconciles
uv run troupe config show model.temperature --theatre "$T"   # 0.5 (reconciles first)
uv run troupe config history --theatre "$T"
# ... {"seq": 2, "op": "set", "path": "model.temperature", "old": 0.2, "new": 0.5}

# Live
uv run troupe config watch --theatre "$T" &          # prints: watching <the value of $T>
WATCH=$!
sleep 3                                              # let it start
edit 's/0\.5 /0.7 /'                                 # recorded within 2 s
sleep 2
edit 's/# creativity/# heat/'                        # comment-only: nothing recorded
uv run troupe config set model.temperature 0.9 --theatre "$T"   # exactly one set event, no echo
kill -INT "$WATCH"; wait "$WATCH"; echo "watch exit: $?"        # 0
uv run troupe config history --theatre "$T"          # seq 1..4; last: 0.7 -> 0.9
rm -rf "$T"
```

Quality gates (run before claiming done):

```bash
uv run pytest && uv run mypy --strict && uv run ruff check && uv run ruff format --check
```
