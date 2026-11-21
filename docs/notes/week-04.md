# Week 4 — 16 to 22 November 2026

## What got built

- **Mon 16:** the API in a container. A Dockerfile in stages, with the tests running inside the build
  and a non-root user; Compose with a local Postgres; a script that copies cloud data to it.
- **Wed 18:** the API is public at https://pune-aqi-api.onrender.com. It reads the database through a
  read-only role and keeps answers for a short time. Gate 2's condition is met; the formal check is 29 Nov.
- **Wed 18:** CI on every code push: two Python versions, lint, tests with a coverage floor, image build.
- **Thu 19:** tests that run my real SQL against a real Postgres, on the laptop and in CI, plus tests for
  the OpenAQ client and the helper scripts. 81 → 132 tests, coverage 36% → 60%.
- **Thu 19:** the band experiment. Eight ways to size the 80% band on the six folds. The live band stays.
- **Fri 20:** one week at a time. 5 of 36 test weeks and 1 of 19 fortnights were under 0.70.
- **Sat 21:** one data file, every number. The feature file is frozen with its fingerprint and all eight
  evaluation scripts were rerun on it (`results/frozen_run_2026-11-11.txt`). 151 tests now.
- **Live:** a forecast for every hour of the week (168 of 168). Band coverage of v2's full tier went
  0.647, 0.656, 0.677, 0.713 from 18 to 21 Nov. MAE against persistence went from 18.02 / 18.08 to
  16.65 / 17.42.

## What I learned

- An image is the packed program; a container is one running copy of it. Running the tests inside the
  build means an image that fails its tests cannot be made at all.
- Least privilege. The API can only read. If it were broken into, it still could not change a row.
- Latency has two clocks. The server answers in about 1 ms from its cache and 44 to 81 ms when it asks
  the database; most of the roughly 200 ms a user waits is the network trip.
- A unit test checks my logic with fakes. An integration test checks that the real parts fit. The SQL
  needed a real Postgres, because what is worth testing there is Postgres's own behaviour.
- A coverage floor does not prove quality. It stops coverage sliding back, and here it also catches the
  database tests being skipped by mistake (47% without them, 60% with them, floor 55%).
- Write the rule before looking at the numbers. I expected the rolling band to win. It did not, and the
  rule written in advance kept me from arguing it in.
- A number for a year hides the weeks. The band holds 0.81 over 48 weeks, yet one week in seven is
  under 0.70.
- Numbers drift when the data file grows. Freezing the file and writing down its fingerprint makes
  every number repeatable.

## What went wrong

- A bug in my own `bench.py`: "p95" over 30 requests was the 28th value, the 93rd percentile, because
  Python rounds 28.5 down to 28. Writing a test found it. The latency numbers have to be measured again.
- The result files had been made on different days from different data. The resume draft said 8.66
  against 9.36 while the current file says 8.91 against 9.61. The frozen run fixed that.
- On 18 Nov the API looked slow, 2 seconds a request. It was the network I was on, not the server.
  That is why the server now reports its own time in a header.
- Live band coverage was 0.66 after its first week. Three days (13 to 15 Nov) held 31 of the 44 misses.
- On 20 Nov I ran the commands in my home folder with the venv off. Nothing broke; the fix was one line.

## What I couldn't explain yet (draft - rewrite in my own words)

- **Why a shorter memory gives a worse band.** Errors come in runs of days: some calm days, then some
  wild ones. A band sized from the last 3 or 7 days has only seen the current kind of day, so when the
  kind changes the actuals fall outside. Eight weeks hold both kinds. Coverage fell step by step, from
  0.798 with 56 days of memory to 0.721 with 3.
- **Why an error is "known" only a day later.** The forecast made at 10:00 today is for 10:00 tomorrow.
  Its error exists only once tomorrow 10:00 has a reading. So a band re-sized at 10:00 today may use
  forecasts made up to 10:00 yesterday and nothing later. Using more would be seeing the future.
- **What the interval score is.** Width, plus a fine of 10 times the distance for every actual that
  falls outside. A band cannot win by being very wide (it pays in width) or very narrow (it pays fines).
- **What the fingerprint proves.** SHA-256 turns a file into 64 characters, and changing one character
  of the file changes them. Same file, same code, no randomness: the same results, byte for byte.
- **Why the ridge loses above 90 µg/m³ and in winter.** Not answered yet. My guess: a straight-line
  model fitted mostly on ordinary hours pulls very high values back towards the usual level, and in a
  long bad spell "same as now" is closer. To check: is the ridge's error in those hours mostly on the
  low side?

## Carried into week 5

- README and a short report with the numbers of the frozen run; tag v1.0.
- Measure latency again with the corrected p95.
- Sun 29 Nov: Gate 2 formal check, and the live checkpoint (full-tier band coverage against 0.70).
- `run_ingest` leaves a run at `running` if it crashes on anything but an OpenAQ error. Test first, then fix.
  A test for `healthcheck.py` is also owed.
- Resume: numbers from the frozen run, and the lines only I can fill.
- Rewrite the "couldn't explain" paragraphs of weeks 2, 3 and 4 in my own words.
- Do not run `python dataset.py` until the write-up is finished.
