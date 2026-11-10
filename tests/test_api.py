"""Step 10 tests for the API: status codes, shapes, and the arithmetic the route layer adds.

    pytest tests/test_api.py -v

No database: service.health / forecast / stats are replaced with fakes, so these tests check the
HTTP layer -- validation, 404 vs 422 vs 200, the response models, lead_hours and the IST label.
The SQL behind the fakes is exercised by `python service.py` against the real database.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app as app_module
import service

NOW = datetime.now(timezone.utc)


def fake_forecast(sensor_id=service.SENSOR):
    rows = [{"target_time": NOW + timedelta(hours=h), "point": 40.0 + h, "lower": 30.0 + h,
             "upper": 55.0 + h, "issued_at": NOW - timedelta(hours=2)} for h in (3, 1, 2)]   # unsorted on purpose
    return {"sensor_id": sensor_id, "station": "Test station", "model_version": "v1", "horizon_hours": 24,
            "band": "80% interval (residual_ratio)", "data_as_of": NOW - timedelta(hours=22), "forecasts": rows}


def fake_health():
    return {"status": "ok", "checked_at": NOW,
            "pipeline": {"last_ok_run": NOW, "hours_since_ok_run": 0.3, "runs_last_24h": 27, "stale_after_hours": 12},
            "data": {"sensor_id": service.SENSOR, "newest_reading": NOW, "hours_since_newest": 3.1,
                     "upstream_lag_after_hours": 9},
            "forecasts": {"model_version": "v1", "hours_ahead_on_file": 13, "newest_target": NOW, "last_issued": NOW}}


def fake_stats(sensor_id=service.SENSOR):
    return {"sensor_id": sensor_id, "model_version": "v1",
            "live": {"scored_hours": 10, "mae": 7.5, "bias": -1.2, "coverage_80": 0.8, "mean_width": 30.1,
                     "persistence_mae": 9.9, "first_scored": NOW, "last_scored": NOW, "note": "x"},
            "lead_time": {"forecasts_issued": 13, "mean_issue_delay_hours": 12.0, "mean_lead_hours": 12.0,
                          "min_lead_hours": 0.7},
            "availability_7d": {"hours_with_forecast": 10, "hours": 168, "share": 0.06},
            "walk_forward": {"ridge_mae": 8.657, "persistence_mae": 9.357, "folds": 6, "source": "x"},
            "trained_on": {"rows": 10186, "from": "2025-02-25", "through": "2026-11-07"}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(service, "forecast", fake_forecast)
    monkeypatch.setattr(service, "health", fake_health)
    monkeypatch.setattr(service, "stats", fake_stats)
    return TestClient(app_module.app)


def test_root_points_at_the_docs_and_endpoints(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["docs"] == "/docs" and "/health" in r.json()["endpoints"]


def test_health_is_200_with_the_three_sections(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body) >= {"status", "checked_at", "pipeline", "data", "forecasts"}
    assert body["pipeline"]["runs_last_24h"] == 27


def test_forecast_default_sensor_is_200_with_rows_and_lead_hours(client):
    r = client.get("/forecast")
    assert r.status_code == 200
    body = r.json()
    assert body["sensor_id"] == service.SENSOR and body["station"] == "Test station"
    assert [row["point"] for row in body["forecasts"]] == [43.0, 41.0, 42.0]      # order as served
    for row in body["forecasts"]:
        assert row["lower"] <= row["point"] <= row["upper"]
        assert row["target_time_ist"].endswith("IST")
    leads = [row["lead_hours"] for row in body["forecasts"]]
    assert all(abs(lead - h) < 0.1 for lead, h in zip(leads, (3, 1, 2)))         # computed from now


def test_forecast_for_a_sensor_without_a_model_is_404(client):
    r = client.get("/forecast?sensor_id=999")
    assert r.status_code == 404
    assert "no model" in r.json()["detail"]


def test_forecast_with_a_non_numeric_sensor_is_422(client):
    assert client.get("/forecast?sensor_id=abc").status_code == 422


def test_forecast_with_nothing_on_file_is_200_and_empty(client, monkeypatch):
    def empty(sensor_id=service.SENSOR):
        return {**fake_forecast(sensor_id), "forecasts": [], "data_as_of": None}
    monkeypatch.setattr(service, "forecast", empty)
    r = client.get("/forecast")
    assert r.status_code == 200 and r.json()["forecasts"] == [] and r.json()["data_as_of"] is None


def test_stats_shows_live_next_to_walk_forward(client):
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["live"]["mae"] == 7.5 and body["walk_forward"]["ridge_mae"] == 8.657
    assert body["availability_7d"]["hours"] == 168


def test_docs_are_generated(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) >= {"/health", "/forecast", "/stats"}
