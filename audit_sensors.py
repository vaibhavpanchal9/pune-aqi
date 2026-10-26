"""Day 1, task 6b. Which PM2.5 sensor at each station is actually alive?

    python audit_sensors.py

Several Pune stations expose two PM2.5 sensors. That happens because OpenAQ
onboarded a second CPCB feed in Feb 2025 that overlaps the older one. If you
poll both, you collect two readings per hour for one physical location. The
database won't object -- different sensor_id means a different series -- so
you'd only notice in Week 2 when your feature rows came out doubled.

The location-level dates you saw in explore_api.py are the union across ALL
sensors at that station, so they can't tell the twins apart. Per-sensor dates
can. That's what this script fetches.

It decides nothing. It prints the evidence; you pick the station.
"""

from datetime import datetime, timezone

from openaq_client import _get, get_pune_locations, OpenAQError
from transform import flatten_locations, _parse_dt

STALE_DAYS = 7


def _fresh(sensor):
    """Is this sensor still reporting?

    Written as an explicit None check, NOT as `stale_days or 999`.
    A sensor that reported an hour ago has stale_days == 0, and 0 is falsy
    in Python, so `0 or 999` returns 999 and the freshest sensor in the set
    gets labelled dead. That exact bug shipped in the first version of this
    file.
    """
    d = sensor["stale_days"]
    return d is not None and d <= STALE_DAYS


def get_location_sensors(location_id):
    """GET /v3/locations/{id}/sensors -- per-sensor dates and coverage."""
    return _get(f"/locations/{location_id}/sensors")


def pm25_sensors_for(location_id):
    payload = get_location_sensors(location_id)
    now = datetime.now(timezone.utc)
    rows = []
    for s in payload.get("results", []):
        param = (s.get("parameter") or {}).get("name")
        if param != "pm25":
            continue
        first = _parse_dt(s.get("datetimeFirst"))
        last = _parse_dt(s.get("datetimeLast"))
        summary = s.get("summary") or {}
        coverage = s.get("coverage") or {}
        rows.append({
            "sensor_id": s["id"],
            "first": first,
            "last": last,
            "stale_days": (now - last).days if last else None,
            "years": round((last - first).days / 365.25, 1) if first and last else None,
            "avg": summary.get("avg"),
            "observed": coverage.get("observedCount"),
            "pct_complete": coverage.get("percentComplete"),
        })
    rows.sort(key=lambda r: (r["stale_days"] is None, r["stale_days"] or 0))
    return rows


def main():
    print("Fetching per-sensor detail. ~19 requests, please wait.\n")
    locations = flatten_locations(get_pune_locations(parameters_id=2))

    report = []
    for loc in locations:
        try:
            sensors = pm25_sensors_for(loc["location_id"])
        except OpenAQError as exc:
            print(f"  ! {loc['location_id']} {loc['name']}: {exc}")
            continue
        if sensors:
            report.append((loc, sensors))

    live, dead, twins = [], [], []
    for loc, sensors in report:
        alive = [s for s in sensors
                 if s["stale_days"] is not None and s["stale_days"] <= STALE_DAYS]
        (live if alive else dead).append((loc, sensors))
        if len(sensors) > 1:
            twins.append((loc, sensors))

    print("=" * 78)
    print(f"  LIVE STATIONS  (PM2.5 reading within {STALE_DAYS} days)")
    print("=" * 78)
    header = f"  {'sensor':>10}  {'from':>10}  {'to':>10}  {'yrs':>5}  {'stale':>5}  {'avg':>6}  {'obs':>8}"
    for loc, sensors in sorted(
            live, key=lambda x: -(max((s["years"] or 0) for s in x[1]))):
        print(f"\n[{loc['location_id']}] {loc['name']}")
        print(header)
        for s in sensors:
            mark = "  <-- LIVE" if _fresh(s) else "  (dead)"
            print(f"  {s['sensor_id']:>10}  {str(s['first'])[:10]:>10}  "
                  f"{str(s['last'])[:10]:>10}  {s['years'] or 0:>5}  "
                  f"{s['stale_days'] if s['stale_days'] is not None else '?':>5}  "
                  f"{round(s['avg'],1) if s['avg'] else '?':>6}  "
                  f"{s['observed'] or '?':>8}{mark}")

    print("\n" + "=" * 78)
    print("  STATIONS WITH MORE THAN ONE PM2.5 SENSOR")
    print("=" * 78)
    if not twins:
        print("  none")
    for loc, sensors in twins:
        keep = [s for s in sensors if _fresh(s)]
        drop = [s for s in sensors if not _fresh(s)]
        print(f"\n[{loc['location_id']}] {loc['name']}")
        print(f"    live  : {[s['sensor_id'] for s in keep] or 'NONE'}")
        print(f"    stale : {[s['sensor_id'] for s in drop] or 'none'}")
        if len(keep) > 1:
            print("    ^^ TWO LIVE SENSORS. Compare their averages above and "
                  "decide which to keep. Do not ingest both.")

    print("\n" + "=" * 78)
    print(f"  DEAD STATIONS: {len(dead)}")
    print("=" * 78)
    for loc, sensors in dead:
        newest = min((s["stale_days"] if s["stale_days"] is not None else 99999) for s in sensors)
        print(f"  [{loc['location_id']:>8}] {loc['name'][:48]:<48} "
              f"silent {newest} days")

    print(f"\n{len(live)} live, {len(dead)} dead, {len(twins)} with duplicate sensors.")
    print("\nPick your primary station on: longest history AND still live AND "
          "high observed count.\nWrite the sensor_id and your reason into "
          "docs/decisions.md.")


if __name__ == "__main__":
    main()
