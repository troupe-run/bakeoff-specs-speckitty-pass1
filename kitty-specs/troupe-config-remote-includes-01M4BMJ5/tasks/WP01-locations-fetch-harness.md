---
work_package_id: WP01
title: Locations, fetching and the HTTP test harness
dependencies: []
requirement_refs:
- C-006
- FR-003
- NFR-004
planning_base_branch: feat/troupe-config-remote-includes
merge_target_branch: feat/troupe-config-remote-includes
branch_strategy: Planning artifacts for this mission were generated on feat/troupe-config-remote-includes. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/troupe-config-remote-includes unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
phase: Phase 1 - Foundations
history:
- at: '2026-10-07T18:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/troupe/remote.py
create_intent:
- src/troupe/location.py
- src/troupe/remote.py
- tests/remote_server.py
- tests/unit/test_remote_fetch.py
execution_mode: code_change
model: ''
owned_files:
- src/troupe/location.py
- src/troupe/remote.py
- src/troupe/errors.py
- tests/remote_server.py
- tests/conftest.py
- tests/unit/test_remote_fetch.py
role: implementer
tags: []
task_type: implement
tracker_refs:
- bakeoff-specs-speckitty-1j5
---

# Work Package Prompt: WP01 – Locations, fetching and the HTTP test harness

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter (`agent_profile`, `role`, `agent`), and behave according to its guidance before parsing the rest of this prompt.

If no profile is specified, run `spec-kitty agent profile list` and select the best match for this work package's `task_type` and `authoritative_surface`.

---

## ⚠️ IMPORTANT: Review Feedback

- **Has review feedback?**: Check the `review_ref` field in the event log (via `spec-kitty agent tasks status`) or the Activity Log below.
- **You must address all feedback** before your work is complete.

---

## Objective

This WP lays the foundation every later WP builds on, and changes no existing behaviour:

1. `src/troupe/location.py` (new, no imports from `troupe`): `Url` and `Location = Path | Url` (research R-1).
2. `src/troupe/remote.py` (new): `fetch(url: Url) -> str`. It is **the only code in troupe that touches the network** (R-2, spec S-2). Each failure raises `FetchError`, a new `LoadError` subclass in `errors.py` (exit 4).
3. A real HTTP server for tests, `tests/remote_server.py`, plus fixtures in `tests/conftest.py`. Every later WP tests remote behaviour with them (R-13, C-006).

## Context

- Spec: S-2, NFR-004, C-006; FR-003.
- Research: **R-1**, **R-2**, **R-13**.
- Existing code to mirror:
  - `loader.read_source` (strict UTF-8, BOM kept in the text, messages "cannot read {path}: …").
  - `errors.py` (single place for exit codes).
  - `tests/conftest.py` (`run_cli` runs `python -m troupe` in a subprocess and removes `TROUPE_THEATRE`/`TROUPE_ACTOR`).
- **Environment**: the development container sets `HTTP_PROXY`/`HTTPS_PROXY` and `NO_PROXY=localhost,127.0.0.1`. `urllib` honours these. The harness must not depend on the developer's shell, so `run_cli` must set `NO_PROXY`/`no_proxy` to include `127.0.0.1,localhost` explicitly (T004).

## Branch Strategy

- Planning/base branch: `feat/troupe-config-remote-includes`. Final merge target: `feat/troupe-config-remote-includes`, which is merged into `main` locally after acceptance.
- Execution worktrees are allocated per computed lane from `lanes.json`. Run `spec-kitty agent action implement WP01 --agent <name>`. This WP has no dependencies.

## Subtasks

### T001 — `location.py`: `Url`, `Location`

```python
@dataclass(frozen=True)
class Url:
    """An absolute http(s) URL, as written or as resolved by ``urljoin`` (spec S-1)."""
    text: str
    def __str__(self) -> str: return self.text

type Location = Path | Url
```

- Equality and hashing go by `text` (frozen dataclass). Do **not** normalise the text (no lower-casing, no trailing-slash games). URLs are used as written or as `urljoin` produced them, and messages must show exactly that.
- `__str__` returning the text matters: later WPs keep `SourceFile.path` as the field name but retype it to `Location` (R-1). Every existing f-string message such as `f"cannot load {file.path}: …"` must then print the URL unchanged.
- Docstring: explain why this module has no dependencies. `tree.py`, `includes.py` and `remote.py` all import it, so it must sit at the bottom of the import graph.

### T002 — `FetchError` and `remote.fetch`

