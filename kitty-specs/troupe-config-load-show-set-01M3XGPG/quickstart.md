# Quickstart: troupe config

```bash
uv sync                                   # install deps + troupe console script
mkdir -p /tmp/demo/.troupe/agents
cat > /tmp/demo/.troupe/troupe.yml <<'YML'
model:
  name: "claude"   # default model
  temperature: 0.2
tools: [read, write]
agents:
  coder: file:agents/coder.yaml
YML
printf 'role: coder\n' > /tmp/demo/.troupe/agents/coder.yaml

uv run troupe config show model.temperature --theatre /tmp/demo     # 0.2
uv run troupe config set model.temperature 0.75 --theatre /tmp/demo # only "0.2" → "0.75" changes
uv run troupe config set tools.2 search --theatre /tmp/demo         # tools: [read, write, search]
uv run troupe config set agents.coder.role reviewer --theatre /tmp/demo  # edits agents/coder.yaml
uv run troupe config set agents.coder x --theatre /tmp/demo; echo $?    # 3 (whole include)
uv run troupe config history model --theatre /tmp/demo              # JSON Lines
```

Quality gates (must all pass before delivery):

```bash
uv run pytest
uv run mypy --strict
uv run ruff check
uv run ruff format --check
```
