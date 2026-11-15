# Week 3 — 9 to 15 November 2026

## What got built

- **v1 live (9 Nov):** the model as a 64-number JSON file, a `forecasts` table that is written once and
  never updated, and a forecast step in the hourly cloud job.
- **The API (10 Nov):** `/health`, `/forecast`, `/stats` with FastAPI and Pydantic; runs locally.
- **v2, fallback tiers (13 Nov):** the same ridge on shorter lag sets (full > day > short). Hours that
  can be forecast went from 73% to 91% at the same error (8.59 vs 8.60). The `tier` column records
  which one made each forecast.
- **Gate 1 passed (15 Nov):** 19.8 days, 246 runs, 0 failed, longest gap 11 h; model 8.66 vs 9.36.
- Tests went from 51 to 77. Explainer v2 and the resume brought up to date.

## What I learned

- A forecast that is never overwritten is the only kind that can be scored honestly afterwards.
- Availability is a number to measure, like accuracy. One 5-hour hole costs the full model 31 hours.
- The 2-day and 7-day lags buy about 1% accuracy and were costing 18 points of availability.
- Walk-forward numbers move when new data arrives, because the folds are anchored on the newest day.
  Every number needs its evaluation date.
- A test record and a live record are different things. Live is running at about twice the test error
  in the week after Diwali.

## What went wrong

- Day one live: no forecasts for 24 hours after the Diwali-night gap (fixed by the tiers).
- Ran a list of steps after the first one had failed; the old script replaced models/v1.json with a
  refit still called v1. Restored from git; the script now refuses to overwrite a model file.
- The laptop could not reach the database for a day: the network's DNS refused the address.
- No work on 11, 12 and 14 Nov. Docker, planned for 12-13 Nov, is not done.

## What I couldn't explain yet (draft - rewrite in my own words)

1. **Why keep the full tier if `day` is almost as good?** On the same hours full is 8.60 and day is 8.70,
   so full is still the best answer whenever its inputs exist. The cascade costs nothing: it only uses a
   smaller tier when the bigger one cannot run.
2. **Why is the live error twice the test error?** The test averages a whole year; the live record so far
   is six days after Diwali at high levels, where the model's test error was already around 25. The
   forecasts also run 8-10 low because the season is rising. Too few days to judge; checkpoint 29 Nov.
3. **Why must a model version never be overwritten?** Every row in `forecasts` says which version made
   it. If v1 is replaced by a different model with the same name, old rows point at a model that no
   longer exists and the live score for "v1" mixes two models.

## Carried into week 4

- Docker and Compose (Monday), then deploy to a public address, latency, CI.
- Live record checkpoint on 29 Nov. Resume blanks: Coursera course name and date, paper title.