**`errors.py`**: add `class FetchError(LoadError)` (exit 4 is inherited). Its constructor is `FetchError(url: str, reason: str)`; it keeps both as attributes and builds the message `cannot fetch {url}: {reason}`. Its docstring says the message names the URL. The loader (WP05) adds the including file and the path by raising a new `FetchError`-compatible `LoadError` whose message is `cannot fetch {url} (included from {including}, at {path}): {reason}` (contract table). That is why `reason` must be available separately. `fetch` itself names only the URL and the reason. `errors.py` must not import `location.py` (keep it at the bottom of the graph), so pass `str(url)`.

In the bullets below, `FetchError(f"cannot fetch {url}: X")` is shorthand for `FetchError(str(url), "X")`.

**`remote.py`**:

```python
FETCH_TIMEOUT_SECONDS: Final = 10.0
_CHUNK: Final = 65536

def fetch(url: Url) -> str: ...
```

Requirements, each with a test in T005:
1. **Request**: `GET` with `urllib.request.Request(url.text, method="GET")`. Send no credentials or cookies: no `HTTPBasicAuthHandler`, no cookie processor. Proxies from the environment are honoured, as is urllib's default.
2. **TLS**: an opener built with `HTTPSHandler(context=ssl.create_default_context())`. Certificates and host names are verified, and verification is never disabled.
3. **Redirects**: subclass `HTTPRedirectHandler` and override `redirect_request`. If the new URL's scheme (`urlsplit(newurl).scheme`) is not `http`/`https`, raise `FetchError(f"cannot fetch {url}: redirect to {newurl} refused (only http and https)")`. Otherwise defer to `super()`. urllib's built-in cap on the redirect count (10) stays.
4. **Total deadline (NFR-004)**: compute `deadline = time.monotonic() + FETCH_TIMEOUT_SECONDS` before opening.
   - Open with `timeout=FETCH_TIMEOUT_SECONDS`.
   - Read the body in chunks. Before each `read`, set the socket timeout to the remaining time through `response.fp.raw._sock.settimeout(...)`; if that private chain is fragile, use the `socket` from `response.fp` or read with `read1`. The aim is that no single blocking call waits past the deadline.
   - If the remaining time is ≤ 0, or a `TimeoutError`/`socket.timeout` occurs, raise `FetchError(f"cannot fetch {url}: timed out after 10 s")`.
   - Implement and test this carefully: the `trickle` route sends one byte per second forever.
5. **Status**: urllib raises `HTTPError` for non-2xx. Map it to `FetchError(f"cannot fetch {url}: HTTP {code} {reason}")`. A 2xx other than 200 (e.g. 204 with an empty body) is success. 3xx responses are handled by the redirect handler; a 3xx without a `Location` header surfaces as `HTTPError` and is a failure.
6. **Other errors**:
   - `URLError` (DNS, connection refused, TLS verification failure) → `FetchError(f"cannot fetch {url}: {reason}")`. Use `err.reason` and keep it short: `str(reason)`, first line only.
   - Any `OSError` → the same.
   - Never let a raw traceback escape. Any exception raised from inside `fetch` must be a `FetchError`.
