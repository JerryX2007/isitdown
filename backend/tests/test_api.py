from hashlib import sha256

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


def test_check_endpoint_rejects_invalid_timeout(client):
    response = client.post(
        "/api/check",
        json={"website": "example.com", "timeout": 0},
    )

    assert response.status_code == 422


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