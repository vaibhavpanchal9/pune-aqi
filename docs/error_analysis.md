# Error analysis — ridge vs persistence, 48 weeks out-of-sample (6 Nov 2026)

`python error_analysis.py` → `results/error_analysis.csv` and three figures. Every forecast is out-of-sample:
each hour was predicted by a model trained only on data before its fold. 5,761 forecasts.
Overall MAE: **ridge 8.56 vs persistence 9.25** (pooled; the per-fold means are 8.66 vs 9.36).

## Where the model loses — the honest sentences
1. **When the air turns out "Poor or worse" (> 90 µg/m³), persistence is better: 18.64 vs 24.72 on 280
   hours.** A linear model fitted to all hours regresses toward the average, so on the extreme hours it
   under-forecasts — and those are the hours a warning is for. v2 candidates: quantile regression for an
   upper band; weighting persistence more when the current level is already high.
2. **The first winter in the record (fold 1, Nov–Dec 2025): 15.39 vs 14.95.** No winter in the training
   data; the model trains on Feb–Nov 2025 and is asked about December. From February 2026 on, with one
   winter seen, the model wins every month.

## Where it wins
- Every time of day; the margin is largest in the morning (9.45 vs 10.30) and evening (7.92 vs 8.76).
  Mornings are the hardest hours for both (the 9–10 am peak).
- Good, Satisfactory and Moderate hours — by 1.9 points in the Satisfactory band.
- Ten of twelve months; the monsoon months are easy for everything (MAE 4–6).

## By fold
segment    n  mae_model  mae_benchmark  model_minus_benchmark      winner
      1 1015      15.39          14.95                   0.44 persistence
      2  673      10.36          11.31                  -0.96       ridge
      3 1085       9.42          10.73                  -1.31       ridge
      4 1064       5.22           5.91                  -0.69       ridge
      5 1024       4.43           5.25                  -0.82       ridge
      6  900       7.13           7.99                  -0.86       ridge


## By time of day (IST)
        segment    n  mae_model  mae_benchmark  model_minus_benchmark winner
afternoon 12-17 1440       8.19           8.74                  -0.55  ridge
  evening 18-23 1380       7.92           8.76                  -0.84  ridge
  morning 06-11 1521       9.45          10.30                  -0.85  ridge
    night 00-05 1420       8.60           9.11                  -0.51  ridge


## By actual pollution level
               segment    n  mae_model  mae_benchmark  model_minus_benchmark      winner
         1 Good (<=30) 3231       6.01           6.57                  -0.56       ridge
2 Satisfactory (31-60) 1554       9.31          11.20                  -1.89       ridge
    3 Moderate (61-90)  696      12.22          13.58                  -1.35       ridge
 4 Poor or worse (>90)  280      24.72          18.64                   6.08 persistence


## By month
segment   n  mae_model  mae_benchmark  model_minus_benchmark      winner
2025-11  74      10.39           8.94                   1.44 persistence
2025-12 733      14.81          14.52                   0.30 persistence
2026-01 307      17.43          17.68                  -0.25       ridge
2026-02 248       9.71          10.32                  -0.61       ridge
2026-03 612       9.66          10.87                  -1.21       ridge
2026-04 636      10.21          11.58                  -1.37       ridge
2026-05 537       6.12           7.00                  -0.88       ridge
2026-06 523       5.11           5.79                  -0.69       ridge
2026-07 617       4.55           5.11                  -0.57       ridge
2026-08 541       4.14           5.06                  -0.93       ridge
2026-09 615       5.91           6.59                  -0.68       ridge
2026-10 318       9.08          10.17                  -1.10       ridge



## Figures
`figures/error_by_hour.png` · `figures/error_vs_level.png` · `figures/pred_vs_actual.png`