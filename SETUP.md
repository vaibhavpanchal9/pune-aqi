# Running Day 1 and Day 2

Work through this in order. Every step has a check. If a check fails, stop
there — do not carry on and hope.

None of this code has ever touched the live API. I could not reach
`api.openaq.org` from my sandbox, so the parsing is tested against fixtures
built from OpenAQ's published response shape, not from a real call. **The
first real call is yours, in step 5.** If the shape differs from the docs,
that is where you will find out, and `--save-fixture` exists so you can
replace my guessed fixture with a real one.

---

## Before you start

Get a free API key from <https://explore.openaq.org>. Takes two minutes.

---

## Day 1

### Steps 1–3 · repo, key, environment

```bash
# after cloning your empty GitHub repo
cd pune-aqi
cp .env.example .env
# now open .env and paste your real OPENAQ_KEY and a PGPASSWORD you choose

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Check:** `git status` does **not** list `.env`. If it does, stop and fix
`.gitignore` before your key ends up on GitHub permanently.

### Step 7 · Docker

```bash
docker run hello-world
```

**Check:** prints a success message.

### Step 8 · Postgres

```bash
docker run --name aqi-pg \
  -e POSTGRES_PASSWORD=the-same-password-you-put-in-.env \
  -e POSTGRES_DB=aqi \
  -p 5432:5432 \
  --restart unless-stopped \
  -d postgres:16
```

**Check:** `docker ps` shows `aqi-pg` with status `Up`.

(`--restart unless-stopped` is Day 2 step 11, but it costs nothing to set now
and saves you recreating the container later.)

### Step 9 · the schema

```bash
docker exec -i aqi-pg psql -U postgres -d aqi < schema.sql
docker exec -it aqi-pg psql -U postgres -d aqi -c '\dt'
```

**Check:** four tables listed — `locations`, `sensors`, `measurements`,
`ingestion_runs`.

### Step 10 · Python reaches the database

```bash
python db.py
```

**Check:** prints `1`. If it hangs or refuses the connection, the password in
`.env` doesn't match the one you gave the container.

### Steps 4–6 · look at the real API

```bash
python explore_api.py --raw --save-fixture tests/fixtures/locations_real.json
python explore_api.py
python explore_api.py --markdown
```

**Check:** the last one prints a markdown table of real Pune stations. Paste it
into `docs/data_sources.md` and answer the four questions underneath.

If you get `401`, your key is wrong. If you get `422`, something is off in the
query — the error message tells you what. If you get **zero stations**, widen
the search: `python explore_api.py --all-parameters`.

---

## Day 2

### Steps 2–4 · build the registry, then collect

```bash
python ingest.py --discover
```

**Check:**
```sql
SELECT count(*) FROM locations;
SELECT count(*) FROM sensors WHERE parameter = 'pm25';
```
Both greater than zero.

```bash
python ingest.py
```

**Check:** `SELECT count(*) FROM measurements;` is now greater than zero.

Now run it a second time immediately:

```bash
python ingest.py
```

**Check:** the row count barely moves. That is the primary key doing its job —
this is Day 2 step 4, and it's worth pausing to appreciate, because it's what
makes everything after this safe to re-run.

### Steps 5–6 · logs

Already wired up. `tail logs/ingest.log`, and:

```sql
SELECT run_at, mode, status, sensors_tried, rows_fetched, rows_inserted
FROM ingestion_runs ORDER BY run_at DESC;
```

### Step 7 · the hourly schedule

**Linux / macOS** — `crontab -e`, then add one line with **absolute paths**:

```
17 * * * * cd /home/you/pune-aqi && /home/you/pune-aqi/.venv/bin/python ingest.py >> logs/cron.log 2>&1
```

Minute 17 rather than 0 — stations publish a little after the hour, and
everyone's scripts fire at :00.

**Windows** — Task Scheduler, new task, trigger daily repeating every 1 hour,
action `C:\path\to\pune-aqi\.venv\Scripts\python.exe`, argument `ingest.py`,
start-in `C:\path\to\pune-aqi`.

**Check (step 8):** wait for the next :17. Do not run it by hand.
```sql
SELECT * FROM ingestion_runs ORDER BY run_at DESC LIMIT 1;
```
A row appeared that you did not cause. That's Day 2 done.

### Step 10 · health check

```bash
python healthcheck.py
```

**Check:** prints a dashboard ending in `STATUS: OK`.

This is task 1 of every subsequent day. Ten seconds. It's the only thing
standing between you and finding out in November that the job died in
September.

### Step 11 · survive a restart

Restart Docker Desktop, or `sudo systemctl restart docker`.

**Check:** `docker ps` shows `aqi-pg` up again and `python healthcheck.py`
still reports your rows. If you skipped `--restart unless-stopped` in Day 1
step 8:

```bash
docker update --restart unless-stopped aqi-pg
```

---

## Tests

```bash
pytest -q
```

17 tests, no network, no database, under a second. Day 5 asks for 3 — you have
these early because the parsing had to be verified somehow.

Two of them are worth reading before you move on:
`test_latitude_is_not_silently_swapped_with_longitude` and
`test_flatten_hours_drops_null_values_but_keeps_real_zeros`. Each one guards a
bug that produces plausible-looking data rather than an error, and those are
the only bugs that survive to hurt you in an interview.

---

## Where the resume numbers come from

Nothing here is fillable yet. Day 27 runs the audit. For reference:

| Placeholder | Query |
|---|---|
| monitoring stations | `SELECT count(DISTINCT location_id) FROM sensors WHERE parameter='pm25';` |
| days running | `SELECT EXTRACT(DAY FROM now() - min(run_at)) FROM ingestion_runs WHERE status IN ('ok','partial');` |
| rows collected | `SELECT count(*) FROM measurements;` |

The days counter starts at the first successful run and only means anything if
the job actually keeps running. That is the whole reason Day 2 comes before
everything else.
