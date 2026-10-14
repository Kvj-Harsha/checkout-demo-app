"""Small checkout API with local-only fault controls and Prometheus metrics."""

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST
from prometheus_client import Counter
from prometheus_client import Histogram
from prometheus_client import generate_latest
from starlette.responses import Response

APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = Path(os.environ.get("DEMO_SETTINGS_PATH", APP_DIR / "settings.json"))
_STATE_LOCK = threading.Lock()
_FAULT_INJECTED = False

REQUESTS = Counter("checkout_requests_total", "Checkout requests", ["status"])
DURATION = Histogram("checkout_request_duration_seconds", "Checkout request duration")
app = FastAPI(title="Checkout Demo", version="1.0.0")


def read_settings() -> dict[str, Any]:
    """Read current config on each request so Sentinel can apply an approved local fix."""
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Checkout settings are unavailable") from exc


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Present a tiny demo console with visible fault controls."""
    return """<!doctype html><html><head><meta charset="utf-8"><title>Checkout Demo</title>
    <style>body{font:16px system-ui;background:#f3f6fb;color:#152238;margin:4rem auto;max-width:760px;padding:0 1rem}
    main{background:white;border:1px solid #dce4ef;border-radius:16px;padding:2rem;box-shadow:0 12px 36px #14243a12}
    button{padding:.8rem 1rem;border:0;border-radius:9px;margin:.35rem;cursor:pointer;font-weight:650}
    .bad{background:#b42318;color:white}.good{background:#13795b;color:white}code{background:#eef2f8;padding:.2rem .4rem}</style></head>
    <body><main><p>LOCAL DEMO SERVICE</p><h1>Checkout</h1>
    <p>This small storefront is monitored by Prometheus. Use the fault switch to simulate a checkout incident.</p>
    <button class="bad" onclick="fetch('/demo/fault',{method:'POST'}).then(show)">Inject checkout fault</button>
    <button class="good" onclick="fetch('/demo/recover',{method:'POST'}).then(show)">Clear demo fault</button>
    <p id="state">Loading service state…</p><p><a href="/docs">API docs</a> · <a href="/metrics">metrics</a> · <a href="/health">health</a></p>
    <script>async function show(r){let d=await r.json();document.querySelector('#state').textContent=JSON.stringify(d)}
    fetch('/demo/state').then(show)</script></main></body></html>"""


@app.get("/health")
def health() -> dict[str, str]:
    """Return service health for containers and recovery checks."""
    return {"status": "ok"}


@app.get("/demo/state")
def demo_state() -> dict[str, Any]:
    """Expose the current local demo fault state."""
    with _STATE_LOCK:
        injected = _FAULT_INJECTED
    settings = read_settings()
    return {"fault_injected": injected, "demo_faults_enabled": settings.get("demo_faults_enabled", False)}


@app.post("/demo/fault")
def inject_fault() -> dict[str, str]:
    """Make checkout calls fail until recovery or an approved config fix is applied."""
    global _FAULT_INJECTED
    if not read_settings().get("demo_faults_enabled", False):
        raise HTTPException(status_code=409, detail="Fault injection is disabled by the approved config")
    with _STATE_LOCK:
        _FAULT_INJECTED = True
    return {"status": "fault injected", "scope": "localhost demo only"}


@app.post("/demo/recover")
def recover_demo() -> dict[str, str]:
    """Manually clear the local demo fault switch."""
    global _FAULT_INJECTED
    with _STATE_LOCK:
        _FAULT_INJECTED = False
    return {"status": "demo fault cleared", "scope": "localhost demo only"}


@app.post("/checkout")
def checkout(order: dict[str, Any]) -> dict[str, str]:
    """Accept a demo order or return a measured synthetic checkout failure."""
    started = time.perf_counter()
    settings = read_settings()
    with _STATE_LOCK:
        injected = _FAULT_INJECTED
    error_rate = 1.0 if injected and settings.get("demo_faults_enabled", False) else float(
        settings.get("checkout_error_rate", 0.0)
    )
    failed = random.random() < max(0.0, min(error_rate, 1.0))
    DURATION.observe(time.perf_counter() - started)
    if failed:
        REQUESTS.labels(status="error").inc()
        raise HTTPException(status_code=503, detail="Checkout temporarily unavailable")
    REQUESTS.labels(status="ok").inc()
    return {"status": "accepted", "order_id": str(order.get("order_id", "demo-order"))}


@app.get("/metrics")
def metrics() -> Response:
    """Expose Prometheus counters and latency histogram."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
