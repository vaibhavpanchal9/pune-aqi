"""Turn OpenAQ v3 JSON into flat rows.

Everything in this file is a pure function: JSON in, plain Python out.
No network, no database. That is deliberate — it means every line here
can be tested against a saved fixture in under a second, which is why
tests/test_transform.py exists.

Keeping the parsing separate from the fetching is the single most useful
structural decision in this project. When the API changes shape (and it
will — v2 was killed in January 2025), only this file breaks.
"""

from datetime import datetime, timezone


def _parse_dt(node):
    """Pull a UTC datetime out of OpenAQ's {"utc": ..., "local": ...} shape.

    Returns None if the node is missing or empty.

    OpenAQ gives every timestamp twice: once in UTC, once in the station's
    local time. We keep ONLY the UTC one. Storing local times in a database
    is how you end up with two 2:30am readings every October.
    """
    if not node:
        return None
    raw = node.get("utc") if isinstance(node, dict) else node
    if not raw:
        return None
    # Python's fromisoformat didn't accept a trailing "Z" before 3.11.
    # Swapping it for "+00:00" works on every version.
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def flatten_locations(payload):
    """Turn GET /v3/locations into a list of station dicts.

    Each station dict carries a nested "sensors" list, because that is the
    shape the API returns and the shape the database expects.
    """
    out = []
    for loc in payload.get("results", []):
        coords = loc.get("coordinates") or {}
        sensors = []
        for s in loc.get("sensors", []):
            param = s.get("parameter") or {}
            sensors.append({
                "sensor_id": s["id"],
                "parameter": param.get("name"),
                "units": param.get("units"),
                "display_name": param.get("displayName"),
            })
        out.append({
            "location_id": loc["id"],
            "name": loc.get("name"),
            "locality": loc.get("locality"),
            "timezone": loc.get("timezone"),
            "latitude": coords.get("latitude"),
            "longitude": coords.get("longitude"),
            "provider": (loc.get("provider") or {}).get("name"),
            "is_mobile": loc.get("isMobile"),
            "is_monitor": loc.get("isMonitor"),
            "datetime_first": _parse_dt(loc.get("datetimeFirst")),
            "datetime_last": _parse_dt(loc.get("datetimeLast")),
            "sensors": sensors,
        })
    return out


def flatten_hours(payload, sensor_id, source="openaq"):
    """Turn GET /v3/sensors/{id}/hours into measurement rows.

    Rows with a null value are dropped. A sensor that was offline for an
    hour reports the hour with no value rather than omitting it, and a null
    is not a zero — writing it as 0 would be inventing a reading of
    perfectly clean air, which is exactly backwards.
    """
    rows = []
    for m in payload.get("results", []):
        value = m.get("value")
        if value is None:
            continue

        # The hourly endpoint labels each row with "period", which carries
        # the start and end of the hour. Fall back to "datetime" because
        # the raw measurements endpoint uses that instead, and this same
        # function then works for both.
        period = m.get("period") or {}
        measured_at = _parse_dt(period.get("datetimeFrom")) or _parse_dt(m.get("datetime"))
        if measured_at is None:
            continue

        rows.append({
            "sensor_id": sensor_id,
            "measured_at": measured_at,
            "value": float(value),
            "source": source,
        })
    return rows


def flatten_latest(payload, source="openaq"):
    """Turn GET /v3/locations/{id}/latest into measurement rows.

    Used for the quick hourly poll. Unlike flatten_hours, the sensor id
    arrives inside each record rather than being passed in.
    """
    rows = []
    for m in payload.get("results", []):
        value = m.get("value")
        sensor_id = m.get("sensorsId")
        measured_at = _parse_dt(m.get("datetime"))
        if value is None or sensor_id is None or measured_at is None:
            continue
        rows.append({
            "sensor_id": sensor_id,
            "measured_at": measured_at,
            "value": float(value),
            "source": source,
        })
    return rows


def flatten_location_sensors(payload, location_id, stale_days=7):
    """Turn GET /v3/locations/{id}/sensors into sensor rows with real dates.

    is_active is decided here, once, using an explicit None check.
    Do not write this as `stale or 999` -- a sensor that reported this hour
    has stale == 0, and 0 is falsy in Python, so the freshest sensor in the
    set would be marked dead. That bug shipped in audit_sensors.py v1.
    """
    now = datetime.now(timezone.utc)
    rows = []
    for s in payload.get("results", []):
        param = (s.get("parameter") or {}).get("name")
        if not param:
            continue
        last = _parse_dt(s.get("datetimeLast"))
        summary = s.get("summary") or {}
        coverage = s.get("coverage") or {}
        stale = (now - last).days if last is not None else None
        rows.append({
            "sensor_id": s["id"],
            "location_id": location_id,
            "parameter": param,
            "units": (s.get("parameter") or {}).get("units"),
            "datetime_first": _parse_dt(s.get("datetimeFirst")),
            "datetime_last": last,
            "observed_count": coverage.get("observedCount"),
            "avg_value": summary.get("avg"),
            "is_active": stale is not None and stale <= stale_days,
        })
    return rows


def summarise_locations(locations, parameter="pm25"):
    """Build the table that goes in docs/data_sources.md (Day 1, task 6).

    Returns a list of dicts, one per station, sorted so the stations that
    actually report your target parameter come first.
    """
    now = datetime.now(timezone.utc)
    summary = []
    for loc in locations:
        params = sorted({s["parameter"] for s in loc["sensors"] if s["parameter"]})
        has_target = parameter in params
        last = loc["datetime_last"]
        days_stale = (now - last).days if last else None
        summary.append({
            "location_id": loc["location_id"],
            "name": loc["name"],
            "provider": loc["provider"],
            "is_monitor": loc["is_monitor"],
            "parameters": params,
            f"has_{parameter}": has_target,
            "first_data": loc["datetime_first"].date() if loc["datetime_first"] else None,
            "last_data": last.date() if last else None,
            "days_stale": days_stale,
        })
    summary.sort(key=lambda r: (not r[f"has_{parameter}"], r["days_stale"] is None,
                                r["days_stale"] or 0))
    return summary
