"""Fetching remote includes: the only network access in troupe (spec S-2, research R-2).

``fetch(url)`` performs one HTTP(S) ``GET`` with the standard library and returns the body as
text. The rules, each enforced here and nowhere else:

- **Request**: a plain ``GET``. No credentials and no cookies are ever sent (the opener has no
  auth handler and no cookie processor). Proxies from the environment are honoured, as urllib
  does by default.
- **TLS**: ``ssl.create_default_context()``, so certificates and host names are verified.
  Verification is never disabled.
- **Redirects**: followed only to ``http``/``https`` targets; any other scheme is refused, and
  so is a redirect from ``https`` to ``http`` (spec S-15). urllib's cap on the number of
  redirects stays in force.
- **Deadline**: one total deadline of ``FETCH_TIMEOUT_SECONDS`` for the whole fetch, redirects
  and proxies included (NFR-004): it covers the DNS lookup, every connect attempt, the TLS
  handshake, sending the request, and reading the status line, headers and body. See
  ``_Deadline`` for how each step is bounded.
- **Status**: any 2xx is success (a 204 yields ``""``); everything else is a failure.
- **Size**: at most ``MAX_BODY_BYTES`` (1 MiB) per body, checked against ``Content-Length``
  and again while reading (spec S-14).
- **Body**: strict UTF-8, no newline translation, and a leading BOM stays in the text, exactly as
  ``loader.read_source`` treats local files. A ``charset`` in ``Content-Type`` is ignored: S-2
  says the body must be UTF-8.

Every failure raises ``FetchError`` (exit 4) whose message is ``cannot fetch <url>: <reason>``;
no other exception escapes ``fetch``. Nothing is cached here: fetching each URL once per
command is the loader's job.
"""

import http.client
import io
import socket
import ssl
import threading
import time
import urllib.request
from collections.abc import Buffer, Sequence
from typing import IO, Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit

from troupe.errors import FetchError
from troupe.location import Url

FETCH_TIMEOUT_SECONDS: Final = 10.0
_CHUNK: Final = 65536
_ALLOWED_SCHEMES: Final = frozenset({"http", "https"})
_TIMED_OUT: Final = f"timed out after {FETCH_TIMEOUT_SECONDS:g} s"
# Largest body accepted for one remote include (spec S-14). Configurations are small (under
# 1,000 leaves in under 50 files), so 1 MiB is far above any real include; anything larger is
# refused as a failed fetch rather than read into memory.
MAX_BODY_BYTES: Final = 1024 * 1024
_TOO_LARGE: Final = "larger than 1 MiB, the limit for a remote include"


def fetch(url: Url) -> str:
    """Fetch ``url`` with a ``GET`` and return its body as text.

    Raises:
        FetchError: For a network or TLS error, a timeout, a non-2xx status, a redirect to a
            scheme other than http/https or from https to http, a body larger than
            ``MAX_BODY_BYTES``, or a body that is not valid UTF-8. The message is
            ``cannot fetch <url>: <reason>``.
    """
    deadline = _Deadline(FETCH_TIMEOUT_SECONDS)
    try:
        data = _get(url, deadline)
    except FetchError:
        raise
    except HTTPError as err:
        err.close()
        raise FetchError(str(url), f"HTTP {err.code} {err.reason}".rstrip()) from err
    except TimeoutError as err:
        raise FetchError(str(url), _TIMED_OUT) from err
    except URLError as err:
        if isinstance(err.reason, TimeoutError):
            raise FetchError(str(url), _TIMED_OUT) from err
        raise FetchError(str(url), _first_line(err.reason)) from err
    except Exception as err:
        # OSError, http.client.HTTPException (bad status line, incomplete read, ...),
        # ValueError (malformed URL) and anything unforeseen: never let a traceback escape.
        raise FetchError(str(url), _first_line(err)) from err
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise FetchError(str(url), f"not valid UTF-8 at byte {err.start}") from err


def _get(url: Url, deadline: "_Deadline") -> bytes:
    request = urllib.request.Request(url.text, method="GET")
    opener = _opener(url, deadline)
    with opener.open(request, timeout=deadline.remaining()) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None and declared.strip().isdigit() and int(declared) > MAX_BODY_BYTES:
            raise FetchError(url.text, _TOO_LARGE)
        chunks: list[bytes] = []
        size = 0
        # The declared length is never trusted: the limit holds while reading (spec S-14).
        while chunk := response.read(_CHUNK):
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise FetchError(url.text, _TOO_LARGE)
            chunks.append(chunk)
    return b"".join(chunks)


def _first_line(reason: object) -> str:
    """Return a short form of an error reason: its first line, or its type if it has no text."""
    lines = str(reason).strip().splitlines()
    return lines[0] if lines else type(reason).__name__


