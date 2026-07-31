import socket

import pytest
from fastapi import HTTPException

from routes import monitors


def resolved_addresses(*addresses):
    return [
        (
            socket.AF_INET6 if ":" in address else socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            (address, 443),
        )
        for address in addresses
    ]


def test_get_public_addresses_returns_unique_global_addresses(monkeypatch):
    monkeypatch.setattr(
        monitors.socket,
        "getaddrinfo",
        lambda *args, **kwargs: resolved_addresses(
            "93.184.216.34",
            "2606:2800:220:1:248:1893:25c8:1946",
            "93.184.216.34",
        ),
    )

    addresses = monitors.get_public_addresses("example.com")

    assert set(addresses) == {
        "93.184.216.34",
        "2606:2800:220:1:248:1893:25c8:1946",
    }


def test_get_public_addresses_returns_empty_list_for_dns_failure(monkeypatch):
    def fail_dns_lookup(*args, **kwargs):
        raise socket.gaierror

    monkeypatch.setattr(monitors.socket, "getaddrinfo", fail_dns_lookup)

    assert monitors.get_public_addresses("missing.example") == []


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",
        "127.0.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "192.0.2.10",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "2001:db8::1",
        "ff02::1",
    ],
)
def test_get_public_addresses_rejects_non_global_or_multicast_results(
    address,
    monkeypatch,
):
    monkeypatch.setattr(
        monitors.socket,
        "getaddrinfo",
        lambda *args, **kwargs: resolved_addresses(address),
    )

    with pytest.raises(HTTPException) as error:
        monitors.get_public_addresses("unsafe.example")

    assert error.value.status_code == 400
    assert error.value.detail == "Private or local network addresses cannot be checked."


def test_get_public_addresses_rejects_mixed_public_and_private_dns(monkeypatch):
    monkeypatch.setattr(
        monitors.socket,
        "getaddrinfo",
        lambda *args, **kwargs: resolved_addresses(
            "93.184.216.34",
            "10.0.0.8",
        ),
    )

    with pytest.raises(HTTPException):
        monitors.get_public_addresses("mixed.example")


def test_check_target_stops_before_http_request_for_private_dns(
    monkeypatch,
):
    monkeypatch.setattr(
        monitors.socket,
        "getaddrinfo",
        lambda *args, **kwargs: resolved_addresses("169.254.169.254"),
    )

    def fail_if_http_client_is_created(**kwargs):
        raise AssertionError("HTTP client must not receive a private target")

    monkeypatch.setattr(monitors.httpx, "Client", fail_if_http_client_is_created)

    with pytest.raises(HTTPException) as error:
        monitors.check_target("metadata.example", timeout=5)

    assert error.value.status_code == 400


def test_check_target_disables_redirect_following(monkeypatch):
    class RedirectResponse:
        status_code = 302

    class RedirectClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def head(self, url):
            return RedirectResponse()

    client_options = {}

    def create_client(**kwargs):
        client_options.update(kwargs)
        return RedirectClient()

    monkeypatch.setattr(
        monitors,
        "get_public_addresses",
        lambda target: ["93.184.216.34"],
    )
    monkeypatch.setattr(monitors.httpx, "Client", create_client)

    result = monitors.check_target("example.com", timeout=5)

    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert result["status"] == "up"
    assert result["status_code"] == 302
