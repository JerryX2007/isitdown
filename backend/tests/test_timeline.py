from datetime import datetime, timezone

from routes import monitors


def test_create_empty_timeline_returns_last_24_complete_hours(monkeypatch):
    monkeypatch.setattr(
        monitors,
        "utc_now",
        lambda: datetime(2026, 7, 31, 14, 37, 12, tzinfo=timezone.utc),
    )

    timeline = monitors.create_empty_timeline("24h")

    assert len(timeline) == 24
    assert timeline[0] == {
        "key": "2026-07-30T15:00:00Z",
        "count": 0,
    }
    assert timeline[-1] == {
        "key": "2026-07-31T14:00:00Z",
        "count": 0,
    }
    assert all(point["count"] == 0 for point in timeline)


def test_create_empty_timeline_returns_last_seven_utc_days(monkeypatch):
    monkeypatch.setattr(
        monitors,
        "utc_now",
        lambda: datetime(2026, 7, 31, 14, 37, 12, tzinfo=timezone.utc),
    )

    timeline = monitors.create_empty_timeline("7d")

    assert len(timeline) == 7
    assert timeline[0] == {"key": "2026-07-25", "count": 0}
    assert timeline[-1] == {"key": "2026-07-31", "count": 0}
    assert all(point["count"] == 0 for point in timeline)
