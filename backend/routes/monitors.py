import socket
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from ipaddress import ip_address
from re import fullmatch
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_session
from database_models import CheckHistory, OutageReportRecord
from models import Monitor, OutageReport

router = APIRouter(prefix="/api", tags=["website status"])


def utc_now():
    return datetime.now(timezone.utc)


def utc_timestamp():
    return utc_now().isoformat().replace("+00:00", "Z")

def as_utc(value: datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)

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


def record_check(result: dict, session: Session):
    checked_at = datetime.fromisoformat(
        result["checked_at"].replace("Z", "+00:00")
    )

    record = CheckHistory(
        target=result["target"],
        status=result["status"],
        latency=result["latency"],
        status_code=result["status_code"],
        checked_at=checked_at,
        error=result["error"],
    )

    session.add(record)
    session.commit()


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
    selected_range: str = Query(
        default="24h",
        alias="range",
        pattern="^(24h|7d)$",
    ),
    session: Session = Depends(get_session),
):
    normalized = normalize_website(target)
    clean_target = normalized["target"]
    now = utc_now()
    timeline = create_empty_timeline(selected_range)

    if selected_range == "7d":
        cutoff = (
            now.replace(hour=0, minute=0, second=0, microsecond=0)
            - timedelta(days=6)
        )
        bucket_format = "%Y-%m-%d"
    else:
        cutoff = (
            now.replace(minute=0, second=0, microsecond=0)
            - timedelta(hours=23)
        )
        bucket_format = "%Y-%m-%dT%H:00:00Z"

    report_times = [
        as_utc(value)
        for value in session.scalars(
            select(OutageReportRecord.created_at)
            .where(
                OutageReportRecord.target == clean_target,
                OutageReportRecord.created_at >= cutoff,
            )
            .order_by(OutageReportRecord.created_at)
        ).all()
    ]

    counts: dict[str, int] = {}

    for created_at in report_times:
        bucket = created_at.strftime(bucket_format)
        counts[bucket] = counts.get(bucket, 0) + 1

    for point in timeline:
        point["count"] = counts.get(point["key"], 0)

    one_hour_ago = now - timedelta(hours=1)
    fifteen_minutes_ago = now - timedelta(minutes=15)

    latest_check = session.scalar(
        select(CheckHistory)
        .where(CheckHistory.target == clean_target)
        .order_by(CheckHistory.checked_at.desc())
        .limit(1)
    )

    latest_check_data = None

    if latest_check is not None:
        latest_check_data = {
            "target": latest_check.target,
            "status": latest_check.status,
            "latency": latest_check.latency,
            "status_code": latest_check.status_code,
            "checked_at": (
                as_utc(latest_check.checked_at)
                .isoformat()
                .replace("+00:00", "Z")
            ),
            "error": latest_check.error,
        }

    last_reported_at = max(report_times) if report_times else None

    return {
        "target": clean_target,
        "range": selected_range,
        "points": timeline,
        "summary": {
            "reports_in_range": len(report_times),
            "reports_last_hour": sum(
                value >= one_hour_ago for value in report_times
            ),
            "reports_last_15_minutes": sum(
                value >= fifteen_minutes_ago for value in report_times
            ),
            "last_reported_at": (
                last_reported_at.isoformat().replace("+00:00", "Z")
                if last_reported_at
                else None
            ),
        },
        "latest_check": latest_check_data,
    }


# POST ENDPOINTS


@router.post("/check")
def check_website(
    request: Monitor,
    session: Session = Depends(get_session),
):
    result = check_target(request.website, request.timeout)
    record_check(result, session)
    return result


@router.post("/status/{target}/report", status_code=201)
def report_outage(
    target: str,
    report: OutageReport,
    session: Session = Depends(get_session),
):
    normalized = normalize_website(target)
    clean_target = normalized["target"]

    reporter_hash = sha256(
        f"{clean_target}:{report.reporter_id}".encode("utf-8")
    ).hexdigest()

    one_hour_ago = utc_now() - timedelta(hours=1)

    existing_report = session.scalar(
        select(OutageReportRecord.id)
        .where(
            OutageReportRecord.target == clean_target,
            OutageReportRecord.reporter_hash == reporter_hash,
            OutageReportRecord.created_at >= one_hour_ago,
        )
        .limit(1)
    )

    if existing_report is not None:
        raise HTTPException(
            status_code=409,
            detail="You already reported an issue with this website recently.",
        )

    created_at = utc_now()

    session.add(
        OutageReportRecord(
            target=clean_target,
            reporter_hash=reporter_hash,
            created_at=created_at,
        )
    )
    session.commit()

    return {
        "accepted": True,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
    }
