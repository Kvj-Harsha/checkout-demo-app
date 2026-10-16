"""Small checkout API with a real pricing code path, local-only demo controls and Prometheus metrics."""

import hashlib
import json
import logging
import os
import random
import threading
import time
import types
import urllib.error
import urllib.request
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
# Pricing is hot-loaded from this file on every change, so a reviewed, merged fix goes live without a rebuild.
PRICING_PATH = Path(os.environ.get("PRICING_PATH", APP_DIR / "pricing.py"))
LOGGER = logging.getLogger("uvicorn.error")
_PRICING_LOCK = threading.Lock()
_PRICING_CACHE: dict[str, Any] = {"stamp": None, "module": None}
SUPPORTED_MARKETS = ["US", "GB", "DE", "FR"]
NEW_MARKETS = ["IN", "BR", "JP", "MX"]
_STATE_LOCK = threading.Lock()
_FAULT_INJECTED = False
# Simulated shoppers: pressing "Inject checkout fault" is the single trigger for the whole demo, so the app also
# produces its own traffic (real requests to its own /checkout, which Prometheus and the logs then record).
TRAFFIC_SHOPPERS = int(os.environ.get("DEMO_TRAFFIC_SHOPPERS", "12"))
TRAFFIC_SECONDS = int(os.environ.get("DEMO_TRAFFIC_SECONDS", "150"))
_TRAFFIC_STOP = threading.Event()
_TRAFFIC_THREADS: list[threading.Thread] = []

REQUESTS = Counter("checkout_requests_total", "Checkout requests", ["status"])
DURATION = Histogram("checkout_request_duration_seconds", "Checkout request duration")
app = FastAPI(title="Checkout Demo", version="1.0.0")


def read_settings() -> dict[str, Any]:
    """Read current config on each request so Sentinel can apply an approved local fix."""
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Checkout settings are unavailable") from exc


def load_pricing() -> Any:
    """Return the current pricing module, re-reading the file whenever it changes on disk."""
    source = PRICING_PATH.read_bytes()  # tiny file; hashing its content is more reliable than mtime/size
    stamp = hashlib.sha256(source).hexdigest()
    with _PRICING_LOCK:
        if _PRICING_CACHE["stamp"] != stamp:
            module = types.ModuleType("pricing_live")
            exec(compile(source, str(PRICING_PATH), "exec"), module.__dict__)  # noqa: S102 - reviewed, merged code
            _PRICING_CACHE.update(stamp=stamp, module=module)
        return _PRICING_CACHE["module"]


def _shopper(index: int, deadline: float) -> None:
    """One simulated shopper: place an order about every half second until recovery or the deadline."""
    order = 0
    url = os.environ.get("DEMO_TRAFFIC_URL", "http://127.0.0.1:8000/checkout")
    while not _TRAFFIC_STOP.is_set() and time.monotonic() < deadline:
        order += 1
        # Half of the shoppers are in markets the v2.14.0 pricing table does not know about.
        country = random.choice(SUPPORTED_MARKETS + NEW_MARKETS)
        body = json.dumps({"order_id": f"sim-{index}-{order}", "country": country, "subtotal": 49.9}).encode()
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(request, timeout=3).close()
        except (urllib.error.URLError, OSError):
            pass  # a 503 is the point of the demo; the failure is already counted by the endpoint
        _TRAFFIC_STOP.wait(0.5)


def start_traffic() -> None:
    """Start simulated shoppers (idempotent: a running burst is not doubled)."""
    with _STATE_LOCK:
        if any(thread.is_alive() for thread in _TRAFFIC_THREADS):
            return
        _TRAFFIC_STOP.clear()
        deadline = time.monotonic() + TRAFFIC_SECONDS
        _TRAFFIC_THREADS[:] = [
            threading.Thread(target=_shopper, args=(index, deadline), daemon=True, name=f"shopper-{index}")
            for index in range(TRAFFIC_SHOPPERS)
        ]
        for thread in _TRAFFIC_THREADS:
            thread.start()


