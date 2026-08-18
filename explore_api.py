"""Day 1, tasks 4-6. Find out what actually exists near Pune.

Run it three ways:

    python explore_api.py --raw          # task 4: dump the raw JSON
    python explore_api.py                # task 5: one tidy line per station
    python explore_api.py --markdown     # task 6: the table for docs/data_sources.md

Nothing here writes to the database. This script only looks.
"""

import json
import argparse

from openaq_client import get_pune_locations, OpenAQError
from transform import flatten_locations, summarise_locations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="store_true", help="print raw JSON (task 4)")
    ap.add_argument("--markdown", action="store_true", help="print a markdown table (task 6)")
    ap.add_argument("--all-parameters", action="store_true",
                    help="include stations that don't measure PM2.5")
    ap.add_argument("--save-fixture", metavar="PATH",
                    help="save the raw response for use in tests")
    args = ap.parse_args()

    try:
        payload = get_pune_locations(
            parameters_id=None if args.all_parameters else 2
        )
    except OpenAQError as exc:
        print(f"\nAPI call failed:\n  {exc}\n")
        raise SystemExit(1)

    if args.save_fixture:
        with open(args.save_fixture, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"Saved raw response to {args.save_fixture}")

    if args.raw:
        print(json.dumps(payload, indent=2)[:6000])
        print(f"\n... meta says found={payload.get('meta', {}).get('found')}")
        return

    locations = flatten_locations(payload)
    print(f"\nFound {len(locations)} stations within 25km of Pune.\n")

    if args.markdown:
        rows = summarise_locations(locations)
        print("| ID | Station | Provider | Reference monitor | Parameters | First data | Last data | Days stale |")
        print("|---|---|---|---|---|---|---|---|")
        for r in rows:
            print(
                f"| {r['location_id']} | {r['name']} | {r['provider']} | "
                f"{'yes' if r['is_monitor'] else 'NO - low-cost'} | "
                f"{', '.join(r['parameters'])} | {r['first_data']} | "
                f"{r['last_data']} | {r['days_stale']} |"
            )
        print("\nPaste the above into docs/data_sources.md.")
        return

    # Default view: one readable block per station.
    for loc in locations:
        params = ", ".join(sorted({s["parameter"] for s in loc["sensors"] if s["parameter"]}))
        print(f"[{loc['location_id']:>7}] {loc['name']}")
        print(f"          provider : {loc['provider']}")
        print(f"          monitor  : {'reference grade' if loc['is_monitor'] else 'LOW-COST SENSOR'}")
        print(f"          coords   : {loc['latitude']}, {loc['longitude']}")
        print(f"          params   : {params}")
        print(f"          data from: {loc['datetime_first']}  to  {loc['datetime_last']}")
        for s in loc["sensors"]:
            print(f"            sensor {s['sensor_id']:>8}  {s['parameter']} ({s['units']})")
        print()

    total_sensors = sum(len(l["sensors"]) for l in locations)
    print(f"{len(locations)} stations, {total_sensors} sensors.")
    print("\nWrite down the sensor_id of the station with the longest history "
          "and the most recent data. That is your primary station for Week 2.")


if __name__ == "__main__":
    main()
