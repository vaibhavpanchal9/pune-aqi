"""Step 16. How far can one week stray? The live band, scored one week at a time.

    python band_weekly.py            # -> results/band_weekly.csv, figures/band_weekly.png
    python band_weekly.py --end 2026-11-11T23:30:00Z     # the same test windows, whatever has arrived since

Why. Step 15 kept the band: over 48 test weeks it holds 0.81 of the actuals, and no other way of
sizing it earned a switch. But the live record is days old, and a figure for a whole year says nothing
about how far a single week can stray from it. Live coverage after one week was 0.66. Is that a band
that has gone wrong, or an ordinary bad week for a band that is right over the year?

What it does. It scores every walk-forward test row with the band exactly as it is live
(intervals.residual_band, ratio=True: same ridge, same folds, same rows as Step 9 and Step 15), then
cuts each 8-week test window into single weeks and into fortnights, and scores each block on its own:

  coverage          share of that block's actuals inside the band
  ridge / persist.  the ridge's MAE divided by persistence's MAE on the same hours. Under 1.00 = the
                    ridge was the better forecast in that block.

A block counts only if at least half of its hours have a scored forecast; the others are listed as
left out, not hidden.

What it is for. A yardstick. "x of 48 weeks were under 0.70" turns a live number into "ordinary" or
"unusual". It changes nothing in what is served.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from intervals import ALPHA, residual_band
from splits import walk_forward

TARGET = "y"
N_FOLDS, TEST_WEEKS = 6, 8                 # the defaults of splits.walk_forward
MIN_SHARE = 0.5                            # a block counts if at least this share of its hours is scored
THRESHOLDS = (0.50, 0.60, 0.65, 0.70, 0.75, 0.80)


def fold_windows(end, n_folds=N_FOLDS, test_weeks=TEST_WEEKS):
    """[(start, end)] of every test window, oldest first. A row t is in a window if start < t <= end.
    The same arithmetic as splits.walk_forward; main() checks the two agree on every row."""
    windows = []
    for k in range(n_folds):
        test_end = end - pd.DateOffset(weeks=test_weeks * k)
        windows.append((test_end - pd.DateOffset(weeks=test_weeks), test_end))
    return list(reversed(windows))


def out_of_sample(f, folds, cols):
    """Every test row with the live recipe's forecast and band, the actual, and persistence."""
    frames = []
    for i, (tr_idx, te_idx) in enumerate(folds, start=1):
        train, test = f.loc[tr_idx], f.loc[te_idx]
        point, lower, upper = residual_band(train, test.drop(columns=[TARGET]), cols, ratio=True)
        frames.append(pd.DataFrame({"fold": i, "y": test[TARGET], "point": point, "lower": lower,
                                    "upper": upper, "persistence": test["value"]}))
    return pd.concat(frames)


def blocks(oos, windows, days, min_share=MIN_SHARE):
    """One row per block of `days` days inside each test window.

    Block 1 of a window starts at the window's start; a row t is in block j if
    start + (j - 1) * days < t <= start + j * days. Days left over at the end of a window make no block.
    `counted` is False for a block with fewer than `min_share` of its hours scored.
    """
    rows = []
    span = pd.Timedelta(days=days)
    for fold, (start, end) in enumerate(windows, start=1):
        rows_of_fold = oos[oos["fold"] == fold]
        for j in range(int((end - start) / span)):
            lo, hi = start + j * span, start + (j + 1) * span
            b = rows_of_fold[(rows_of_fold.index > lo) & (rows_of_fold.index <= hi)]
            row = {"days": days, "fold": fold, "block": j + 1, "after": lo, "hours": days * 24,
                   "scored": len(b), "counted": len(b) >= min_share * days * 24}
            if len(b):
                err = b["point"] - b["y"]
                row.update(coverage=float(((b["y"] >= b["lower"]) & (b["y"] <= b["upper"])).mean()),
                           mae_ridge=float(err.abs().mean()),
                           mae_persistence=float((b["persistence"] - b["y"]).abs().mean()),
                           bias=float(err.mean()), mean_actual=float(b["y"].mean()))
            rows.append(row)
    return pd.DataFrame(rows)


def spread(b, thresholds=THRESHOLDS):
    """The yardstick: how the counted blocks spread. Returns a dict of plain numbers."""
    c = b[b["counted"]]
    cov = c["coverage"]
    out = {"blocks": int(len(c)), "left_out": int((~b["counted"]).sum()),
           "lowest": float(cov.min()), "p10": float(cov.quantile(0.10)), "median": float(cov.median()),
           "p90": float(cov.quantile(0.90)), "highest": float(cov.max())}
    for t in thresholds:
        out[f"under_{t:.2f}"] = int((cov < t).sum())
    out["ridge_better"] = int((c["mae_ridge"] < c["mae_persistence"]).sum())
    return out


