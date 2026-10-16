"""Pricing behaviour that must hold before and after any fix."""

import json
import logging

from fastapi.testclient import TestClient

from app import main
from app import pricing


def test_supported_markets_are_priced_with_their_tax_rate():
    assert pricing.order_total(100, "US") == 107.0
    assert pricing.order_total(100, "GB") == 120.0
    assert pricing.order_total(100, "DE") == 119.0
    assert pricing.order_total(100, "FR") == 120.0


def test_checkout_failure_is_a_real_counted_error_with_a_greppable_log_line(tmp_path, monkeypatch, caplog):
    """A pricing exception becomes a 503, increments the error counter and logs status, exception, line, market."""
    broken = tmp_path / "pricing.py"
    broken.write_text("def order_total(subtotal, country):\n    return subtotal + None\n", encoding="utf-8")
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"demo_faults_enabled": True, "checkout_error_rate": 0.0}), encoding="utf-8")
    monkeypatch.setattr(main, "PRICING_PATH", broken)
    monkeypatch.setattr(main, "SETTINGS_PATH", config)
    client = TestClient(main.app)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        response = client.post("/checkout", json={"order_id": "o1", "country": "IN", "subtotal": 10})

    assert response.status_code == 503
    assert any("status 503 TypeError" in r.message and "country=IN" in r.message for r in caplog.records)
    assert 'checkout_requests_total{status="error"}' in client.get("/metrics").text


def test_a_changed_pricing_file_is_picked_up_without_a_restart(tmp_path, monkeypatch):
    """The merged fix goes live by replacing the file: no rebuild, no restart."""
    path = tmp_path / "pricing.py"
    path.write_text("def order_total(subtotal, country):\n    return 1.0\n", encoding="utf-8")
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"demo_faults_enabled": True, "checkout_error_rate": 0.0}), encoding="utf-8")
    monkeypatch.setattr(main, "PRICING_PATH", path)
    monkeypatch.setattr(main, "SETTINGS_PATH", config)
    client = TestClient(main.app)

    assert client.post("/checkout", json={"order_id": "a", "country": "IN"}).json()["total"] == "1.00"
    path.write_text("def order_total(subtotal, country):\n    return 2.0\n", encoding="utf-8")
    assert client.post("/checkout", json={"order_id": "b", "country": "IN"}).json()["total"] == "2.00"
