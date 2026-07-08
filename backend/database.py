import sqlite3

DATABASE = "monitor.db"

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS monitors (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 owner_type TEXT CHECK(owner_type IN ('guest', 'user')) NOT NULL,
                 owner_id TEXT NOT NULL,
                 name TEXT NOT NULL,
                 target TEXT NOT NULL,
                 port INTEGER CHECK (port > 0 AND port < 65536) NOT NULL,
                 timeout REAL CHECK (timeout > 0) NOT NULL,
                 check_type TEXT CHECK(check_type IN ('https', 'http', 'dns', 'tcp')) NOT NULL DEFAULT 'https',
                 status TEXT,
                 latency REAL,
                 last_checked TEXT,
                 last_error TEXT,
                 UNIQUE(owner_type, owner_id, target, port, check_type))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS check_history (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 monitor_id INTEGER NOT NULL,
                 status TEXT CHECK (status IN ('online', 'offline')) NOT NULL,
                 latency REAL,
                 checked_at TEXT NOT NULL,
                 last_error TEXT,
                 FOREIGN KEY(monitor_id) REFERENCES monitors(id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS incidents (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 monitor_id INTEGER NOT NULL,
                 started_at TEXT NOT NULL,
                 resolved_at TEXT,
                 duration REAL,
                 status TEXT CHECK (status IN ('ongoing', 'resolved')) NOT NULL,
                 FOREIGN KEY(monitor_id) REFERENCES monitors(id))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS popular_checks (
                target TEXT PRIMARY KEY,
                total_checks INTEGER NOT NULL DEFAULT 0,
                last_checked TEXT,
                last_status TEXT CHECK(last_status IN ('online', 'offline')),
                last_latency REAL)''')
    conn.commit()
    conn.close()