7. **Decoding**: strict UTF-8 on the bytes, no newline translation. A BOM stays in the text, exactly as `loader.read_source` keeps it, because spans are indices into `SourceFile.text`. On failure: `FetchError(f"cannot fetch {url}: not valid UTF-8 at byte {err.start}")`. **Ignore** any `charset` in `Content-Type`: S-2 says the body must be UTF-8.
8. Module docstring: "the only network access in troupe (spec S-2, research R-2)". List the rules above and state that nothing is cached here (caching per command is the loader's `fetched` map, WP05).

### T003 — `tests/remote_server.py`

A small, typed, importable module, not a fixture file:

```python
@dataclass
class Route:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)   # e.g. {"Location": "..."} for redirects
    behaviour: Literal["normal", "hang", "trickle"] = "normal"

@dataclass(frozen=True)
class Request:
    method: str
    path: str      # path + query exactly as requested

class RemoteServer:
    base: str                                  # "http://127.0.0.1:<port>"
    def url(self, path: str) -> str: ...       # base + path ("/team.yaml")
    def serve(self, path: str, body: str | bytes, status: int = 200, **headers: str) -> str: ...  # returns url
    def route(self, path: str, route: Route) -> str: ...
    def requests(self) -> list[Request]: ...   # thread-safe copy of the log
    def clear_log(self) -> None: ...
    def close(self) -> None: ...
```

- Use `http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)` with `serve_forever` in a daemon thread. Set `daemon_threads = True`.
- The handler answers `GET`, `HEAD`, `POST`, `PUT`, `DELETE` and `PATCH`, and logs every request with its method. NFR-001 tests assert that only `GET` ever arrives. Matching is on the path **without** the query string; the log keeps the query.
- An unknown path returns 404.
- `hang`: sleep 30 s (interruptible by `close()` via a `threading.Event`) and then send nothing.
- `trickle`: send `200` with a large `Content-Length`, then one byte per second until closed.
- Silence the default stderr logging (`log_message` → no-op).
- `close()` shuts the server down and sets the stop event, so hanging handlers end promptly. Tests must not leave threads blocking pytest's exit.

### T004 — Fixtures in `tests/conftest.py`

1. `@pytest.fixture def remote() -> Iterator[RemoteServer]`: start, yield, close.
2. `@pytest.fixture def https_remote(tmp_path) -> Iterator[RemoteServer]` serves over TLS with a self-signed certificate:
   - Generate the key and certificate with `openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=127.0.0.1 -addext subjectAltName=IP:127.0.0.1 -keyout … -out …` via `subprocess.run(check=True)`.
   - Wrap the server socket with `ssl.SSLContext(PROTOCOL_TLS_SERVER).wrap_socket(..., server_side=True)`, and expose `base = "https://127.0.0.1:<port>"`.
   - If `shutil.which("openssl")` is `None`, call `pytest.skip("openssl is not installed; cannot create a self-signed certificate for the TLS verification test")`. The skip reason is visible in the output (TROUPE-006: no silent gaps).
3. `run_cli`: add `NO_PROXY` and `no_proxy` = `"127.0.0.1,localhost"` to the child environment, applied **before** the caller's `env` so a test can still override it. Explain why in a comment: the child must reach the test server even when the developer's shell sets an HTTP proxy.
4. Update the module docstring (helpers list).

### T005 — Unit tests `tests/unit/test_remote_fetch.py`

Call `fetch` in-process against `remote` and `https_remote`. Set `NO_PROXY` for the test process with `monkeypatch.setenv`. Suggested tests (names state what they prove):
- `test_fetch_returns_the_body_exactly_including_crlf_and_bom`
- `test_fetch_accepts_any_2xx_status` (200, 203, 204 empty body → `""`)
- `test_fetch_of_404_names_the_url_and_status` (assert the message equals `cannot fetch <url>: HTTP 404 Not Found`)
- `test_fetch_of_500_is_a_fetch_error`
- `test_fetch_follows_an_http_redirect`
- `test_fetch_refuses_a_redirect_to_another_scheme` (`Location: file:///etc/passwd`; also `ftp://…`)
- `test_fetch_of_a_non_utf8_body_names_the_byte`
- `test_fetch_ignores_a_declared_charset_and_requires_utf8` (latin-1 bytes with `Content-Type: text/plain; charset=latin-1` → error)
- `test_fetch_of_an_unanswered_request_fails_within_the_deadline` (the `hang` route; assert it took ≥ 10 s and < 12 s with `time.monotonic()`)
- `test_fetch_of_a_trickling_body_fails_within_the_deadline` (the `trickle` route; same bounds)
- `test_fetch_of_a_closed_port_is_a_fetch_error_naming_the_url` (bind a socket, close it, use its port)
- `test_fetch_refuses_an_unverified_certificate` (`https_remote`; skipped with a reason if `openssl` is missing)
- `test_fetch_sends_only_get` (request log)
- `test_fetch_errors_are_load_errors_with_exit_4` (`FetchError.exit_code == 4`, `issubclass(FetchError, LoadError)`)
- `test_url_prints_as_its_text_and_compares_by_text`

Only the two deadline tests are slow (about 10 s each). Do not add a configurable timeout to make them faster (research R-2).

## Definition of Done

- The new modules are fully typed: `uv run mypy --strict` passes, and so do the other three gates. Paste their output in the Activity Log.
- No existing test changes behaviour. Only `conftest.py`'s `run_cli` environment changes.
- `remote.py` is the only module that imports `urllib.request`, `ssl` or `socket` (excluding tests).

## Risks

- **Deadline enforcement through urllib internals.** Mitigation: keep the deadline logic in one helper with a comment, and prove it with the hang and trickle tests.
- **Leaking server threads** making pytest hang. Mitigation: daemon threads, a stop event and `close()` in the fixture `finally`.
- **Proxy in the environment** sending test requests to the proxy. Mitigation: `NO_PROXY` set in `run_cli` and with `monkeypatch` in unit tests.

## Reviewer guidance

- Every failure path ends in `FetchError` with a message starting `cannot fetch <url>: `.
- No TLS weakening anywhere, including tests: the TLS test expects failure.
- The server logs every method, and the log is thread-safe.

## Activity Log

- 2026-10-07T18:00:00Z – system – Prompt generated via /spec-kitty.tasks
