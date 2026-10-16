"""Smoke tests for the demo checkout API."""

import json

from fastapi.testclient import TestClient

from app import main


def test_checkout_succeeds_and_exports_metrics(tmp_path, monkeypatch):
    """Healthy checkout produces an accepted order and a Prometheus counter."""
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"demo_faults_enabled": True, "checkout_error_rate": 0.0}), encoding="utf-8")
    monkeypatch.setattr(main, "SETTINGS_PATH", config)
    monkeypatch.setattr(main, "_FAULT_INJECTED", False)
    client = TestClient(main.app)

    response = client.post("/checkout", json={"order_id": "order-1"})

    assert response.status_code == 200
    assert response.json()["order_id"] == "order-1"
    assert "checkout_requests_total" in client.get("/metrics").text


def test_fault_injection_can_be_disabled_by_approved_settings(tmp_path, monkeypatch):
    """Merged safe settings prevent demo fault injection and keep checkout healthy."""
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"demo_faults_enabled": False, "checkout_error_rate": 0.0}), encoding="utf-8")
    monkeypatch.setattr(main, "SETTINGS_PATH", config)
    monkeypatch.setattr(main, "_FAULT_INJECTED", False)
    client = TestClient(main.app)

    assert client.post("/demo/fault").status_code == 409
    assert client.post("/checkout", json={"order_id": "order-2"}).status_code == 200


def test_fault_injection_starts_traffic_and_recovery_stops_it(tmp_path, monkeypatch):
    """The fault button is the only trigger: it starts simulated shoppers, and recovery stops them."""
    started = []
    monkeypatch.setattr(main, "start_traffic", lambda: started.append(True))
    stopped = []
    monkeypatch.setattr(main, "stop_traffic", lambda: stopped.append(True))
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"demo_faults_enabled": True, "checkout_error_rate": 0.0}), encoding="utf-8")
    monkeypatch.setattr(main, "SETTINGS_PATH", config)
    monkeypatch.setattr(main, "_FAULT_INJECTED", False)
    client = TestClient(main.app)

    assert client.post("/demo/fault").status_code == 200
    assert started == [True]
    client.post("/demo/recover")
    assert stopped == [True]