class _Deadline:
    """The total time budget of one fetch (NFR-004), enforced at every blocking call.

    A socket timeout alone bounds each single call, not the fetch: a server sending one byte
    per second would never trip it, and ``socket.create_connection`` gives every address the
    full timeout. So each blocking step first takes the *remaining* time as its limit:

    - the DNS lookup runs in a thread that is waited for at most that long (``_resolve``);
    - each connect attempt, per resolved address (``_connect``);
    - each send, including a proxy ``CONNECT`` (``_Connection.send``);
    - the TLS handshake (``_TLSConnection.connect``);
    - each read of the status line, headers and body, the proxy's reply included
      (``_DeadlineReader``).

    Once the deadline has passed, ``remaining`` raises ``TimeoutError`` before the next step
    starts, so the fetch as a whole ends within the deadline plus scheduling slack.
    """

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        """Return the seconds left; raise ``TimeoutError`` if there are none."""
        left = self._end - time.monotonic()
        if left <= 0:
            raise TimeoutError("fetch deadline passed")
        return left


class _DeadlineReader(io.RawIOBase):
    """Raw reads from a socket, each limited to the time left before the deadline."""

    def __init__(self, sock: socket.socket, deadline: _Deadline) -> None:
        super().__init__()
        self._sock = sock
        self._deadline = deadline
        # A ``makefile`` reference, like ``HTTPResponse``'s own: the socket stays open after
        # urllib closes the connection object, until this reader is closed.
        self._raw = sock.makefile("rb", buffering=0)

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int | None:
        self._sock.settimeout(self._deadline.remaining())
        return self._raw.readinto(buffer)

    def close(self) -> None:
        self._raw.close()
        super().close()


def _response_class(deadline: _Deadline) -> type[http.client.HTTPResponse]:
    class DeadlineResponse(http.client.HTTPResponse):
        """An ``HTTPResponse`` that reads the status, headers and body through the deadline."""

        def __init__(
            self,
            sock: socket.socket,
            debuglevel: int = 0,
            method: str | None = None,
            url: str | None = None,
        ) -> None:
            super().__init__(sock, debuglevel, method, url)
            self.fp.close()  # drop the plain reader made by ``HTTPResponse``
            self.fp = io.BufferedReader(_DeadlineReader(sock, deadline))

    return DeadlineResponse


class _Connection(http.client.HTTPConnection):
    """An http connection whose every blocking step is bounded by the deadline.

    ``connect`` resolves the host and connects through ``_open_socket`` (DNS and each connect
    attempt bounded), every ``send`` -- the request and a proxy's ``CONNECT`` alike -- first
    re-arms the socket timeout, and responses read through ``_DeadlineReader``.
    """

    def __init__(
        self,
        host: str,
        port: int | None,
        deadline: _Deadline,
        source_address: tuple[str, int] | None,
        blocksize: int,
    ) -> None:
        super().__init__(host, port, deadline.remaining(), source_address, blocksize)
        self._arm(deadline)

    def _arm(self, deadline: _Deadline) -> None:
        self._deadline = deadline
        # ``HTTPConnection.connect`` opens its socket through this instance attribute.
        self._create_connection = self._open_socket
        self.response_class = _response_class(deadline)

    def _open_socket(
        self,
        address: tuple[str, int],
        timeout: float,  # ignored: the deadline decides
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        return _connect(address[0], address[1], source_address, self._deadline)

    def send(self, data: Any) -> None:
        if self.sock is not None:
            self.sock.settimeout(self._deadline.remaining())
        super().send(data)


class _TLSConnection(_Connection, http.client.HTTPSConnection):
    """An https connection: ``_Connection``'s bounds, plus a TLS handshake bounded likewise."""

    _tunnel_host: str | None  # set by ``HTTPConnection.set_tunnel`` (https through a proxy)

    def __init__(
        self,
        host: str,
        port: int | None,
        deadline: _Deadline,
        source_address: tuple[str, int] | None,
        blocksize: int,
        context: ssl.SSLContext,
    ) -> None:
        http.client.HTTPSConnection.__init__(
            self,
            host,
            port,
            timeout=deadline.remaining(),
            source_address=source_address,
            context=context,
            blocksize=blocksize,
        )
        self._arm(deadline)
        self._tls = context

    def connect(self) -> None:
        # What ``HTTPSConnection.connect`` does, with the handshake limited to the time left.
        http.client.HTTPConnection.connect(self)  # TCP, and the proxy CONNECT if any
        assert self.sock is not None
        self.sock.settimeout(self._deadline.remaining())
        self.sock = self._tls.wrap_socket(self.sock, server_hostname=self._tunnel_host or self.host)


def _connect(
    host: str, port: int, source_address: tuple[str, int] | None, deadline: _Deadline
) -> socket.socket:
    """Connect to ``host``, like ``socket.create_connection`` but bounded by the deadline.

    Each address gets only the time left, re-armed per attempt; once none is left the next
    attempt raises ``TimeoutError`` instead of starting.
    """
    errors: list[OSError] = []
    for family, kind, proto, _, sockaddr in _resolve(host, port, deadline):
        timeout = deadline.remaining()
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            if source_address is not None:
                sock.bind(source_address)
            sock.connect(sockaddr)
        except OSError as err:
            sock.close()
            errors.append(err)
            continue
        return sock
    deadline.remaining()  # the last attempt used up the time: report the timeout
    if not errors:
        raise OSError("getaddrinfo returns an empty list")
    raise errors[0]


_AddrInfo = Sequence[
    tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
    ]
]


