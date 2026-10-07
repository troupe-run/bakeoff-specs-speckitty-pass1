---
affected_files: []
cycle_number: 1
mission_slug: troupe-config-remote-includes-01M4BMJ5
reproduction_command:
reviewed_at: '2026-10-07T18:36:27Z'
reviewer_agent: user
wp_id: WP01
---

# WP01 review feedback (cycle 1)

**Verdict: changes requested**

1. **`src/troupe/remote.py:194-208` and `:222-241`: the 10 s total deadline does not cover connecting (NFR-004 violated).**
   - **Problem:** `_connection` reads `self._deadline.remaining()` once, when it creates the connection object. `socket.create_connection` then gives **each** address from `getaddrinfo` that full timeout. With two addresses that drop packets, the fetch took **20.0 s**; the reviewer reproduced this with a full-backlog listener and a patched `getaddrinfo` returning it twice. The TLS handshake in `HTTPSConnection.connect` also uses the stale timeout, not the remaining time. The `_Deadline` docstring claim "No blocking call can therefore wait past the deadline" is therefore false.
   - **Required:**
     - Re-arm the timeout with `deadline.remaining()` before **each** connect attempt. Use your own create-connection loop (`connection._create_connection`, or an overridden `connect`) that raises `TimeoutError` once time is up.
     - In HTTPS, call `self.sock.settimeout(deadline.remaining())` after the TCP connect and before `wrap_socket`.
     - Do the same before any tunnel/proxy `CONNECT` step you touch.
     - Add a deterministic offline test in the style of the hang and trickle tests (`10 <= elapsed < 12`): a full-backlog listener plus a patched `getaddrinfo` returning its address twice.
     - Correct the `_Deadline` docstring.

2. **The DNS lookup is not bounded (also NFR-004, raised to required by the orchestrator).**
   - **Problem:** `getaddrinfo` takes no timeout.
   - **Required:**
     - Run the lookup in a daemon thread and wait at most `deadline.remaining()`. On timeout, raise the same `timed out after 10 s` FetchError.
     - Test it by patching `socket.getaddrinfo` with a slow function, using an `Event` the test releases afterwards.
     - State in the module docstring that the deadline covers DNS, connect, TLS, headers and body.

3. **Trailing space in the HTTP error message (small, required).**
   - **Problem:** `HTTP {code} {reason}` ends in a space when the server sends no reason phrase.
   - **Required:** use `.rstrip()`, and add a test (the test server can send a status line with no reason).

Non-blocking:
- `RemoteServer(tls=…)` performs the TLS handshake in the accept loop. A client that never handshakes would block the server. This is acceptable for now; leave a comment in the code.

Everything else in T001–T005 was verified as specified. Keep it unchanged.
