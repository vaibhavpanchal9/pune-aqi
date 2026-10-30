# Data quality — 30 Oct 2026

Produced by `python quality_report.py` (default station: Panchawati_Pashan, 12238693). Every number
in the policies in `decisions.md` points at a table here. Re-run after any change to the ingest.

## Headline numbers
1. Pashan is missing 1,354 of 14,792 hours (9.2%). 685 of those hours (51%) sit in 8 holes of a day
   or more; 380 (28%) in 33 holes of 6–23 h; 87 in 25 holes of 3–5 h; 202 (15%) in 163 gaps of 1–2 h.
2. Exact zeros: 2,000+ across stations, 83 at Pashan (0.6%). They occur in flat runs of identical
   values (section D), i.e. a stuck instrument, not clean air. Negatives: 8, all at Park Street Wakad.
   Values ≥ 985 (instrument ceiling 1000): 5 in the whole table, none at Pashan.
3. Network-wide outages: 42 days with fewer than half of the possible readings, 15 of them with
   zero readings from any station: 9–10 Apr 2025, 11–19 Jan 2026, 24 Jun 2026, 24–26 Oct 2026.

## A. Gap lengths at Pashan
(table A)

## B. Missing hours per month at Pashan
(table B)
Worst months: Jan 2026 33.1%, Apr 2025 28.2%, Oct 2026 19.6%, Feb 2026 14.6%, Aug 2026 13.6%.
All but one are network-wide events (section F); the rest of the months lose 1.5–11%.

## C. Impossible and suspicious values, per station
(table C)
- Negative values exist only at Park Street Wakad (8).
- Zeros everywhere; Transport Nagar-Nigdi has 527, Revenue Colony 256, Mhada Colony 202. Pashan 83.
- Ceiling values (≥ 985): Gavalinagar 2, Bhumkar Nagar 1, Dhankawadi 1, Katraj 1.
- Spikes (> 4× both neighbours): Thergaon 16, Gavalinagar 10, Katraj 6; Pashan 0.
- Dropouts (< ¼ of both neighbours): Thergaon 23, Park Street 20, Gavalinagar 17; Pashan 5
  (one is 2026-02-03 07:30: 90.3 → 13.0 → 52.1).

## D. Stuck sensors (runs of 6+ identical consecutive values)
(table D)
- Revenue Colony-Shivajinagar: one run of 191 hours at 225.1 µg/m³ — eight days of a frozen high
  reading. Its station average (57.5, the highest) is partly this.
- Hadapsar: 402 hours in flat runs, longest 121 h at ~10.6. Nigdi: 376 hours, all at 0.0.
- Pashan: 6 runs, 72 hours, all at 0.0 — covered by the zero rule.

## E. Timestamp alignment
(table E) — all 146,742 rows on minute 30 UTC (CPCB's IST hours). No off-grid readings.

## F. Network-wide outage days
(table F)
Episodes with zero readings from every station: 9–10 Apr 2025 · 11–19 Jan 2026 · 24 Jun 2026 ·
24–26 Oct 2026. Partial days (10–12 stations, under half the readings) cluster around each episode.
These cannot be fixed on our side; they are listed so the README's "where it loses" is honest.

## What Step 6 does with this
See `decisions.md`, entries dated 2026-10-30: the value policy (what becomes NULL) and the gap
policy (what gets filled, what gets excluded). Expected effect at Pashan: ~88 readings (0.65%)
become NULL; ~250 missing hours get forward-filled; ~1,100 hours stay missing and are excluded.