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
