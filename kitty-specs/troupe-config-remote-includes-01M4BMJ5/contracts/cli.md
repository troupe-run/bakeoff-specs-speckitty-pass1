# CLI contract as delivered: Remote includes and schema (step 7)

Contract text (verbatim from the product owner, step 7):

- A string starting `https://` or `http://` is also an include; it is fetched when the configuration loads (YAML if the URL path ends `.yml`/`.yaml`, otherwise text). A failed fetch → exit 4.
- Changing a value that comes from a remote include → exit 3; stderr contains the include string exactly as written in the local file. (New keys under a remote include become local overrides, per step 5.)
- `<dir>/.troupe/troupe.schema.json` (JSON Schema 2020-12), if present, describes the configuration. A string whose schema — found through `properties`, `items` and `additionalProperties` — has `"format": "uri"` is a literal, not an include. A string tagged `!literal` is a literal.
- The loaded configuration must validate against the schema, else exit 4. A `set` that would make it invalid → exit 3.
- `set PATH VALUE` where `VALUE` is a string that would be read as an include and the schema does not mark `PATH` as `format: uri` writes it tagged `!literal`, unless `--include` is given.

## Command surface

```
troupe config set [--reason TEXT] [--in-include] [--expand-alias] [--include] PATH VALUE
```

`--include` is accepted only by `set`, anywhere among its options (S-12).

| Exit | New causes in step 7 |
|---|---|
| 0 | Value set; include-looking strings are written `!literal …` unless `--include` is given or the schema marks their path `uri` (S-11, S-13). |
| 2 | `--include` on `get`/`show`/`history`/`watch`; any tag (including `!literal`) in VALUE. |
| 3 | Changing remote content (S-4); a result that fails the schema (S-9); `--include` where the new include cannot be read or fetched, or where its path is marked `uri` (S-12). |
| 4 | Failed fetch (S-2); URL cycle (S-1); invalid schema file (S-8); configuration fails the schema (S-8); `!literal` on a mapping, list or `$ref` value, `!literal` on a mapping key, or any other tag (S-10, S-3). |
| 5 | Unchanged. |

## Messages (stderr, one `troupe: ` line, stdout empty)

| Case | Message shape |
|---|---|
| Failed fetch | `cannot fetch <url> (included from <local or remote including location>, at <path>): <reason>` where the reason is `HTTP 404 Not Found`, `timed out after 10 s`, `redirect to <url> refused (only http and https)`, `not valid UTF-8 at byte N`, or a network or TLS error |
| URL cycle | `include cycle at <path>: <loc> -> <loc> -> <loc>` |
| Remote refusal | `<PATH>: value comes from remote include <include string as written> (<local file> line N); troupe does not change remote content — change that include line instead; no file changed` |
| Schema file | `cannot load schema <schema file>: <reason>` (not JSON or not UTF-8; `$schema` is not 2020-12; fails the meta-schema; non-fragment `$ref`) |
| Invalid configuration (load) | `configuration does not match schema <schema file> at <path>: <validator message>` |
| Invalid result (`set`) | `<PATH>: the change would not match schema <schema file> at <path>: <validator message>; no file changed` |
| `--include` on a `uri` path | `<PATH>: schema <schema file> marks <path> as format uri, so it cannot be an include; no file changed` |
| `--include` target unreadable | `<PATH>: <load error naming the include target or URL>; no file changed` |
| Bad tag | other tags keep the step-6 message `cannot parse <file>: tags are not supported at line N`; `!literal` on a mapping or list: `cannot parse <file>: !literal applies only to scalars at line N`; `!literal` on a `$ref` value: `cannot load <file>: <path>.$ref must be an include string, not !literal (line N)`; `!literal` on a mapping key: `cannot load <file>: mapping key at line N under <path> is tagged !literal; keys are never includes` |

## Agent choices

Spec S-1 to S-13 (see [spec.md](../spec.md)). They are recorded there and are not amendments to this contract.

## Examples

```yaml
# .troupe/troupe.yml                       # after `set team.temperature 0.3`
team: https://cfg.example.com/team.yaml    team:
                                             $ref: https://cfg.example.com/team.yaml
                                             temperature: 0.3
```

```
$ troupe config set team.model sonnet
troupe: team.model: value comes from remote include https://cfg.example.com/team.yaml (/…/.troupe/troupe.yml line 1); troupe does not change remote content — change that include line instead; no file changed
$ echo $?
3
```

```
$ troupe config set docs https://x.example/y        # writes  docs: !literal https://x.example/y
$ troupe config set --include extra https://cfg.example.com/x.yaml   # writes an include
```