def grid(b, column):
    """Folds down, blocks across. A block that is not counted shows as NaN."""
    table = b.assign(v=b[column].where(b["counted"])).pivot(index="fold", columns="block", values="v")
    return table.rename_axis(index="fold", columns=None)


def report(b, days, label):
    s = spread(b)
    one = {7: "week", 14: "fortnight"}.get(days, f"{days}-day block")
    need = int(np.ceil(MIN_SHARE * days * 24))
    print(f"\n{label}  (a {one} counts if at least {need} of its {days * 24} hours are scored)")
    print(f"coverage of the {1 - ALPHA:.0%} band:")
    print(grid(b, "coverage").rename(columns=lambda j: f"{one} {j}").round(2).to_string())
    print(f"{s['blocks']} counted, {s['left_out']} left out.  lowest {s['lowest']:.2f} · 10th percentile {s['p10']:.2f}"
          f" · median {s['median']:.2f} · 90th percentile {s['p90']:.2f} · highest {s['highest']:.2f}")
    print("how many were " + " · ".join(f"under {t:.2f}: {s[f'under_{t:.2f}']}" for t in THRESHOLDS)
          + f"   (of {s['blocks']})")
    ratio = b.assign(ratio=b["mae_ridge"] / b["mae_persistence"])
    print("ridge MAE / persistence MAE (under 1.00 = the ridge was better):")
    print(grid(ratio, "ratio").rename(columns=lambda j: f"{one} {j}").round(2).to_string())
    print(f"the ridge was better in {s['ridge_better']} of {s['blocks']}")
    return s


def plot_weeks(weeks, yearly, path):
    """One dot per counted week: where it is in time and how much of it the band held."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    w = weeks[weeks["counted"]]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.scatter(w["after"], w["coverage"], s=28, color="#2E6F9E", zorder=3, label="one test week")
    ax.axhline(1 - ALPHA, color="#B5432A", lw=1.0, ls="--", label="target 0.80")
    ax.axhline(yearly, color="#172029", lw=1.0, label=f"all test weeks together: {yearly:.2f}")
    for start in weeks.loc[weeks["block"] == 1, "after"]:
        ax.axvline(start, color="#9AA5B1", lw=0.6, zorder=1)
    ax.set_ylim(0, 1.02); ax.set_ylabel("share of actuals inside the band")
    ax.set_title("The 80% band, one week at a time (grey lines: where a test window starts)")
    ax.legend(loc="lower left", fontsize=8); ax.grid(alpha=0.3, axis="y")
    fig.autofmt_xdate(); fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=130); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--end", default=None, help="where the newest test window ends (UTC). "
                                                "Default: the newest usable row in the feature file")
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    end = f.index.max()
    if args.end is not None:
        end = pd.Timestamp(args.end)
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        f = f[f.index <= end]
    folds = walk_forward(f.index, end=end)
    windows = fold_windows(end)
    cols = feature_columns(f)

    pd.set_option("display.width", 200)
    print(f"sensor {args.sensor} · usable rows {len(f):,} · {f.index.min():%Y-%m-%d} to {f.index.max():%Y-%m-%d %H:%M} UTC"
          f" · test windows {windows[0][0]:%Y-%m-%d} to {windows[-1][1]:%Y-%m-%d}")

    oos = out_of_sample(f, folds, cols)
    inside = (oos["y"] >= oos["lower"]) & (oos["y"] <= oos["upper"])
    weeks, fortnights = blocks(oos, windows, 7), blocks(oos, windows, 14)
    agree = all(te.min() > start and te.max() <= stop for (_, te), (start, stop) in zip(folds, windows))
    if not agree or not (weeks["scored"].sum() == len(oos) == fortnights["scored"].sum()):
        raise SystemExit("self-check failed: the blocks do not hold every test row exactly once. Nothing written.")
    by_fold = inside.groupby(oos["fold"]).mean()
    print(f"self-check: all {len(oos):,} test rows are in exactly one week and one fortnight")
    print("coverage per fold (must be Step 15's static_8w row): " + "  ".join(f"{c:.3f}" for c in by_fold)
          + f"   mean of folds {by_fold.mean():.3f}, all rows together {inside.mean():.3f}")

    report(weeks, 7, "ONE WEEK AT A TIME")
    report(fortnights, 14, "TWO WEEKS AT A TIME")

    Path("results").mkdir(exist_ok=True)
    out = pd.concat([weeks, fortnights], ignore_index=True)
    out["after"] = out["after"].dt.strftime("%Y-%m-%d %H:%M")
    out.to_csv("results/band_weekly.csv", index=False)
    plot_weeks(weeks, float(inside.mean()), "figures/band_weekly.png")
    print("\nwritten: results/band_weekly.csv, figures/band_weekly.png")


if __name__ == "__main__":
    main()
