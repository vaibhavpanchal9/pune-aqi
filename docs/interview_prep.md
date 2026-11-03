# Interview prep — SQL

1. What is the difference between GROUP BY and a window function? (Q7 vs Q21)
2. `LAG(value, 24)` on a table with missing hours — what does it actually return, and what did you do about it? (Q23, Q35, decisions.md)
3. ROWS BETWEEN vs RANGE BETWEEN: when do they give different answers? (Q23, 4 Feb 2026)
4. RANK vs ROW_NUMBER vs DENSE_RANK — what happened on 21 Jan 2026 and which would you use to pick "the worst hour of each day"? (Q24)
5. Why did `max(measured_at)` take 0.03 ms on 146k rows, and why did the primary key not help a time-range query across all stations? (Q27, Q28, Q30)
6. Why not random cross-validation, and why does your benchmark change from 7.99 to 9.36? – 
I don’t use random cross-validation because hourly air-quality readings aren’t independent: the reading at 10:00 and the one at 11:00 carry almost the same information, so a random split would let the model see hours that are effectively in its test set, and the score would be flattering and meaningless. Instead I test the way the model will actually be used — trained on the past, judged on the future. I use six consecutive 8-week test windows going back 48 weeks, each trained on everything before it, with a 24-hour gap between training and test so that the last training row’s target, which is 24 hours ahead, can’t fall inside the test window.

The benchmark moved from 7.99 to 9.36 because the first number came from a single eight-week autumn window, and that season happens to be easy for a “same as now” forecaster. Across six seasons the same baseline averages 9.36, and in the winter fold it’s 14.95 — nearly three times the monsoon folds. One window gave one season’s answer; six windows gave the honest one, and they also showed that the best baseline changes with the season, which is why I look at the winter fold separately, not just the mean.
