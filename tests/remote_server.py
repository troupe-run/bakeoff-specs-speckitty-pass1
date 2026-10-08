"""A real HTTP(S) server for remote-include tests, run in a thread of the test process (R-13).

Tests register routes (path -> status, body, headers, behaviour), point troupe at ``url(path)``
and read the request log to assert what was fetched, how often and with which method. The server
listens on ``127.0.0.1`` only, so no test touches the outside network (C-006); the CLI subprocess
started by ``run_cli`` reaches it the same way.

Behaviours beyond a normal response:

- ``hang``: accept the request and send nothing for 30 s (ended early by ``close()``).
- ``trickle``: send ``200`` with a large ``Content-Length``, then one body byte per second until
  the client goes away or the server is closed.
- ``unsized``: send the body without ``Content-Length`` and end it by closing the connection
  (HTTP/1.0), so the client can only learn the size by reading (spec S-14).
"""

import ssl
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final, Literal, cast
from urllib.parse import urlsplit

HANG_SECONDS: Final = 30.0
TRICKLE_LENGTH: Final = 1_000_000


@dataclass
class Route:
    """How the server answers one path."""

    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)  # e.g. {"Location": "..."}
    behaviour: Literal["normal", "hang", "trickle", "unsized"] = "normal"
    reason: str | None = None  # status-line reason phrase; None = the standard one, "" = none


@dataclass(frozen=True)
class Request:
    """One logged request."""

    method: str
    path: str  # path + query exactly as requested


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes: dict[str, Route] = {}
        self.log: list[Request] = []
        self.lock = threading.Lock()
        self.stop = threading.Event()


class _Handler(BaseHTTPRequestHandler):
    def _answer(self) -> None:
        server = cast(_Server, self.server)
        with server.lock:
            server.log.append(Request(self.command, self.path))
            route = server.routes.get(urlsplit(self.path).path)
        if route is None:
            route = Route(status=404, body=b"not found\n")
        try:
            if route.behaviour == "hang":
                server.stop.wait(HANG_SECONDS)
            elif route.behaviour == "trickle":
                self._trickle(server.stop)
            else:
                self._normal(route)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up, which is what deadline tests provoke

    def _normal(self, route: Route) -> None:
        self.send_response(route.status, route.reason)
        for name, value in route.headers.items():
            self.send_header(name, value)
        has_body = route.status not in (204, 304) and self.command != "HEAD"
        if route.status not in (204, 304) and route.behaviour != "unsized":
            self.send_header("Content-Length", str(len(route.body)))
        self.end_headers()
        if has_body:
            self.wfile.write(route.body)
        if route.behaviour == "unsized":
            self.close_connection = True

    def _trickle(self, stop: threading.Event) -> None:
        self.send_response(200)
        self.send_header("Content-Length", str(TRICKLE_LENGTH))
        self.end_headers()
        self.wfile.flush()
        while not stop.wait(1.0):
            self.wfile.write(b"x")
            self.wfile.flush()

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = _answer

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep pytest output clean


class RemoteServer:
    """A running server on ``127.0.0.1``; ``tls`` makes it serve https with that context."""

    def __init__(self, tls: ssl.SSLContext | None = None) -> None:
        self._server = _Server()
        if tls is not None:
            # The handshake then runs in the accept loop, before a handler thread starts: a
            # client that connects but never handshakes blocks this server. Acceptable for
            # tests, whose clients are troupe itself; move the handshake into the handler if
            # a test ever needs a stalled TLS client.
            self._server.socket = tls.wrap_socket(self._server.socket, server_side=True)
        port = self._server.server_address[1]
        self.base = f"{'https' if tls else 'http'}://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def url(self, path: str) -> str:
        """Return the absolute URL of ``path`` (which starts with ``/``)."""
        return self.base + path

    def serve(self, path: str, body: str | bytes, status: int = 200, **headers: str) -> str:
        """Answer ``path`` with ``body`` (``str`` is UTF-8 encoded verbatim); return its URL."""
        data = body.encode("utf-8") if isinstance(body, str) else body
        return self.route(path, Route(status=status, body=data, headers=dict(headers)))

    def route(self, path: str, route: Route) -> str:
        """Answer ``path`` (matched without its query) as ``route`` says; return its URL."""
        with self._server.lock:
            self._server.routes[path] = route
        return self.url(path)

    def requests(self) -> list[Request]:
        """Return a copy of the request log, oldest first."""
        with self._server.lock:
            return list(self._server.log)

    def clear_log(self) -> None:
        """Forget every request logged so far."""
        with self._server.lock:
            self._server.log.clear()

    def close(self) -> None:
        """Stop serving, end hanging and trickling handlers, and release the port."""
        self._server.stop.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(5.0)
