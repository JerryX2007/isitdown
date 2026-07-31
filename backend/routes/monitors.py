import socket
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from ipaddress import ip_address
from re import fullmatch
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query

from database import get_db
from models import Monitor, OutageReport

router = APIRouter(prefix="/api", tags=["website status"])


def utc_now():
    return datetime.now(timezone.utc)


def utc_timestamp():
    return utc_now().isoformat().replace("+00:00", "Z")


def get_public_addresses(target: str):
    try:
        address_info = socket.getaddrinfo(target, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []

    addresses = {entry[4][0] for entry in address_info}

    for address in addresses:
        parsed_address = ip_address(address)
        if not parsed_address.is_global or parsed_address.is_multicast:
            raise HTTPException(
                status_code=400,
                detail="Private or local network addresses cannot be checked.",
            )

    return list(addresses)


def normalize_website(raw_website: str):
    value = raw_website.strip()

    if not value:
        raise HTTPException(status_code=400, detail="Enter a website to check.")

    try:
        parsed = urlparse(value if "://" in value else f"https://{value}")
        custom_port = parsed.port is not None
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid website, such as example.com.",
        ) from error

    scheme = parsed.scheme.lower()

    if scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400,
            detail="Only HTTP and HTTPS websites can be checked.",
        )

    if parsed.username or parsed.password or custom_port:
        raise HTTPException(
            status_code=400,
            detail="Enter a website without login details or a custom port.",
        )

    if not parsed.hostname:
        raise HTTPException(
            status_code=400,
            detail="Enter a valid website, such as example.com.",
        )

    try:
        target = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as error:
        raise HTTPException(
            status_code=400, detail="Invalid website address."
        ) from error

    labels = target.split(".")
    if len(target) > 253 or any(
        fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
        for label in labels
    ):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid website, such as example.com.",
        )

    if target == "localhost" or target.endswith(".local") or "." not in target:
        raise HTTPException(
            status_code=400,
            detail="Enter a public website address.",
        )

    return {
        "target": target,
        "scheme": scheme,
        "url": f"{scheme}://{target}",
    }


