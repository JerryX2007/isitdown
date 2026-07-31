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
    ],
)
def test_normalize_website(raw_website, expected):
    assert normalize_website(raw_website) == expected


@pytest.mark.parametrize(
    "raw_website",
    [
        "",
        "ftp://example.com",
        "localhost",
        "https://example.com:8080",
    ],
)
def test_normalize_website_rejects_invalid_addresses(raw_website):
    with pytest.raises(HTTPException) as error:
        normalize_website(raw_website)

    assert error.value.status_code == 400
