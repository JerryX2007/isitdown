import sqlite3
from pathlib import Path

DATABASE = Path(__file__).with_name("monitor.db")


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS check_history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 target TEXT NOT NULL,
                 status TEXT CHECK(status IN ('up', 'issues', 'down')) NOT NULL,
                 latency REAL,
                 status_code INTEGER,
                 checked_at TEXT NOT NULL,
                 error TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS outage_reports (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 target TEXT NOT NULL,
                 reporter_hash TEXT NOT NULL,
                 created_at TEXT NOT NULL)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS check_history_target_time_idx
                 ON check_history(target, checked_at)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS outage_reports_target_time_idx
                 ON outage_reports(target, created_at)""")
    conn.execute("""CREATE INDEX IF NOT EXISTS outage_reports_rate_limit_idx
                 ON outage_reports(target, reporter_hash, created_at)""")
    conn.commit()
    conn.close()