def stop_traffic() -> None:
    """Stop the simulated shoppers (recovery, or the approved fix)."""
    _TRAFFIC_STOP.set()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Present a tiny demo console with visible fault controls."""
    return """<!doctype html><html><head><meta charset="utf-8"><title>Checkout Demo</title>
    <style>body{font:16px system-ui;background:#f3f6fb;color:#152238;margin:4rem auto;max-width:760px;padding:0 1rem}
    main{background:white;border:1px solid #dce4ef;border-radius:16px;padding:2rem;box-shadow:0 12px 36px #14243a12}
    button{padding:.8rem 1rem;border:0;border-radius:9px;margin:.35rem;cursor:pointer;font-weight:650}
    .bad{background:#b42318;color:white}.good{background:#13795b;color:white}code{background:#eef2f8;padding:.2rem .4rem}</style></head>
    <body><main><p>LOCAL DEMO SERVICE</p><h1>Checkout</h1>
    <p>Release v2.14.0 is live. Start the incident to send real shopper traffic, including customers from new markets, and watch Sentinel investigate and propose a code fix.</p>
    <button class="bad" onclick="fetch('/demo/fault',{method:'POST'}).then(show)">Start incident: traffic from new markets</button>
    <button class="good" onclick="fetch('/demo/recover',{method:'POST'}).then(show)">Stop traffic</button>
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
    """Start the incident: shoppers, including ones in new markets the v2.14.0 pricing code cannot price."""
    global _FAULT_INJECTED
    if not read_settings().get("demo_faults_enabled", False):
        raise HTTPException(status_code=409, detail="Fault injection is disabled by the approved config")
    with _STATE_LOCK:
        _FAULT_INJECTED = True
    if os.environ.get("DEMO_TRAFFIC", "on").lower() != "off":
        start_traffic()
    return {"status": "incident started", "scope": "localhost demo only",
            "traffic": f"{TRAFFIC_SHOPPERS} simulated shoppers for up to {TRAFFIC_SECONDS}s"}


@app.post("/demo/recover")
def recover_demo() -> dict[str, str]:
    """Manually clear the local demo fault switch."""
    global _FAULT_INJECTED
    with _STATE_LOCK:
        _FAULT_INJECTED = False
    stop_traffic()
    return {"status": "demo fault cleared", "scope": "localhost demo only"}


@app.post("/checkout")
def checkout(order: dict[str, Any]) -> dict[str, str]:
    """Price and accept an order. A failure here is a real exception from the pricing code, not a switch."""
    started = time.perf_counter()
    settings = read_settings()
    country = str(order.get("country", "US")).upper()
    subtotal = float(order.get("subtotal", 49.9))
    try:
        total = load_pricing().order_total(subtotal, country)
        if random.random() < float(settings.get("checkout_error_rate", 0.0)):
            raise RuntimeError("configured synthetic error")
    except Exception as exc:  # noqa: BLE001 - every pricing failure is a failed checkout
        DURATION.observe(time.perf_counter() - started)
        REQUESTS.labels(status="error").inc()
        tb = exc.__traceback__
        while tb and tb.tb_next:
            tb = tb.tb_next
        where = f"{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}" if tb else "unknown"
        # One line, greppable: status, exception, failing source line and the order's market.
        LOGGER.error("checkout failed status 503 %s: %s (pricing.py %s) country=%s", type(exc).__name__, exc, where, country)
        raise HTTPException(status_code=503, detail="Checkout temporarily unavailable") from exc
    DURATION.observe(time.perf_counter() - started)
    REQUESTS.labels(status="ok").inc()
    return {"status": "accepted", "order_id": str(order.get("order_id", "demo-order")), "total": f"{total:.2f}"}


@app.get("/metrics")
def metrics() -> Response:
    """Expose Prometheus counters and latency histogram."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
