import logging
import time
from uuid import uuid4

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from logging_config import configure_logging
from routes.monitors import router as monitors_router

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        send_default_pii=False,
        traces_sample_rate=0.0,
    )

configure_logging()
request_logger = logging.getLogger("api.request")

app = FastAPI(title="Is My Website Down API", version="1.0.0")


@app.middleware("http")
async def log_http_request(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round(
            (time.perf_counter() - started_at) * 1000,
            2,
        )

        request_logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": duration_ms,
            },
        )
        raise

    duration_ms = round(
        (time.perf_counter() - started_at) * 1000,
        2,
    )

    response.headers["X-Request-ID"] = request_id

    request_logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )

    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID"],
)

app.include_router(monitors_router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
