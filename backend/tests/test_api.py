import socket
from hashlib import sha256

import pytest

import database
from routes import monitors


def test_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_endpoint_records_result(client, monkeypatch):
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

    connection = database.get_db()
    saved_check = connection.execute("""
        SELECT target, status, latency, status_code, checked_at, error
        FROM check_history
        """).fetchone()
    connection.close()

    assert dict(saved_check) == fake_result


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
):
    response = client.post(
        "/api/check",
        json={"website": website},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": expected_detail}

    connection = database.get_db()
    saved_checks = connection.execute("SELECT COUNT(*) FROM check_history").fetchone()[
        0
    ]
    connection.close()
    assert saved_checks == 0


def test_check_endpoint_returns_400_for_private_dns(client, monkeypatch):
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

    connection = database.get_db()
    saved_checks = connection.execute("SELECT COUNT(*) FROM check_history").fetchone()[
        0
    ]
    connection.close()
    assert saved_checks == 0


def test_report_outage_accepts_and_hashes_reporter_id(client, monkeypatch):
    monkeypatch.setattr(
        monitors,
        "utc_timestamp",
        lambda: "2026-07-31T12:00:00Z",
    )

    response = client.post(
        "/api/status/example.com/report",
        json={"reporter_id": "browser-identifier"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "accepted": True,
        "created_at": "2026-07-31T12:00:00Z",
    }

    connection = database.get_db()
    saved_report = connection.execute("""
        SELECT target, reporter_hash, created_at
        FROM outage_reports
        """).fetchone()
    connection.close()

    assert dict(saved_report) == {
        "target": "example.com",
        "reporter_hash": sha256(b"example.com:browser-identifier").hexdigest(),
        "created_at": "2026-07-31T12:00:00Z",
    }


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


def test_history_endpoint_returns_populated_seven_day_summary(client):
    connection = database.get_db()
    connection.execute("""
        INSERT INTO outage_reports (target, reporter_hash, created_at)
        VALUES ('example.com', 'recent', datetime('now', '-10 minutes'))
        """)
    connection.execute("""
        INSERT INTO outage_reports (target, reporter_hash, created_at)
        VALUES ('example.com', 'earlier', datetime('now', '-2 hours'))
        """)
    connection.execute("""
        INSERT INTO outage_reports (target, reporter_hash, created_at)
        VALUES ('example.com', 'expired', datetime('now', '-8 days'))
        """)
    connection.execute("""
        INSERT INTO check_history
        (target, status, latency, status_code, checked_at, error)
        VALUES (
            'example.com', 'issues', 125.5, 503, datetime('now'), NULL
        )
        """)
    connection.commit()
    connection.close()

    response = client.get("/api/status/example.com/history?range=7d")

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
        key: value for key, value in latest_check.items() if key != "checked_at"
    } == {
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


def test_report_outage_accepts_report_after_rate_limit_expires(client):
    reporter_hash = sha256(b"example.com:browser-identifier").hexdigest()
    connection = database.get_db()
    connection.execute(
        """
        INSERT INTO outage_reports (target, reporter_hash, created_at)
        VALUES (?, ?, datetime('now', '-2 hours'))
        """,
        ("example.com", reporter_hash),
    )
    connection.commit()
    connection.close()

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
