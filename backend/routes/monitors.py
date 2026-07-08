from fastapi import Header, APIRouter, HTTPException, Depends
from datetime import datetime
from urllib.parse import urlparse
import sqlite3
import socket
import time

from database import get_db
from models import Monitor, TempCheck

router = APIRouter()

def current_timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S")

def find_monitor(monitor_id: int, owner: dict):
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT * FROM monitors
        WHERE id = ? AND owner_type = ? AND owner_id = ?
        """,
        (monitor_id, owner["owner_type"], owner["owner_id"]),
    )
    monitor = cursor.fetchone()
    conn.close()

    if monitor:
        return dict(monitor)

    return None

def normalize_website(raw_website: str):
    value = raw_website.strip()

    if not value:
        raise HTTPException(status_code=400, detail="Website cannot be empty")

    has_scheme = "://" in value
    parsed = urlparse(value if has_scheme else f"https://{value}")

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        scheme = "https"

    target = parsed.hostname
    if not target:
        raise HTTPException(status_code=400, detail="Invalid website or domain")

    target = target.lower()
    default_port = 443 if scheme == "https" else 80

    try:
        port = parsed.port or default_port
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid port")

    if port <= 0 or port >= 65536:
        raise HTTPException(status_code=400, detail="Port must be between 1 and 65535")

    return {
        "target": target,
        "port": port,
        "check_type": scheme,
    }

def get_owner(x_guest_id: str | None = Header(default=None)):
    if not x_guest_id:
        raise HTTPException(status_code=400, detail="Missing guest ID")
    return {
        "owner_type": "guest",
        "owner_id": x_guest_id
    }

def check_target(target: str, port: int, timeout: float, check_type: str):
    start_time = time.perf_counter()

    try:
        socket.getaddrinfo(target, port, type=socket.SOCK_STREAM)

        with socket.create_connection((target, port), timeout=timeout):
            pass

        end_time = time.perf_counter()
        latency = round((end_time - start_time) * 1000, 2)

        return {
            "target": target,
            "port": port,
            "check_type": check_type,
            "status": "online",
            "latency": latency,
            "last_error": None,
        }

    except socket.gaierror:
        return {
            "target": target,
            "port": port,
            "check_type": check_type,
            "status": "offline",
            "latency": None,
            "last_error": "DNS lookup failed",
        }

    except socket.timeout:
        return {
            "target": target,
            "port": port,
            "check_type": check_type,
            "status": "offline",
            "latency": None,
            "last_error": "Connection timed out",
        }

    except socket.error as e:
        return {
            "target": target,
            "port": port,
            "check_type": check_type,
            "status": "offline",
            "latency": None,
            "last_error": str(e),
        }

def record_popular_check(conn, target: str, status: str, latency: float | None, checked_at: str):
    conn.execute(
        """
        INSERT INTO popular_checks
        (target, total_checks, last_checked, last_status, last_latency)
        VALUES (?, 1, ?, ?, ?)
        ON CONFLICT(target) DO UPDATE SET
            total_checks = total_checks + 1,
            last_checked = excluded.last_checked,
            last_status = excluded.last_status,
            last_latency = excluded.last_latency
        """,
        (target, checked_at, status, latency),
    )

#GET ENDPOINTS

@router.get("/popular")
def get_popular_websites():
    conn = get_db()
    rows = conn.execute(
        """
        SELECT target, total_checks, last_checked, last_status, last_latency
        FROM popular_checks
        ORDER BY total_checks DESC, target ASC
        LIMIT 10
        """
    ).fetchall()
    conn.close()

    return [dict(row) for row in rows]

@router.get("/monitors")
def get_monitors(owner=Depends(get_owner)):
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT * FROM monitors
        WHERE owner_type = ? AND owner_id = ?
        ORDER BY id DESC
        """,
        (owner["owner_type"], owner["owner_id"]),
    )
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]

@router.get("/monitors/{monitor_id}")
def read_monitor(monitor_id: int, owner=Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)

    if monitor:
        return monitor

    raise HTTPException(status_code=404, detail="Monitor not found")

