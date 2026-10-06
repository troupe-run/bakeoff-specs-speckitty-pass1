# Quickstart: anchors, aliases and `--expand-alias`

```bash
mkdir -p /tmp/th/.troupe
cat > /tmp/th/.troupe/troupe.yml <<'EOF'
defaults: &d
  model: opus
coder:
  settings: *d
reviewer:
  settings: *d
EOF
cd /work/bakeoff-specs-speckitty

uv run troupe config --theatre /tmp/th get coder.settings.model        # opus
uv run troupe config --theatre /tmp/th set coder.settings.model sonnet  # exit 3, mentions --expand-alias
uv run troupe config --theatre /tmp/th set defaults.model haiku         # everyone now haiku
uv run troupe config --theatre /tmp/th set --expand-alias coder.settings.model sonnet
cat /tmp/th/.troupe/troupe.yml
# defaults: &d
#   model: haiku
# coder:
#   settings:  # expanded from *d by troupe
#     model: sonnet
# reviewer:
#   settings: *d
uv run troupe config --theatre /tmp/th history
```

Expected history (after the import): one `set` event each for `defaults.model`, `coder.settings.model` and `reviewer.settings.model` (the anchor change). Then one `set` event for `coder.settings.model` (the expand-and-set).
