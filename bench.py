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

Two clocks. The times above are end to end: server + network, and the network depends on where this is
run (measured from Pune: 180 ms per request on one connection, 2 seconds on another, same server, same
hour). The "server" columns come from the Server-Timing header the API adds to every answer: the
milliseconds the server itself spent. That part does not change with the visitor's connection.
"""

import argparse
import csv
import math
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ENDPOINTS = ["/", "/health", "/forecast", "/stats"]


def server_ms(headers):
    """The server's own time from a Server-Timing header like 'app;dur=3.2'; None if absent."""
    value = headers.get("Server-Timing") if headers is not None else None
    if not value or "dur=" not in value:
        return None
    try:
        return float(value.split("dur=")[1].split(",")[0].split(";")[0])
    except ValueError:
        return None


def timed_get(url, timeout=120):
    """(end-to-end ms, HTTP status, server ms or None). A refused or timed-out request has status 0."""
    req = urllib.request.Request(url, headers={"User-Agent": "pune-aqi-bench"})
    start = time.perf_counter()
    headers = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            status, headers = r.status, r.headers
    except urllib.error.HTTPError as e:
        status, headers = e.code, e.headers
    except Exception:
        status = 0
    return (time.perf_counter() - start) * 1000, status, server_ms(headers)


def percentile(values, q):
    """Nearest rank: the smallest value that has at least a share q of the values at or below it.

    The rank is rounded UP. (Until 19 Nov 2026 this used round(), and Python rounds 28.5 down to 28:
    with the default 30 requests, "p95" was the 28th value of 30, which is the 93rd percentile.)
    """
    ordered = sorted(values)
    rank = math.ceil(q * len(ordered) - 1e-9)        # minus a hair: 0.07 * 100 is 7.000000000000001
    return ordered[min(len(ordered) - 1, max(0, rank - 1))]


def measure(base, path, n):
    first_ms, first_status, first_server = timed_get(base + path)
    rest = [timed_get(base + path) for _ in range(n)]
    times = [ms for ms, status, _ in rest if status == 200]
    server = [srv for _, status, srv in rest if status == 200 and srv is not None]
    return {
        "endpoint": path,
        "first_ms": round(first_ms),
        "first_status": first_status,
        "ok": len(times),
        "n": n,
        "p50_ms": round(statistics.median(times)) if times else None,
        "p95_ms": round(percentile(times, 0.95)) if times else None,
        "max_ms": round(max(times)) if times else None,
        "first_server_ms": None if first_server is None else round(first_server, 1),
        "server_p50_ms": round(statistics.median(server), 1) if server else None,
        "server_p95_ms": round(percentile(server, 0.95), 1) if server else None,
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
    print(f"{'':<10} {'------- end to end (server + network) -------':^44}   {'------ server only ------':^27}")
    print(f"{'endpoint':<10} {'first':>10} {'p50':>10} {'p95':>10} {'max':>10}   {'first':>8} {'p50':>8} {'p95':>8}   ok")
    rows = []
    for path in ENDPOINTS:
        r = measure(base, path, args.n)
        rows.append({**r, "url": base, "measured_at": stamp.isoformat(timespec="seconds")})
        fmt = lambda v: "-" if v is None else f"{v:,} ms"
        print(f"{path:<10} {fmt(r['first_ms']):>10} {fmt(r['p50_ms']):>10} {fmt(r['p95_ms']):>10} {fmt(r['max_ms']):>10}   "
              f"{fmt(r['first_server_ms']):>8} {fmt(r['server_p50_ms']):>8} {fmt(r['server_p95_ms']):>8}   "
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
