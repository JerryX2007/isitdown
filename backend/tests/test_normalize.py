import pytest
from fastapi import HTTPException

from routes.monitors import normalize_website


@pytest.mark.parametrize(
    ("raw_website", "expected"),
    [
        (
            "example.com",
            {
                "target": "example.com",
                "scheme": "https",
                "url": "https://example.com",
            },
        ),
        (
            " HTTP://Example.COM/somewhere ",
            {
                "target": "example.com",
                "scheme": "http",
                "url": "http://example.com",
            },
        ),
        (
            "https://sub.example.com.",
            {
                "target": "sub.example.com",
                "scheme": "https",
                "url": "https://sub.example.com",
            },
        ),
        (
            "https://BÜCHER.de/catalogue?q=one#results",
            {
                "target": "xn--bcher-kva.de",
                "scheme": "https",
                "url": "https://xn--bcher-kva.de",
            },
        ),
        (
            "http://8.8.8.8/dns-query",
            {
                "target": "8.8.8.8",
                "scheme": "http",
                "url": "http://8.8.8.8",
            },
        ),
    ],
)
def test_normalize_website(raw_website, expected):
    assert normalize_website(raw_website) == expected


@pytest.mark.parametrize(
    ("raw_website", "expected_detail"),
    [
        ("", "Enter a website to check."),
        (
            "ftp://example.com",
            "Only HTTP and HTTPS websites can be checked.",
        ),
        ("localhost", "Enter a public website address."),
        ("printer.local", "Enter a public website address."),
        ("intranet", "Enter a public website address."),
        (
            "https://example.com:8080",
            "Enter a website without login details or a custom port.",
        ),
        (
            "https://user:password@example.com",
            "Enter a website without login details or a custom port.",
        ),
        (
            "https://example.com:notaport",
            "Enter a valid website, such as example.com.",
        ),
        (
            "https://[::1",
            "Enter a valid website, such as example.com.",
        ),
        (
            "https:///missing-host",
            "Enter a valid website, such as example.com.",
        ),
        (
            "https://%31%32%37.0.0.1",
            "Enter a valid website, such as example.com.",
        ),
        (
            "https://example..com",
            "Invalid website address.",
        ),
        (
            "https://-example.com",
            "Enter a valid website, such as example.com.",
        ),
        (
            "https://example-.com",
            "Enter a valid website, such as example.com.",
        ),
        ("\ud800.com", "Invalid website address."),
    ],
)
def test_normalize_website_rejects_invalid_addresses(
    raw_website,
    expected_detail,
):
    with pytest.raises(HTTPException) as error:
        normalize_website(raw_website)

    assert error.value.status_code == 400
    assert error.value.detail == expected_detail
