# Data inventory — 27 Oct 2026

Source: OpenAQ v3, `/sensors/{id}/hours`, PM2.5 (parameters_id=2), 13 live reference-grade
CPCB/MPCB/IITM stations within 25 km of Pune. Backfilled 2025-02-18 → 2026-10-23 with
`python backfill.py`; kept current by the GitHub Actions job every 2 h. Every number below is
the output of `python runsql.py sql/00_inventory.sql` on this date.

## Totals
(paste table 1)

## Per station
(paste table 2)

## Per month
(paste table 3)

## What this says
(two or three sentences in your own words: best and worst station and their coverage; which
months look wrong; the upstream gap since 2026-10-23 14:30 UTC)

## Primary station
Sensor 12238693, Panchawati_Pashan, Pune – IITM: live, longest history, highest coverage
(91.4% of hours present). Backup: 12236443, Mhada Colony (87.6%).