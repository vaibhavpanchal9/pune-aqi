# SQL notes — Step 4 (1/2), 28 Oct 2026

Every number below is from `python runsql.py sql/0N_*.sql` run against Neon on this date.

## Ideas used today (cheat-sheet)
- `SELECT … FROM … WHERE … ORDER BY … LIMIT` — choose columns, filter rows, sort, cut.
- `GROUP BY` collapses rows into groups; `count / avg / min / max` summarise each group.
- `HAVING` filters groups *after* they exist (WHERE can't see `count(*)`).
- `JOIN` keeps only rows with a match in both tables; `LEFT JOIN` keeps every row of the left table
  and fills the right side with NULL when there is no match.
- A filter on the right table of a LEFT JOIN belongs in `ON`, not `WHERE` — in WHERE it silently
  turns the LEFT JOIN back into a JOIN.
- `count(*)` counts rows; `count(column)` counts non-NULL values. That difference is how coverage works.
- `CASE WHEN … THEN … ELSE … END` is if/else inside a query; `avg(CASE WHEN cond THEN 1 ELSE 0 END)`
  is the share of rows where cond is true.
- `date_trunc('month', ts)`, `to_char(ts, 'YYYY-MM')`, `EXTRACT(HOUR FROM ts)`,
  `ts AT TIME ZONE 'Asia/Kolkata'` — time handling. Stored timestamps are UTC; convert before grouping by hour.
- `WITH name AS (…)` (a CTE) names a sub-result; `generate_series(start, end, interval '1 hour')`
  makes one row per hour; `CROSS JOIN` pairs every row of one side with every row of the other.
- `round(x::numeric, 1)` — one decimal (`::numeric` is a cast; `round` needs it for doubles).
- `sum(count(*)) OVER ()` — a window function: the total next to each group, no second query.

## 01 basics — look before you query
- Q1 Four tables. `measurements(sensor_id, measured_at timestamptz, value double, source, ingested_at)`;
  `sensors` holds every parameter a station has (pm25, no, o3, nox …) with `is_active`, `datetime_first/last`,
  `observed_count`; `locations` has name, lat/lon, provider; `ingestion_runs` has run_at, mode, status,
  rows_fetched/inserted, error_text.
- Q2 One row = one sensor, one hour. Timestamps are UTC and end in :30 because CPCB hours are IST hours
  (08:30 UTC = 14:00 IST). The value column is `value`, in µg/m³.
- Q3 `is_active` is true for `no`, `o3`, `nox` sensors too. Active ≠ PM2.5: always filter `parameter = 'pm25'` as well.
- Q4 measurements 146,193 · sensors 215 · locations 19 · ingestion_runs 31.
- Q5 Newest Pashan (12238693) reading: 2026-10-28 02:30 UTC (08:00 IST), 55.0.
- Q6 Oldest: 2025-02-18 19:30 UTC, 41.7. `DESC` → `ASC` is the only change.

## 02 GROUP BY
- Q7 Station averages run from 22.7 (SPPU, 12238005) to 57.5 (Revenue Colony, 12236463). Every station
  has a minimum of 0.0; Park Street Wakad has −19.9; maxima include 1000.0 twice and 1180.0.
  Negative PM2.5 is impossible and a flat 1000 looks like an instrument ceiling → Step 5.
- Q8 Pashan by month: May–Sep 2025 16–20, Dec 2025 70.1, Jan 2026 66.0, Feb 57.6, back to 17–19 by June.
  Strong yearly cycle — the basis of the climatology baseline.
- Q9 Pashan by hour of day (IST): worst 9–10 am (38.8), best 4 pm (22.8), flat ~31–32 overnight.
  Morning traffic + a cold trapped layer; afternoon heat mixes it away. This curve is the `hour` feature.
- Q10 Pashan months under 600 rows: 2025-02 (245, partial month), 2025-04 (517), 2026-01 (498),
  2026-02 (574), 2026-10 (514, partial + the 4-day outage).
- Q11 Ten highest readings: 1180 and 1090 at Gavalinagar (12237987) in May 2026; exactly 1000.0 at
  Bhumkar Nagar (May 2025) and Dhankawadi (Jan 2026); 997 at Katraj. Real or faults — Step 5 looks at the
  neighbouring hours before deciding.

## 03 JOIN
- Q12 Q7 with names via measurements → sensors → locations. Most polluted on average: Revenue
  Colony-Shivajinagar 57.5; cleanest: SPPU 22.7; Pashan 30.9 (9th of 13).
- Q13 Ten registered PM2.5 sensors have zero measurements. All `is_active = False`, last seen 2018–2025:
  the dead stations and the retired twins. `active_sensors()` is filtering exactly these out.
- Q14a/Q14b Identical lists — all 13 stations reported in Jun–Nov 2025. The guess "one station was silent
  six months" was wrong; the LEFT JOIN proved it. What really happened: Hadapsar (1,345 rows) and SPPU
  (1,707) each lost about two-thirds of the period in pieces, vs ~4,000 rows for the others.
  Lesson: a query written to confirm a hypothesis is allowed to kill it.

## 04 CASE
- Q15 Pashan hours by CPCB category: Good 64.1% · Satisfactory 24.8 · Moderate 8.5 · Poor 2.3 ·
  Very poor 0.2 · Severe 1 hour.
- Q16 Share of "Poor or worse" (>90) hours per month at Pashan: Dec 2025 22.6%, Jan 2026 15.9%,
  Feb 2026 10.1%, everything else ≤ 1%.
- Q17 Winter (Nov–Feb) vs rest, every station: winter is 2–3× worse everywhere. Hadapsar 107.2 vs 35.6,
  Mhada Colony 92.2 vs 32.5, Pashan 57.0 vs 24.3.

## 05 coverage
- Q18 Pashan, own span: 14,792 hours expected, 13,438 present, **1,354 missing = 9.2%**.
- Q19 Where Pashan's holes are: Apr 2025 (203 h), Jan 2026 (246 h), Oct 2026 (137 h — mostly the
  23–27 Oct upstream outage), Aug 2026 (101 h), Feb 2026 (98 h). Other months lose 1–7%.
- Q20 Same fixed window (Mar 2025 → 23 Oct 2026) for all stations, 14,439 hours each:
  Pashan 8.8% missing · Mhada Colony 12.2 · Thergaon 13.8 · Park Street 16.4 · Revenue Colony 17.2 ·
  Nigdi 17.5 · Katraj 21.7 · Gavalinagar 23.1 · Bhumkar Nagar 24.1 · Bhosari 28.9 · Dhankawadi 36.8 ·
  Hadapsar 42.4 · SPPU 45.6. Primary-station choice confirmed by coverage, not preference.

## 06 exercises (my own)
- E1 Hadapsar's daily shape vs Pashan's: 
- E2 First month where