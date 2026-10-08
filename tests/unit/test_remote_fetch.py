"""``remote.fetch`` against a real local HTTP(S) server (spec S-2, NFR-004, research R-2)."""

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from conftest import LOCAL_NO_PROXY
from remote_server import RemoteServer, Request, Route
from troupe.errors import FetchError, LoadError
from troupe.location import Url
from troupe.remote import MAX_BODY_BYTES, fetch


@pytest.fixture(autouse=True)
def _bypass_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test server is local; a proxy configured in the environment must not intercept it.
    monkeypatch.setenv("NO_PROXY", LOCAL_NO_PROXY)
    monkeypatch.setenv("no_proxy", LOCAL_NO_PROXY)


def fetch_error(url: str) -> FetchError:
    with pytest.raises(FetchError) as caught:
        fetch(Url(url))
    return caught.value


def test_fetch_returns_the_body_exactly_including_crlf_and_bom(remote: RemoteServer) -> None:
    body = "﻿a: 1\r\nb: é\r\n"
    url = remote.serve("/team.yaml", body)

    assert fetch(Url(url)) == body


@pytest.mark.parametrize(("status", "body"), [(200, "x: 1\n"), (203, "x: 2\n"), (204, "")])
def test_fetch_accepts_any_2xx_status(remote: RemoteServer, status: int, body: str) -> None:
    url = remote.serve("/doc.yaml", body, status=status)

    assert fetch(Url(url)) == body


def test_fetch_of_404_names_the_url_and_status(remote: RemoteServer) -> None:
    url = remote.url("/missing.yaml")

    err = fetch_error(url)

    assert err.message == f"cannot fetch {url}: HTTP 404 Not Found"
    assert (err.url, err.reason) == (url, "HTTP 404 Not Found")


def test_fetch_of_a_status_without_reason_phrase_has_no_trailing_space(
    remote: RemoteServer,
) -> None:
    url = remote.route("/bare.yaml", Route(status=404, reason=""))

    assert fetch_error(url).message == f"cannot fetch {url}: HTTP 404"


def test_fetch_of_500_is_a_fetch_error(remote: RemoteServer) -> None:
    url = remote.serve("/broken.yaml", "boom", status=500)

    assert fetch_error(url).message == f"cannot fetch {url}: HTTP 500 Internal Server Error"


def test_fetch_follows_an_http_redirect(remote: RemoteServer) -> None:
    target = remote.serve("/new.yaml", "moved: true\n")
    start = remote.serve("/old.yaml", "", status=301, Location=target)

    assert fetch(Url(start)) == "moved: true\n"
    assert [r.path for r in remote.requests()] == ["/old.yaml", "/new.yaml"]


@pytest.mark.parametrize("target", ["file:///etc/passwd", "ftp://127.0.0.1/team.yaml"])
def test_fetch_refuses_a_redirect_to_another_scheme(remote: RemoteServer, target: str) -> None:
    url = remote.serve("/redirect.yaml", "", status=302, Location=target)

    err = fetch_error(url)

    assert err.message == f"cannot fetch {url}: redirect to {target} refused (only http and https)"


def test_fetch_follows_an_http_redirect_to_https(
    remote: RemoteServer,
    https_remote: RemoteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Trust the fixture's self-signed certificate (same tmp_path) so only the redirect rule decides.
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "server.crt"))
    target = https_remote.serve("/team.yaml", "secure: true\n")
    start = remote.serve("/team.yaml", "", status=301, Location=target)

    assert fetch(Url(start)) == "secure: true\n"


def test_fetch_refuses_a_redirect_from_https_to_http(
    remote: RemoteServer,
    https_remote: RemoteServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "server.crt"))
    target = remote.serve("/team.yaml", "plain: true\n")
    start = https_remote.serve("/team.yaml", "", status=302, Location=target)

    err = fetch_error(start)

    assert err.message == (
        f"cannot fetch {start}: redirect to {target} refused (https may not redirect to http)"
    )
    assert remote.requests() == []  # the downgraded URL is never contacted


def test_fetch_follows_an_https_redirect_to_https(
    https_remote: RemoteServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "server.crt"))
    target = https_remote.serve("/new.yaml", "moved: true\n")
    start = https_remote.serve("/old.yaml", "", status=308, Location=target)

    assert fetch(Url(start)) == "moved: true\n"


def test_fetch_accepts_a_body_of_exactly_the_limit(remote: RemoteServer) -> None:
    url = remote.serve("/big.txt", b"x" * MAX_BODY_BYTES)

    assert len(fetch(Url(url))) == MAX_BODY_BYTES


def test_fetch_refuses_a_body_whose_declared_length_exceeds_the_limit(
    remote: RemoteServer,
) -> None:
    url = remote.serve("/huge.txt", b"x" * (MAX_BODY_BYTES + 1))

    assert fetch_error(url).message == (
        f"cannot fetch {url}: larger than 1 MiB, the limit for a remote include"
    )


def test_fetch_refuses_an_unsized_body_once_reading_passes_the_limit(
    remote: RemoteServer,
) -> None:
    url = remote.route("/stream.txt", Route(body=b"x" * (MAX_BODY_BYTES + 1), behaviour="unsized"))

    assert fetch_error(url).message == (
        f"cannot fetch {url}: larger than 1 MiB, the limit for a remote include"
    )


def test_fetch_reads_an_unsized_body_within_the_limit(remote: RemoteServer) -> None:
    url = remote.route("/small.txt", Route(body=b"a: 1\n", behaviour="unsized"))

    assert fetch(Url(url)) == "a: 1\n"


