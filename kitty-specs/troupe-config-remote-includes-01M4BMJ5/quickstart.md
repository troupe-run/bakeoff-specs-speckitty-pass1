# Quickstart: remote includes and a schema (manual walkthrough)

Run from the repository root. A local server stands in for the team's configuration host.

```bash
T=$(mktemp -d); mkdir -p "$T/.troupe" "$T/srv"
printf 'model: opus\ntemperature: 0.7\n' > "$T/srv/team.yaml"
(cd "$T/srv" && exec python3 -m http.server 8765 --bind 127.0.0.1) & SRV=$!
sleep 1   # let the server start
cat > "$T/.troupe/troupe.yml" <<'EOF'
team: http://127.0.0.1:8765/team.yaml
webhook: https://hooks.example.com/notify
EOF
cat > "$T/.troupe/troupe.schema.json" <<'EOF'
{"$schema": "https://json-schema.org/draft/2020-12/schema",
 "type": "object",
 "properties": {"webhook": {"type": "string", "format": "uri"},
                "team": {"type": "object", "properties": {"model": {"type": "string"},
                                                   "max_tokens": {"type": "integer"}}}}}
EOF
export TROUPE_THEATRE="$T"

uv run troupe config get team.model                 # opus (fetched)
uv run troupe config get webhook                    # https://hooks.example.com/notify (the webhook URL is not fetched: format uri)
uv run troupe config show --sources                 # team.* attributed to http://127.0.0.1:8765/team.yaml
uv run troupe config set team.model sonnet; echo $? # 3, stderr shows http://127.0.0.1:8765/team.yaml
uv run troupe config set team.max_tokens 2000       # new key: becomes a local override ($ref form)
uv run troupe config set docs https://x.example/y   # written as  docs: !literal https://x.example/y
uv run troupe config set team.max_tokens lots; echo $?   # 3: the local override would not match the schema
cat "$T/.troupe/troupe.yml"
kill $SRV; uv run troupe config get team.model; echo $?   # 4: failed fetch names the URL and troupe.yml
rm -rf "$T"
```
