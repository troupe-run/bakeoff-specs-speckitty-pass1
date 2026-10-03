# Quickstart: get and show

```bash
T=$(mktemp -d) && mkdir -p "$T/.troupe/prompts"
printf 'name: demo\nserver: file:server.yml\ntools: [a, b]\nprompt: file:prompts/sys.md\n' > "$T/.troupe/troupe.yml"
printf 'port: 8080\n' > "$T/.troupe/server.yml"
printf 'Be brief.\n' > "$T/.troupe/prompts/sys.md"

uv run troupe config get server.port --theatre "$T"        # 8080
uv run troupe config get server --theatre "$T"; echo $?    # stderr: ... use 'troupe config show server'; 5
uv run troupe config show server.port --theatre "$T"       # 8080  (same as get)
uv run troupe config show server --theatre "$T"            # port: 8080
uv run troupe config show --theatre "$T"                   # whole configuration as YAML
uv run troupe config show --sources --theatre "$T"         # same, with "# from <file>" per scalar line
uv run troupe config show server.port --sources --theatre "$T"   # 8080 # from .troupe/server.yml
```

Expected `show --sources` output: see the example in `contracts/cli.md`.

Gates: `uv run pytest && uv run mypy --strict && uv run ruff check && uv run ruff format --check`.