def test_fetch_of_a_redirect_without_location_is_a_fetch_error(remote: RemoteServer) -> None:
    url = remote.serve("/nowhere.yaml", "", status=302)

    assert fetch_error(url).message == f"cannot fetch {url}: HTTP 302 Found"


def test_fetch_of_a_non_utf8_body_names_the_byte(remote: RemoteServer) -> None:
    url = remote.serve("/bad.yaml", b"ok: 1\nname: \xff\n")

    assert fetch_error(url).message == f"cannot fetch {url}: not valid UTF-8 at byte 12"


def test_fetch_ignores_a_declared_charset_and_requires_utf8(remote: RemoteServer) -> None:
    url = remote.route(
        "/latin.txt",
        Route(
            body="café".encode("latin-1"), headers={"Content-Type": "text/plain; charset=latin-1"}
        ),
    )

    assert fetch_error(url).message == f"cannot fetch {url}: not valid UTF-8 at byte 3"


def test_fetch_of_an_unanswered_request_fails_within_the_deadline(remote: RemoteServer) -> None:
    url = remote.route("/hang.yaml", Route(behaviour="hang"))

    started = time.monotonic()
    err = fetch_error(url)
    elapsed = time.monotonic() - started

    assert err.message == f"cannot fetch {url}: timed out after 10 s"
    assert 10.0 <= elapsed < 12.0


def test_fetch_of_a_trickling_body_fails_within_the_deadline(remote: RemoteServer) -> None:
    url = remote.route("/trickle.yaml", Route(behaviour="trickle"))

    started = time.monotonic()
    err = fetch_error(url)
    elapsed = time.monotonic() - started

    assert err.message == f"cannot fetch {url}: timed out after 10 s"
    assert 10.0 <= elapsed < 12.0


@pytest.fixture
def full_backlog() -> Iterator[tuple[str, int]]:
    """A listener whose accept queue is full, so further connects hang (SYNs are dropped)."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(0)
    address = listener.getsockname()
    fillers: list[socket.socket] = []
    try:
        while True:
            filler = socket.socket()
            fillers.append(filler)
            filler.settimeout(0.3)
            try:
                filler.connect(address)
            except TimeoutError:
                break  # the queue is full
        yield address
    finally:
        for filler in fillers:
            filler.close()
        listener.close()


def test_fetch_bounds_all_connect_attempts_by_one_deadline(
    monkeypatch: pytest.MonkeyPatch, full_backlog: tuple[str, int]
) -> None:
    # Two addresses that both swallow the connect: the deadline is shared, not per address.
    host, port = full_backlog
    resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))] * 2
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: resolved)
    url = f"http://127.0.0.1:{port}/team.yaml"

    started = time.monotonic()
    err = fetch_error(url)
    elapsed = time.monotonic() - started

    assert err.message == f"cannot fetch {url}: timed out after 10 s"
    assert 10.0 <= elapsed < 12.0


def test_fetch_bounds_a_hanging_dns_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def slow_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        release.wait(60.0)
        raise socket.gaierror("lookup released by the test")

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    url = "http://troupe.invalid/team.yaml"
    monkeypatch.setenv("NO_PROXY", "*")  # the lookup under test is the server's, not a proxy's
    monkeypatch.setenv("no_proxy", "*")

    started = time.monotonic()
    try:
        err = fetch_error(url)
    finally:
        release.set()
    elapsed = time.monotonic() - started

    assert err.message == f"cannot fetch {url}: timed out after 10 s"
    assert 10.0 <= elapsed < 12.0


def test_fetch_of_a_closed_port_is_a_fetch_error_naming_the_url() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/team.yaml"

    err = fetch_error(url)

    assert err.message.startswith(f"cannot fetch {url}: ")
    assert "refused" in err.reason.lower()


def test_fetch_refuses_an_unverified_certificate(https_remote: RemoteServer) -> None:
    url = https_remote.serve("/team.yaml", "x: 1\n")

    err = fetch_error(url)

    assert err.message.startswith(f"cannot fetch {url}: ")
    assert "CERTIFICATE_VERIFY_FAILED" in err.reason
    assert https_remote.requests() == []  # nothing was sent over the untrusted connection


def test_fetch_of_a_non_http_url_is_refused_without_reading_the_file() -> None:
    url = "file:///etc/hostname"

    assert fetch_error(url).message == f"cannot fetch {url}: unknown url type: file"


def test_fetch_sends_only_get(remote: RemoteServer) -> None:
    remote.serve("/team.yaml", "x: 1\n")
    url = remote.url("/team.yaml?v=1")

    fetch(Url(url))

    assert remote.requests() == [Request("GET", "/team.yaml?v=1")]


def test_fetch_errors_are_load_errors_with_exit_4() -> None:
    assert issubclass(FetchError, LoadError)
    assert FetchError.exit_code == 4
    assert FetchError("https://h/x.yaml", "HTTP 404 Not Found").message == (
        "cannot fetch https://h/x.yaml: HTTP 404 Not Found"
    )


def test_url_prints_as_its_text_and_compares_by_text() -> None:
    url = Url("https://Example.com/a/../b.yaml?q=1")

    assert str(url) == "https://Example.com/a/../b.yaml?q=1"
    assert f"{url}" == url.text
    assert url == Url("https://Example.com/a/../b.yaml?q=1")
    assert url != Url("https://example.com/a/../b.yaml?q=1")
    assert len({url, Url(url.text)}) == 1
