import socket
from hashlib import sha256
from datetime import datetime, timedelta, timezone

import pytest

from routes import monitors

from sqlalchemy import func, select
from database_models import CheckHistory, OutageReportRecord


def test_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_endpoint_records_result(
    client,
    monkeypatch,
    db_session,
):
    fake_result = {
        "target": "example.com",
        "status": "up",
        "latency": 42.5,
        "status_code": 200,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": None,
    }

    monkeypatch.setattr(
        monitors,
        "check_target",
        lambda website, timeout: fake_result,
    )

    response = client.post(
        "/api/check",
        json={"website": "example.com", "timeout": 5},
    )

    assert response.status_code == 200
    assert response.json() == fake_result

    saved_check = db_session.scalar(select(CheckHistory))

    assert saved_check is not None
    assert {
        "target": saved_check.target,
        "status": saved_check.status,
        "latency": saved_check.latency,
        "status_code": saved_check.status_code,
        "checked_at": (
            monitors.as_utc(saved_check.checked_at)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "error": saved_check.error,
    } == fake_result


def test_check_endpoint_uses_default_timeout(client, monkeypatch):
    captured_request = {}
    fake_result = {
        "target": "example.com",
        "status": "up",
        "latency": 12.5,
        "status_code": 200,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": None,
    }

    def fake_check_target(website, timeout):
        captured_request.update({"website": website, "timeout": timeout})
        return fake_result

    monkeypatch.setattr(monitors, "check_target", fake_check_target)

    response = client.post(
        "/api/check",
        json={"website": "example.com"},
    )

    assert response.status_code == 200
    assert captured_request == {"website": "example.com", "timeout": 7.0}


def test_check_endpoint_returns_down_result_with_http_200(client, monkeypatch):
    down_result = {
        "target": "missing.example",
        "status": "down",
        "latency": None,
        "status_code": None,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": "DNS lookup failed.",
    }
    monkeypatch.setattr(
        monitors,
        "check_target",
        lambda website, timeout: down_result,
    )

    response = client.post(
        "/api/check",
        json={"website": "missing.example"},
    )

    assert response.status_code == 200
    assert response.json() == down_result


@pytest.mark.parametrize("timeout", [0, -1, 15.01, "fast"])
def test_check_endpoint_rejects_invalid_timeout(client, timeout):
    response = client.post(
        "/api/check",
        json={"website": "example.com", "timeout": timeout},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "timeout"]


def test_check_endpoint_rejects_missing_website(client):
    response = client.post("/api/check", json={})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "website"]
    assert response.json()["detail"][0]["type"] == "missing"


