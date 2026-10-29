# Interview prep — SQL

1. What is the difference between GROUP BY and a window function? (Q7 vs Q21)
2. `LAG(value, 24)` on a table with missing hours — what does it actually return, and what did you do about it? (Q23, Q35, decisions.md)
3. ROWS BETWEEN vs RANGE BETWEEN: when do they give different answers? (Q23, 4 Feb 2026)
4. RANK vs ROW_NUMBER vs DENSE_RANK — what happened on 21 Jan 2026 and which would you use to pick "the worst hour of each day"? (Q24)
5. Why did `max(measured_at)` take 0.03 ms on 146k rows, and why did the primary key not help a time-range query across all stations? (Q27, Q28, Q30)