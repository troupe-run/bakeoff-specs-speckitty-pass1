# Quickstart: sync with files

From the repository root:

```bash
mkdir -p /tmp/t/.troupe
printf 'model:\n  temperature: 0.2  # creativity\n' > /tmp/t/.troupe/troupe.yml

# Edit while nothing runs; the next command picks it up
uv run troupe config history --theatre /tmp/t        # import event only
sed -i 's/0.2 /0.5 /' /tmp/t/.troupe/troupe.yml
uv run troupe config history --theatre /tmp/t        # unchanged: history never reconciles
uv run troupe config show model.temperature --theatre /tmp/t   # 0.5 (reconciles first)
uv run troupe config history --theatre /tmp/t        # + {"op":"set","path":"model.temperature","old":0.2,"new":0.5}

# Live
uv run troupe config watch --theatre /tmp/t &        # prints: watching /tmp/t
sed -i 's/0.5 /0.7 /' /tmp/t/.troupe/troupe.yml      # recorded within 2 s
sed -i 's/# creativity/# heat/' /tmp/t/.troupe/troupe.yml   # comment-only: nothing recorded
uv run troupe config set model.temperature 0.9 --theatre /tmp/t   # exactly one set event, no echo
kill -INT %1                                         # exits 0
uv run troupe config history --theatre /tmp/t
```

Quality gates (run before claiming done):

```bash
uv run pytest && uv run mypy --strict && uv run ruff check && uv run ruff format --check
```