@pytest.mark.parametrize(
    ("website", "expected_detail"),
    [
        ("   ", "Enter a website to check."),
        (
            "https://example.com:notaport",
            "Enter a valid website, such as example.com.",
        ),
    ],
)
def test_check_endpoint_returns_400_for_invalid_website(
    client,
    website,
    expected_detail,
    db_session,
):
    response = client.post(
        "/api/check",
        json={"website": website},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": expected_detail}

    saved_checks = db_session.scalar(
        select(func.count()).select_from(CheckHistory)
    )
    assert saved_checks == 0


def test_check_endpoint_returns_400_for_private_dns(
    client,
    monkeypatch,
    db_session,
):
    monkeypatch.setattr(
        monitors.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("169.254.169.254", 443),
            )
        ],
    )

    response = client.post(
        "/api/check",
        json={"website": "metadata.example"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Private or local network addresses cannot be checked."
    }

    saved_checks = db_session.scalar(
        select(func.count()).select_from(CheckHistory)
    )
    assert saved_checks == 0
    assert saved_checks == 0


def test_report_outage_accepts_and_hashes_reporter_id(
    client,
    monkeypatch,
    db_session,
):
    fixed_now = datetime(
        2026,
        7,
        31,
        12,
        0,
        tzinfo=timezone.utc,
    )

    monkeypatch.setattr(monitors, "utc_now", lambda: fixed_now)

    response = client.post(
        "/api/status/example.com/report",
        json={"reporter_id": "browser-identifier"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "accepted": True,
        "created_at": "2026-07-31T12:00:00Z",
    }

    saved_report = db_session.scalar(select(OutageReportRecord))

    assert saved_report is not None
    assert saved_report.target == "example.com"
    assert saved_report.reporter_hash == sha256(
        b"example.com:browser-identifier"
    ).hexdigest()
    assert monitors.as_utc(saved_report.created_at) == fixed_now


def test_report_outage_rejects_duplicate_recent_report(client):
    payload = {"reporter_id": "browser-identifier"}

    first_response = client.post(
        "/api/status/example.com/report",
        json=payload,
    )
    duplicate_response = client.post(
        "/api/status/example.com/report",
        json=payload,
    )

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "detail": "You already reported an issue with this website recently."
    }


def test_history_endpoint_returns_empty_24_hour_timeline(client):
    response = client.get("/api/status/example.com/history")

    assert response.status_code == 200
    body = response.json()
    assert body["target"] == "example.com"
    assert body["range"] == "24h"
    assert len(body["points"]) == 24
    assert all(point["count"] == 0 for point in body["points"])
    assert body["summary"] == {
        "reports_in_range": 0,
        "reports_last_hour": 0,
        "reports_last_15_minutes": 0,
        "last_reported_at": None,
    }
    assert body["latest_check"] is None


def test_history_endpoint_returns_populated_seven_day_summary(
    client,
    db_session,
):
    now = monitors.utc_now()

    db_session.add_all(
        [
            OutageReportRecord(
                target="example.com",
                reporter_hash="recent",
                created_at=now - timedelta(minutes=10),
            ),
            OutageReportRecord(
                target="example.com",
                reporter_hash="earlier",
                created_at=now - timedelta(hours=2),
            ),
            OutageReportRecord(
                target="example.com",
                reporter_hash="expired",
                created_at=now - timedelta(days=8),
            ),
            CheckHistory(
                target="example.com",
                status="issues",
                latency=125.5,
                status_code=503,
                checked_at=now,
                error=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/api/status/example.com/history?range=7d"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["target"] == "example.com"
    assert body["range"] == "7d"
    assert len(body["points"]) == 7
    assert sum(point["count"] for point in body["points"]) == 2

    assert body["summary"]["reports_in_range"] == 2
    assert body["summary"]["reports_last_hour"] == 1
    assert body["summary"]["reports_last_15_minutes"] == 1
    assert body["summary"]["last_reported_at"] is not None

    latest_check = body["latest_check"]
    assert latest_check["checked_at"] is not None

    assert {
        key: value
        for key, value in latest_check.items()
        if key != "checked_at"
    } == {
        "target": "example.com",
        "status": "issues",
        "latency": 125.5,
        "status_code": 503,
        "error": None,
    }


def test_history_endpoint_rejects_invalid_range(client):
    response = client.get("/api/status/example.com/history?range=30d")

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "range"]


def test_history_endpoint_rejects_local_target(client):
    response = client.get("/api/status/printer.local/history")

    assert response.status_code == 400
    assert response.json() == {"detail": "Enter a public website address."}


@pytest.mark.parametrize("reporter_id", ["short", "x" * 101])
def test_report_outage_rejects_invalid_reporter_id(client, reporter_id):
    response = client.post(
        "/api/status/example.com/report",
        json={"reporter_id": reporter_id},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == [
        "body",
        "reporter_id",
    ]


def test_report_outage_rejects_local_target(client):
    response = client.post(
        "/api/status/printer.local/report",
        json={"reporter_id": "browser-identifier"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Enter a public website address."}


def test_report_outage_accepts_report_after_rate_limit_expires(
    client,
    db_session,
):
    reporter_hash = sha256(
        b"example.com:browser-identifier"
    ).hexdigest()

    db_session.add(
        OutageReportRecord(
            target="example.com",
            reporter_hash=reporter_hash,
            created_at=monitors.utc_now() - timedelta(hours=2),
        )
    )
    db_session.commit()

    response = client.post(
        "/api/status/example.com/report",
        json={"reporter_id": "browser-identifier"},
    )

    assert response.status_code == 201
    assert response.json()["accepted"] is True


def test_report_outage_rate_limit_is_scoped_to_target(client):
    payload = {"reporter_id": "browser-identifier"}

    first_response = client.post(
        "/api/status/example.com/report",
        json=payload,
    )
    second_response = client.post(
        "/api/status/example.org/report",
        json=payload,
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
