# Quickstart: overrides and `--in-include`

```bash
T=$(mktemp -d); mkdir -p $T/.troupe/agents
printf 'coder: file:agents/coder.yaml  # c\n' > $T/.troupe/troupe.yml
printf 'model: gpt\ntemperature: 0.7\n' > $T/.troupe/agents/coder.yaml

uv run troupe config set coder.top_p 0.9 --theatre $T
cat $T/.troupe/troupe.yml          # coder:  # c / $ref: file:agents/coder.yaml / top_p: 0.9
cat $T/.troupe/agents/coder.yaml   # unchanged

uv run troupe config set coder.temperature 0.5 --theatre $T   # not overridden: changes coder.yaml
uv run troupe config set coder.top_p 0.8 --theatre $T         # overridden: changes troupe.yml

uv run troupe config set --in-include coder.max_tokens 100 --theatre $T   # appended to coder.yaml
uv run troupe config show coder --sources --theatre $T
uv run troupe config history --theatre $T
```

Expected `show coder --sources`: `model`, `temperature`, `max_tokens` from `.troupe/agents/coder.yaml`; `top_p` from `.troupe/troupe.yml`.
