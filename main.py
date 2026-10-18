
import json
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from fastapi.responses import Response
from prometheus_client import (
    Counter,
    CollectorRegistry,
    CONTENT_TYPE_LATEST,
    generate_latest,
)

app = FastAPI(title="Observable API")

# Use a dedicated registry so the metric is predictable.
registry = CollectorRegistry()

# Prometheus exposes this counter as http_requests_total.
http_requests = Counter(
    "http_requests",
    "Total HTTP requests received by the service",
    registry=registry,
)

START_TIME = time.monotonic()
LOG_LIMIT = 1000
recent_logs = deque(maxlen=LOG_LIMIT)

# Structured JSON logs are emitted to stdout.
logger = logging.getLogger("observable_api")
logger.setLevel(logging.INFO)
logger.handlers.clear()
logger.propagate = False

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(handler)


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def record_request(level, path, request_id, status_code):
    entry = {
        "level": level,
        "ts": utc_timestamp(),
        "path": path,
        "request_id": request_id,
        "status_code": status_code,
    }
    recent_logs.append(entry)
    logger.log(
        logging.ERROR if level == "ERROR" else logging.INFO,
        json.dumps(entry),
    )


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # Count every incoming request, including /metrics and /healthz.
    http_requests.inc()

    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        record_request(
            level="INFO" if response.status_code < 500 else "ERROR",
            path=request.url.path,
            request_id=request_id,
            status_code=response.status_code,
        )
        return response

    except Exception:
        record_request(
            level="ERROR",
            path=request.url.path,
            request_id=request_id,
            status_code=500,
        )
        raise


@app.get("/work")
async def work(n: int = Query(default=1, ge=0, le=100000)):
    # Perform n units of simple work.
    for _ in range(n):
        pass

    return {
        "email": "22f3002265@ds.study.iitm.ac.in",
        "done": n,
    }


@app.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "uptime_s": float(time.monotonic() - START_TIME),
    }


@app.get("/logs/tail")
async def logs_tail(limit: int = Query(default=20, ge=1, le=LOG_LIMIT)):
    # Return the newest entries, oldest to newest within the selected tail.
    return list(recent_logs)[-limit:]
