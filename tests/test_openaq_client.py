"""Tests for the OpenAQ client: what it retries, what it refuses to retry, and how it pages.

    pytest tests/test_openaq_client.py -v

No internet and no waiting: requests.get is replaced by a script of answers, and time.sleep by a
list that records how long the client WOULD have slept. So the retry rules can be read off exactly.
"""

from types import SimpleNamespace

import pytest
import requests

import openaq_client as oc


class FakeResponse:
    def __init__(self, status, payload=None, headers=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture
def api(monkeypatch):
    """`script` holds the answers to give, in order (a response, or an exception to raise)."""
    calls, sleeps, script = [], [], []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(SimpleNamespace(url=url, headers=headers, params=params, timeout=timeout))
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(oc.requests, "get", fake_get)
    monkeypatch.setattr(oc.time, "sleep", sleeps.append)
    monkeypatch.setattr(oc, "API_KEY", "test-key")
    return SimpleNamespace(calls=calls, sleeps=sleeps, script=script)


# ---------------------------------------------------------------- one request
def test_a_good_answer_is_returned_with_the_key_in_the_header_and_a_timeout(api):
    api.script.append(FakeResponse(200, {"results": [1, 2]}))
    assert oc._get("/locations", {"limit": 5}) == {"results": [1, 2]}
    call = api.calls[0]
    assert call.url == "https://api.openaq.org/v3/locations"
    assert call.headers == {"X-API-Key": "test-key"}          # a header, not a query parameter
    assert call.params == {"limit": 5} and call.timeout == oc.TIMEOUT
    assert api.sleeps == []


def test_rate_limited_waits_as_long_as_the_server_says_then_tries_again(api):
    api.script += [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, {"ok": True})]
    assert oc._get("/x") == {"ok": True}
    assert api.sleeps == [7] and len(api.calls) == 2


def test_rate_limited_without_a_hint_backs_off_by_itself(api):
    api.script += [FakeResponse(429), FakeResponse(200, {"ok": True})]
    oc._get("/x")
    assert api.sleeps == [2]


def test_server_errors_are_retried_with_doubling_waits(api):
    api.script += [FakeResponse(500), FakeResponse(502), FakeResponse(200, {"ok": True})]
    assert oc._get("/x") == {"ok": True}
    assert api.sleeps == [2, 4] and len(api.calls) == 3


def test_it_gives_up_after_three_attempts_and_says_why(api):
    api.script += [FakeResponse(503)] * 3
    with pytest.raises(oc.OpenAQError, match="Gave up on /x after 3 attempts. Last: 503 server error"):
        oc._get("/x")
    assert api.sleeps == [2, 4, 8] and len(api.calls) == oc.MAX_RETRIES


def test_a_network_failure_is_retried(api):
    api.script += [requests.ConnectionError("no route"), requests.Timeout("slow"), FakeResponse(200, {"ok": 1})]
    assert oc._get("/x") == {"ok": 1}
    assert api.sleeps == [2, 4]


@pytest.mark.parametrize("status, words", [(401, "401 Unauthorized"), (410, "410 Gone"), (422, "422 Unprocessable")])
def test_a_wrong_request_is_not_retried(api, status, words):
    """401, 410 and 422 mean OUR request is wrong. Sending it three more times will not make it right."""
    api.script.append(FakeResponse(status))
    with pytest.raises(oc.OpenAQError, match=words):
        oc._get("/x", {"radius": 99999})
    assert len(api.calls) == 1 and api.sleeps == []


def test_any_other_error_is_reported_with_its_status_and_text(api):
    api.script.append(FakeResponse(404, text="no such sensor"))
    with pytest.raises(oc.OpenAQError, match="HTTP 404: no such sensor"):
        oc._get("/sensors/1/hours")
    assert len(api.calls) == 1


def test_without_a_key_nothing_is_sent(api, monkeypatch):
    monkeypatch.setattr(oc, "API_KEY", None)
    with pytest.raises(oc.OpenAQError, match="OPENAQ_KEY is not set"):
        oc._get("/locations")
    assert api.calls == []


# ---------------------------------------------------------------- the questions it asks
def test_stations_are_asked_for_as_latitude_then_longitude(api):
    """Reversing them does not error; it quietly returns stations somewhere else on Earth."""
    api.script += [FakeResponse(200, {}), FakeResponse(200, {})]
    oc.get_pune_locations()
    assert api.calls[0].params == {"coordinates": "18.5204,73.8567", "radius": 25000, "limit": 1000,
                                   "parameters_id": 2}
    oc.get_pune_locations(parameters_id=None)
    assert "parameters_id" not in api.calls[1].params


def test_hours_are_asked_for_by_sensor_with_the_date_window(api):
    api.script.append(FakeResponse(200, {"results": []}))
    oc.get_sensor_hours(12238693, "2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", limit=100, page=3)
    call = api.calls[0]
    assert call.url.endswith("/sensors/12238693/hours")
    assert call.params == {"limit": 100, "page": 3, "datetime_from": "2026-11-01T00:00:00Z",
                           "datetime_to": "2026-11-02T00:00:00Z"}


def test_station_detail_is_asked_for_by_station_id(api):
    api.script += [FakeResponse(200, {}), FakeResponse(200, {})]
    oc.get_location_sensors(7)
    oc.get_location_latest(7)
    assert [c.url for c in api.calls] == [f"{oc.BASE_URL}/locations/7/sensors", f"{oc.BASE_URL}/locations/7/latest"]


# ---------------------------------------------------------------- paging
def pages_of(monkeypatch, sizes):
    """Make get_sensor_hours answer page k with sizes[k-1] results (nothing after the last)."""
    asked = []

    def fake(sensor_id, datetime_from=None, datetime_to=None, limit=1000, page=1):
        asked.append(page)
        n = sizes[page - 1] if page <= len(sizes) else 0
        return {"results": [{"page": page, "i": i} for i in range(n)]}

    monkeypatch.setattr(oc, "get_sensor_hours", fake)
    return asked


def test_every_page_is_read_until_a_short_one(api, monkeypatch):
    asked = pages_of(monkeypatch, [2, 2, 1])
    payloads = list(oc.iter_sensor_hours(1, limit=2))
    assert [len(p["results"]) for p in payloads] == [2, 2, 1]        # reading only page 1 would lose 3 of 5
    assert asked == [1, 2, 3]
    assert api.sleeps == [oc.SLEEP_BETWEEN_CALLS] * 2                # polite pause between pages only


def test_a_full_last_page_costs_one_more_request_and_then_stops(api, monkeypatch):
    asked = pages_of(monkeypatch, [2, 2])
    assert len(list(oc.iter_sensor_hours(1, limit=2))) == 2
    assert asked == [1, 2, 3]                                         # page 3 is empty: that is how it knows


def test_no_data_yields_nothing(api, monkeypatch):
    pages_of(monkeypatch, [])
    assert list(oc.iter_sensor_hours(1)) == []