def check_target(website: str, timeout: float):
    normalized = normalize_website(website)
    target = normalized["target"]
    addresses = get_public_addresses(target)
    checked_at = utc_timestamp()

    if not addresses:
        return {
            "target": target,
            "status": "down",
            "latency": None,
            "status_code": None,
            "checked_at": checked_at,
            "error": "DNS lookup failed.",
        }

    urls = [normalized["url"]]
    if normalized["scheme"] == "https":
        urls.append(f"http://{target}")

    last_error = "The website did not respond."

    with httpx.Client(
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(timeout),
        headers={
            "User-Agent": "WebsiteStatusChecker/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    ) as client:
        for url in urls:
            started_at = time.perf_counter()

            try:
                response = client.head(url)
                if response.status_code == 405:
                    response = client.get(url, headers={"Range": "bytes=0-0"})

                latency = round((time.perf_counter() - started_at) * 1000, 2)
                status = "issues" if response.status_code >= 500 else "up"

                return {
                    "target": target,
                    "status": status,
                    "latency": latency,
                    "status_code": response.status_code,
                    "checked_at": checked_at,
                    "error": None,
                }
            except httpx.TimeoutException:
                last_error = "The connection timed out."
            except httpx.HTTPError:
                last_error = "We could not connect to this website."

    return {
        "target": target,
        "status": "down",
        "latency": None,
        "status_code": None,
        "checked_at": checked_at,
        "error": last_error,
    }


def record_check(result: dict):
    connection = get_db()
    connection.execute(
        """
        INSERT INTO check_history
        (target, status, latency, status_code, checked_at, error)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            result["target"],
            result["status"],
            result["latency"],
            result["status_code"],
            result["checked_at"],
            result["error"],
        ),
    )
    connection.commit()
    connection.close()


def create_empty_timeline(selected_range: str):
    now = utc_now()

    if selected_range == "7d":
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return [
            {
                "key": (end - timedelta(days=6 - index)).strftime("%Y-%m-%d"),
                "count": 0,
            }
            for index in range(7)
        ]

    end = now.replace(minute=0, second=0, microsecond=0)
    return [
        {
            "key": (end - timedelta(hours=23 - index)).strftime("%Y-%m-%dT%H:00:00Z"),
            "count": 0,
        }
        for index in range(24)
    ]


# GET ENDPOINTS


@router.get("/status/{target}/history")
def get_outage_history(
    target: str,
    selected_range: str = Query(default="24h", alias="range", pattern="^(24h|7d)$"),
):
    normalized = normalize_website(target)
    clean_target = normalized["target"]
    timeline = create_empty_timeline(selected_range)
    bucket_format = "%Y-%m-%d" if selected_range == "7d" else "%Y-%m-%dT%H:00:00Z"
    since = "-7 days" if selected_range == "7d" else "-24 hours"

    connection = get_db()
    report_rows = connection.execute(
        f"""
        SELECT
            strftime('{bucket_format}', datetime(created_at)) AS bucket,
            COUNT(*) AS report_count
        FROM outage_reports
        WHERE target = ?
          AND datetime(created_at) >= datetime('now', ?)
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        (clean_target, since),
    ).fetchall()

    summary = dict(
        connection.execute(
            """
            SELECT
                COUNT(*) AS reports_in_range,
                COALESCE(SUM(
                    CASE
                        WHEN datetime(created_at) >= datetime('now', '-1 hour')
                        THEN 1 ELSE 0
                    END
                ), 0) AS reports_last_hour,
                COALESCE(SUM(
                    CASE
                        WHEN datetime(created_at) >= datetime('now', '-15 minutes')
                        THEN 1 ELSE 0
                    END
                ), 0) AS reports_last_15_minutes,
                MAX(created_at) AS last_reported_at
            FROM outage_reports
            WHERE target = ?
              AND datetime(created_at) >= datetime('now', ?)
            """,
            (clean_target, since),
        ).fetchone()
    )

    latest_check_row = connection.execute(
        """
        SELECT status, latency, status_code, checked_at, error
        FROM check_history
        WHERE target = ?
        ORDER BY datetime(checked_at) DESC
        LIMIT 1
        """,
        (clean_target,),
    ).fetchone()
    connection.close()

    counts = {row["bucket"]: row["report_count"] for row in report_rows}
    for point in timeline:
        point["count"] = counts.get(point["key"], 0)

    return {
        "target": clean_target,
        "range": selected_range,
        "points": timeline,
        "summary": summary,
        "latest_check": dict(latest_check_row) if latest_check_row else None,
    }


# POST ENDPOINTS


@router.post("/check")
def check_website(request: Monitor):
    result = check_target(request.website, request.timeout)
    record_check(result)
    return result


@router.post("/status/{target}/report", status_code=201)
def report_outage(target: str, report: OutageReport):
    normalized = normalize_website(target)
    clean_target = normalized["target"]
    reporter_hash = sha256(
        f"{clean_target}:{report.reporter_id}".encode("utf-8")
    ).hexdigest()

    connection = get_db()
    existing_report = connection.execute(
        """
        SELECT id
        FROM outage_reports
        WHERE target = ?
          AND reporter_hash = ?
          AND datetime(created_at) >= datetime('now', '-1 hour')
        LIMIT 1
        """,
        (clean_target, reporter_hash),
    ).fetchone()

    if existing_report:
        connection.close()
        raise HTTPException(
            status_code=409,
            detail="You already reported an issue with this website recently.",
        )

    created_at = utc_timestamp()
    connection.execute(
        """
        INSERT INTO outage_reports (target, reporter_hash, created_at)
        VALUES (?, ?, ?)
        """,
        (clean_target, reporter_hash, created_at),
    )
    connection.commit()
    connection.close()

    return {"accepted": True, "created_at": created_at}
