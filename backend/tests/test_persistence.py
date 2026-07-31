import database
from routes import monitors


def test_record_check_preserves_failed_check_details(client):
    failed_check = {
        "target": "unavailable.example",
        "status": "down",
        "latency": None,
        "status_code": None,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": "The connection timed out.",
    }

    monitors.record_check(failed_check)

    connection = database.get_db()
    saved_check = connection.execute("""
        SELECT target, status, latency, status_code, checked_at, error
        FROM check_history
        """).fetchone()
    connection.close()

    assert dict(saved_check) == failed_check