def _resolve(host: str, port: int, deadline: _Deadline) -> _AddrInfo:
    """Look ``host`` up, waiting at most the time left.

    ``getaddrinfo`` takes no timeout, so it runs in a daemon thread. A lookup still hanging at
    the deadline is abandoned (its thread ends whenever the resolver returns) and
    ``TimeoutError`` is raised.
    """
    found: list[_AddrInfo] = []
    failed: list[BaseException] = []

    def lookup() -> None:
        try:
            found.append(socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM))
        except BaseException as err:  # handed to the caller's thread below
            failed.append(err)

    thread = threading.Thread(target=lookup, name=f"troupe-dns-{host}", daemon=True)
    thread.start()
    thread.join(deadline.remaining())
    if thread.is_alive():
        raise TimeoutError(f"DNS lookup of {host} did not finish")
    if failed:
        raise failed[0]
    return found[0]


class _HTTPHandler(urllib.request.HTTPHandler):
    """Open http connections whose every blocking call is bounded by the deadline."""

    def __init__(self, deadline: _Deadline) -> None:
        super().__init__()
        self._deadline = deadline

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._connection, req)

    def _connection(
        self,
        host: str,
        /,
        *,
        port: int | None = None,
        timeout: float = FETCH_TIMEOUT_SECONDS,  # ignored: the deadline decides
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
    ) -> http.client.HTTPConnection:
        return _Connection(host, port, self._deadline, source_address, blocksize)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    """Open https connections that verify certificates and host names, within the deadline."""

    def __init__(self, deadline: _Deadline) -> None:
        self._verified = ssl.create_default_context()
        super().__init__(context=self._verified)
        self._deadline = deadline

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(self._connection, req)

    def _connection(
        self,
        host: str,
        /,
        *,
        port: int | None = None,
        timeout: float = FETCH_TIMEOUT_SECONDS,  # ignored: the deadline decides
        source_address: tuple[str, int] | None = None,
        blocksize: int = 8192,
    ) -> http.client.HTTPConnection:
        return _TLSConnection(host, port, self._deadline, source_address, blocksize, self._verified)


class _RedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to http/https; refuse every other scheme with a ``FetchError``.

    A redirect from https to http is refused too (spec S-15): the owner asked for an encrypted
    source, and following the downgrade would silently drop that. http to https and
    same-scheme redirects are followed. Every hop is checked, so https -> http -> http is
    refused at its first hop.

    The check sits in ``http_error_30x`` rather than ``redirect_request`` because urllib
    rejects ``file:`` and similar targets before ``redirect_request`` is called, with an
    ``HTTPError`` that would read like a status failure; ``ftp:`` it would even follow.
    """

    def __init__(self, url: Url) -> None:
        super().__init__()
        self._url = url

    def http_error_302(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
    ) -> Any:
        target = headers.get("location") or headers.get("uri")
        if target is not None:
            newurl = urljoin(req.full_url, target)
            scheme = urlsplit(newurl).scheme
            if scheme not in _ALLOWED_SCHEMES:
                fp.close()
                raise FetchError(
                    str(self._url), f"redirect to {newurl} refused (only http and https)"
                )
            if scheme == "http" and urlsplit(req.full_url).scheme == "https":
                fp.close()
                raise FetchError(
                    str(self._url), f"redirect to {newurl} refused (https may not redirect to http)"
                )
        return super().http_error_302(req, fp, code, msg, headers)

    # The base class binds these aliases to its own ``http_error_302``; rebind them to ours.
    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _opener(url: Url, deadline: _Deadline) -> urllib.request.OpenerDirector:
    """Build an opener with exactly the handlers S-2 needs: no auth, cookies, ftp or file."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        _HTTPHandler(deadline),
        _HTTPSHandler(deadline),
        urllib.request.HTTPDefaultErrorHandler(),
        _RedirectHandler(url),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener
