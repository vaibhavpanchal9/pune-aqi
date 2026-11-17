"""Step 12. Measure how fast the API answers, from wherever this is run.

    python bench.py --url https://pune-aqi-api.onrender.com          # 30 requests per endpoint
    python bench.py --url http://127.0.0.1:8000 --n 50 --out results/latency_local.csv

For each endpoint it reports:
    first   the very first request. On a free host that sleeps when idle this includes waking up
            (about a minute on Render); otherwise it is the one request that had to ask the database
    p50     the middle request of the rest: what a visitor normally waits
    p95     19 requests in 20 are faster than this
    max     the slowest of the rest

Every request opens a new connection (TLS handshake included), as a first-time visitor's would.
The API reuses an answer for 30-300 seconds (service.CACHE_SECONDS), so most of "the rest" are served
from memory; "first" is the honest number for an uncached answer. Standard library only.
"""

import argparse
import csv
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINTS = ["/", "/health", "/forecast", "/stats"]


def timed_get(url, timeout=120):
    """(milliseconds, HTTP status). A refused or timed-out request is reported as status 0."""
    req = urllib.request.Request(url, headers={"User-Agent": "pune-aqi-bench"})
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        status = 0
    return (time.perf_counter() - start) * 1000, status


def percentile(values, q):
    """The value below which a share q of the sorted values falls (nearest rank)."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * len(ordered)) - 1))]


def measure(base, path, n):
    first_ms, first_status = timed_get(base + path)
    rest = [timed_get(base + path) for _ in range(n)]
    times = [ms for ms, status in rest if status == 200]
    return {
        "endpoint": path,
        "first_ms": round(first_ms),
        "first_status": first_status,
        "ok": len(times),
        "n": n,
        "p50_ms": round(statistics.median(times)) if times else None,
        "p95_ms": round(percentile(times, 0.95)) if times else None,
        "max_ms": round(max(times)) if times else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="base address, e.g. https://pune-aqi-api.onrender.com")
    ap.add_argument("--n", type=int, default=30, help="requests per endpoint after the first")
    ap.add_argument("--out", default=None, help="default: results/latency_<date>.csv")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    stamp = datetime.now(timezone.utc)
    print(f"{base} · {args.n} requests per endpoint after the first · {stamp:%Y-%m-%d %H:%M} UTC\n")
    print(f"{'endpoint':<10} {'first':>9} {'p50':>7} {'p95':>7} {'max':>7}   ok")
    rows = []
    for path in ENDPOINTS:
        r = measure(base, path, args.n)
        rows.append({**r, "url": base, "measured_at": stamp.isoformat(timespec="seconds")})
        fmt = lambda v: "-" if v is None else f"{v:,} ms"
        print(f"{path:<10} {fmt(r['first_ms']):>9} {fmt(r['p50_ms']):>7} {fmt(r['p95_ms']):>7} {fmt(r['max_ms']):>7}   "
              f"{r['ok']}/{r['n']}" + ("" if r["first_status"] == 200 else f"   first request: HTTP {r['first_status']}"))

    out = Path(args.out or f"results/latency_{stamp:%Y-%m-%d}.csv")
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