@router.get("/monitors/{monitor_id}/history")
def get_monitor_history(monitor_id: int, owner = Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    conn = get_db()
    cursor = conn.execute("SELECT * FROM check_history WHERE monitor_id = ? ORDER BY id DESC", (monitor_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@router.get("/monitors/{monitor_id}/stats")
def get_monitor_stats(monitor_id: int, owner = Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    conn = get_db()
    cursor = conn.execute(
        """
        SELECT
        COUNT(*) AS total_checks,
        COALESCE(SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END), 0) AS online_checks,
        COALESCE(SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END), 0) AS offline_checks,
        AVG(latency) AS avg_latency
        FROM check_history
        WHERE monitor_id = ?
        """,
        (monitor_id,)
    )
    stats = dict(cursor.fetchone())
    conn.close()

    up = stats["online_checks"]
    total = stats["total_checks"]
    stats["uptime_percentage"] = round((up / total) * 100, 2) if total > 0 else None

    return stats

@router.get("/monitors/{monitor_id}/incidents")
def get_monitor_incidents(monitor_id: int, owner = Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    conn = get_db()
    rows = conn.execute(
        """
        SELECT * FROM incidents
        WHERE monitor_id = ?
        ORDER BY id DESC
        """,
        (monitor_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

#POST ENDPOINTS

@router.post("/check-once")
def check_url(request: TempCheck):
    normalized = normalize_website(request.website)
    result = check_target(
        normalized["target"],
        normalized["port"],
        request.timeout,
        normalized["check_type"],
    )

    checked_at = current_timestamp()
    result["checked_at"] = checked_at

    conn = get_db()
    record_popular_check(conn, result["target"], result["status"], result["latency"], checked_at)
    conn.commit()
    conn.close()

    return result

@router.post("/monitors")
def add_monitor(monitor: Monitor, owner=Depends(get_owner)):
    normalized = normalize_website(monitor.website)
    monitor_name = monitor.name.strip() if monitor.name and monitor.name.strip() else normalized["target"]

    conn = get_db()

    try:
        cursor = conn.execute(
            """
            INSERT INTO monitors
            (owner_type, owner_id, name, target, port, timeout, check_type, status, latency, last_checked, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                owner["owner_type"],
                owner["owner_id"],
                monitor_name,
                normalized["target"],
                normalized["port"],
                monitor.timeout,
                normalized["check_type"],
                None,
                None,
                None,
                None,
            ),
        )
        conn.commit()
        monitor_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?",
            (monitor_id,),
        ).fetchone()

        return dict(row)

    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="You already saved this website")

    finally:
        conn.close()

@router.post("/monitors/{monitor_id}/check")
def check_monitor(monitor_id: int, owner = Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    result = check_target(
        monitor["target"],
        monitor["port"],
        monitor["timeout"],
        monitor["check_type"],
    )
    checked_at = current_timestamp()
    result["checked_at"] = checked_at
    conn = get_db()

    try:
        latest_incident = conn.execute(
            """
            SELECT * FROM incidents
            WHERE monitor_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (monitor_id,),
        ).fetchone()
        if result["status"] == "offline":
            if not latest_incident or latest_incident["status"] != "ongoing":
                conn.execute(
                    """
                    INSERT INTO incidents
                    (monitor_id, started_at, status)
                    VALUES (?, ?, ?)
                    """,
                    (monitor_id, checked_at, "ongoing"),
                )
        if result["status"] == "online" and latest_incident and latest_incident["status"] == "ongoing":
            duration = (
                datetime.strptime(checked_at, "%Y-%m-%d %H:%M:%S")
                - datetime.strptime(latest_incident["started_at"], "%Y-%m-%d %H:%M:%S")
            ).total_seconds()

            conn.execute(
                """
                UPDATE incidents
                SET resolved_at = ?, duration = ?, status = ?
                WHERE id = ?
                """,
                (checked_at, duration, "resolved", latest_incident["id"]),
            )

        conn.execute(
            """
            UPDATE monitors
            SET status = ?, latency = ?, last_checked = ?, last_error = ?
            WHERE id = ?
            """,
            (result["status"], result["latency"], checked_at, result["last_error"], monitor_id),
        )

        cursor = conn.execute(
            """
            INSERT INTO check_history
            (monitor_id, status, latency, checked_at, last_error)
            VALUES (?, ?, ?, ?, ?)
            """,
            (monitor_id, result["status"], result["latency"], checked_at, result["last_error"]),
        )

        record_popular_check(conn, result["target"], result["status"], result["latency"], checked_at)

        conn.commit()
        recent_check_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM check_history WHERE id = ?",
            (recent_check_id,),
        ).fetchone()

        return dict(row)
    finally:
        conn.close()

#DELETE ENDPOINTS

@router.delete("/monitors/{monitor_id}")
def delete_monitor(monitor_id: int, owner = Depends(get_owner)):
    monitor = find_monitor(monitor_id, owner)
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")
    conn = get_db()
    conn.execute("DELETE FROM check_history WHERE monitor_id = ?", (monitor_id,))
    conn.execute("DELETE FROM incidents WHERE monitor_id = ?", (monitor_id,))
    conn.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
    conn.commit()
    conn.close()
    return {"message": "Monitor deleted"}

#PUT ENDPOINTS

@router.put("/monitors/{monitor_id}")
def update_monitor(monitor_id: int, monitor: Monitor, owner=Depends(get_owner)):
    existing_monitor = find_monitor(monitor_id, owner)

    if not existing_monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    normalized = normalize_website(monitor.website)
    monitor_name = monitor.name.strip() if monitor.name and monitor.name.strip() else normalized["target"]

    conn = get_db()

    try:
        conn.execute(
            """
            UPDATE monitors
            SET name = ?, target = ?, port = ?, timeout = ?, check_type = ?
            WHERE id = ?
            """,
            (
                monitor_name,
                normalized["target"],
                normalized["port"],
                monitor.timeout,
                normalized["check_type"],
                monitor_id,
            ),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM monitors WHERE id = ?",
            (monitor_id,),
        ).fetchone()

        return dict(row)

    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="You already saved this website")

    finally:
        conn.close()