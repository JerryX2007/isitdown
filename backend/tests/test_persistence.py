from sqlalchemy import select

from database_models import CheckHistory
from routes import monitors


def test_record_check_preserves_failed_check_details(db_session):
    failed_check = {
        "target": "unavailable.example",
        "status": "down",
        "latency": None,
        "status_code": None,
        "checked_at": "2026-07-31T12:00:00Z",
        "error": "The connection timed out.",
    }

    monitors.record_check(failed_check, db_session)

    saved_check = db_session.scalar(select(CheckHistory))

    assert saved_check is not None
    assert {
        "target": saved_check.target,
        "status": saved_check.status,
        "latency": saved_check.latency,
        "status_code": saved_check.status_code,
        "checked_at": (
            monitors.as_utc(saved_check.checked_at).isoformat().replace("+00:00", "Z")
        ),
        "error": saved_check.error,
    } == failed_check
