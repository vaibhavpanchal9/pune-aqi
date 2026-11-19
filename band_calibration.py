"""Step 15. How should the 80% band be sized? An experiment on the walk-forward folds.

    python band_calibration.py            # -> results/band_calibration.csv, figures/band_calibration.png
    python band_calibration.py --end 2026-11-12T10:30:00Z     # the same test windows, whatever has arrived since

Why. The band that is live is sized ONCE. The ridge is fitted without the last 8 weeks, its relative
errors on those 8 weeks give two numbers (their 10th and 90th percentile), and those two numbers are
used unchanged from then on (intervals.py, fit_model.py). Live, after 125 scored hours, 66% of the
actuals fell inside a band that is meant to hold 80% (19 Nov 2026).

Two suspects, tested separately. Same ridge, same folds and same rows as intervals.py:

  static_Nw    sized once, from the last N weeks before the test window. static_8w is what is live.
               Question: does a shorter look-back help?
  rolling_Nd   re-sized for every forecast, from the errors of the last N days that are ALREADY KNOWN.
               Question: does it help to let the band learn from the forecasts it has just got wrong?

"Already known" is the whole point. The error of the forecast made at origin hour s is known only when
its target hour, s + 24 h, has a reading. So the band for origin hour t may use the errors of origins
up to t - 24 h and nothing later. tests/test_band_calibration.py pins that down: changing an actual in
the future never changes a band in the past. At the start of a test window the known errors are those
of the calibration weeks; as the window goes on, the model's own test errors take over. That is what a
live system would see.

Judged per fold, as in Step 9:
  coverage        share of actuals inside the band. Target 0.80.
  fold_miss       how far coverage is from 0.80, averaged over the folds. A method that is 0.95 in one
                  season and 0.65 in the next has a fine mean and a bad fold_miss.
  width           mean (upper - lower). Narrower is better only if coverage holds.
  interval_score  width, plus a fine of 10 x the distance for every actual outside the band (the
                  Winkler score for an 80% band). One number for "narrow AND honest". Lower is better.

The same errors also give a middle (their median). mae_middle is the MAE of the point forecast after
shifting it to the middle of its band, next to the plain ridge and to persistence. It is reported, not
decided on here.

THE RULE, written down before the numbers were seen. The live band (static_8w) is replaced only by a
scheme that
  1. is closer to 0.80 fold by fold: its fold_miss is lower than static_8w's by at least 0.02; and
  2. does not buy that with width: its interval_score is not worse than static_8w's.
  3. Among the schemes that pass 1 and 2 the lowest fold_miss wins. Schemes within 0.01 of the lowest
     count as equal, and among equals the one listed first wins: the simplest, with the longest memory
     and so the most errors behind each number.
Otherwise the simpler band stays. A band that re-sizes itself is one more moving part, and it has to
earn its place. (rolling_56d has the same memory as static_8w, so the pair shows what re-sizing alone does.)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baselines import load_features
from dataset import PRIMARY, HORIZON, usable, feature_columns
from intervals import ALPHA, CAL_WEEKS, coverage, split_calibration
from metrics import mae
from splits import walk_forward, describe
from train import make_ridge

TARGET = "y"
QS = (ALPHA / 2, 0.5, 1 - ALPHA / 2)      # lower edge, middle, upper edge of the band
# Simplest first, then longest memory first. Rule 3 breaks ties towards the top of this list.
SCHEMES = [("static", 8), ("static", 4), ("static", 2),
           ("rolling", 56), ("rolling", 28), ("rolling", 14), ("rolling", 7), ("rolling", 3)]
LIVE = "static_8w"            # what models/v2.json uses
MIN_ERRORS = 48               # a rolling window with fewer known errors than this falls back to static_8w
POOR = 90                     # "Poor or worse" starts above 90 µg/m³, as in Step 9
MARGIN = 0.02                 # rule 1: how much closer to 0.80, fold by fold, a scheme must be
TIE = 0.01                    # rule 3: fold_miss values this close count as equal


def name_of(kind, n):
    return f"{kind}_{n}{'w' if kind == 'static' else 'd'}"


# ----------------------------------------------------------------------------- errors and quantiles
def relative_error(y, point):
    """The error as a share of the forecast: (actual - forecast) / max(forecast, 1). Same as intervals.py."""
    return (y - point) / point.clip(lower=1.0)


def calibration_errors(train, cols, weeks):
    """Relative errors on the last `weeks` weeks of train, made by a ridge that never saw those weeks."""
    fit, cal = split_calibration(train, weeks=weeks)
    return relative_error(cal[TARGET], make_ridge(cols)(fit, cal)).sort_index()


def rolling_quantiles(errors, at, days, horizon=HORIZON, qs=QS, min_n=MIN_ERRORS):
    """For every timestamp in `at`: the quantiles of the errors known at that moment and at most `days` old.

    errors   relative errors indexed by ORIGIN hour, sorted. The error of origin s is known at s + horizon.
    at       the origin hours a band is wanted for.
    Returns a frame indexed like `at` with columns lo, mid, hi, n. Where fewer than `min_n` errors are
    known in the window, lo / mid / hi are NaN: the caller decides what to fall back to.
    """
    known_at = errors.index + pd.Timedelta(hours=horizon)
    values = errors.to_numpy(dtype=float)
    last = known_at.searchsorted(at, side="right")                               # known at or before t
    first = known_at.searchsorted(at - pd.Timedelta(days=days), side="right")    # and newer than t - days
    out = np.full((len(at), len(qs)), np.nan)
    for i, (a, b) in enumerate(zip(first, last)):
        if b - a >= min_n:
            out[i] = np.quantile(values[a:b], qs)
    frame = pd.DataFrame(out, index=at, columns=["lo", "mid", "hi"])
    frame["n"] = last - first
    return frame


def band_from(point, q):
    """(lower, middle, upper) Series. `q` is three numbers, or a frame with lo / mid / hi per row."""
    base = point.clip(lower=1.0)
    lo, mid, hi = (q["lo"], q["mid"], q["hi"]) if isinstance(q, pd.DataFrame) else q
    return point + lo * base, point + mid * base, point + hi * base


def bands_for_fold(point, static_errors, test_errors, schemes=SCHEMES):
    """Every scheme's band for one fold. Pure: Series in, Series out, no model and no files.

    point          the ridge's forecasts for the test rows
    static_errors  {weeks: calibration errors of the last `weeks` weeks before the test window}
    test_errors    the ridge's relative errors on the test rows (each one used only once it is known)
    Returns ({scheme name: (lower, middle, upper)}, {scheme name: share of rows that fell back}).
    """
    fallback = np.quantile(static_errors[CAL_WEEKS], QS)
    stream = pd.concat([static_errors[CAL_WEEKS], test_errors]).sort_index()
    bands, fell_back = {}, {}
    for kind, n in schemes:
        if kind == "static":
            q, share = tuple(np.quantile(static_errors[n], QS)), 0.0
        else:
            q = rolling_quantiles(stream, point.index, days=n)
            thin = q["lo"].isna()
            q.loc[thin, ["lo", "mid", "hi"]] = fallback
            share = float(thin.mean())
        bands[name_of(kind, n)] = band_from(point, q)
        fell_back[name_of(kind, n)] = share
    return bands, fell_back


# ----------------------------------------------------------------------------- scoring
def interval_score(y, lo, hi, alpha=ALPHA):
    """Mean of: width + (2 / alpha) * how far outside the band the actual fell. Lower is better."""
    outside = (lo - y).clip(lower=0) + (y - hi).clip(lower=0)
    return float(((hi - lo) + (2 / alpha) * outside).mean())


def score_band(y, lo, mid, hi):
    poor = y > POOR
    return {"n": int(len(y)),
            "coverage": coverage(y, lo, hi),
            "below": float((y < lo).mean()), "above": float((y > hi).mean()),
            "width": float((hi - lo).mean()),
            "interval_score": interval_score(y, lo, hi),
            "coverage_poor_plus": coverage(y[poor], lo[poor], hi[poor]) if poor.any() else np.nan,
            "n_poor_plus": int(poor.sum()),
            "mae_middle": mae(y, mid)}


def evaluate_schemes(f, folds, cols, schemes=SCHEMES):
    """One row per (scheme, fold). Also returns the largest difference between this file's static_8w band
    and intervals.py's residual-ratio band, which must be 0: same recipe, written twice."""
    from intervals import residual_band
    rows, worst_diff = [], 0.0
    weeks_needed = sorted({n for kind, n in schemes if kind == "static"} | {CAL_WEEKS})
    for i, (tr_idx, te_idx) in enumerate(folds, start=1):
        train, test = f.loc[tr_idx], f.loc[te_idx]
        y = test[TARGET]
        point = make_ridge(cols)(train, test)
        static_errors = {w: calibration_errors(train, cols, w) for w in weeks_needed}
        bands, fell_back = bands_for_fold(point, static_errors, relative_error(y, point), schemes)

        _, ref_lo, ref_hi = residual_band(train, test.drop(columns=[TARGET]), cols, ratio=True)
        lo, _, hi = bands[LIVE]
        worst_diff = max(worst_diff, float((lo - ref_lo).abs().max()), float((hi - ref_hi).abs().max()))

        for name, (lo, mid, hi) in bands.items():
            rows.append({"scheme": name, "fold": i, **score_band(y, lo, mid, hi),
                         "mae_ridge": mae(y, point), "mae_persistence": mae(y, test["value"]),
                         "fallback_share": fell_back[name]})
    return pd.DataFrame(rows), worst_diff


def summarise(per_fold):
    """One row per scheme: the mean over folds, the worst and best fold, and the fold-to-fold miss."""
    g = per_fold.groupby("scheme", sort=False)
    s = g[["coverage", "width", "interval_score", "below", "above", "mae_middle", "mae_ridge",
           "mae_persistence", "fallback_share"]].mean()
    s.insert(1, "worst_fold", g["coverage"].min())
    s.insert(2, "best_fold", g["coverage"].max())
    s.insert(3, "fold_miss", g["coverage"].apply(lambda c: float((c - (1 - ALPHA)).abs().mean())))
    return s


def pick(summary, live=LIVE, margin=MARGIN, tie=TIE):
    """THE RULE from the top of this file. Returns (scheme to use, the reason in one sentence).

    `summary` is in SCHEMES order (simplest and longest memory first), which is rule 3's tie-break.
    """
    others = summary.drop(index=live)
    if others.empty:
        return live, "there is nothing to compare it with"
    gain = summary.loc[live, "fold_miss"] - others["fold_miss"]
    closer = others[gain >= margin]
    if closer.empty:
        return live, (f"no scheme is closer to 0.80 fold by fold by the {margin:.2f} the rule asks for "
                      f"(the largest gain is {gain.max():.3f}, by {gain.idxmax()})")
    passed = closer[closer["interval_score"] <= summary.loc[live, "interval_score"]]
    if passed.empty:
        return live, (f"closer to 0.80 fold by fold: {', '.join(closer.index)}, but only with a worse "
                      f"interval score than {live}")
    best = passed.index[passed["fold_miss"] <= passed["fold_miss"].min() + tie][0]
    return best, (f"its fold_miss is {gain[best]:.3f} lower than {live}'s, its interval score is no worse, "
                  f"and it is the simplest of the schemes that get that close to 0.80")


# ----------------------------------------------------------------------------- output
def plot_coverage(per_fold, chosen, path, windows=None):
    """Coverage per fold: the live band, the chosen one if different, the others in grey.

    `windows` is splits.describe(folds); with it each fold is labelled with the months it tests.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    table = per_fold.pivot(index="fold", columns="scheme", values="coverage")
    fig, ax = plt.subplots(figsize=(9, 4))
    others = [name for name in table.columns if name not in (LIVE, chosen)]
    for k, name in enumerate(others):
        ax.plot(table.index, table[name], color="#9AA5B1", lw=1.0, marker="o", ms=3,
                label="the other schemes" if k == 0 else None)
    ax.plot(table.index, table[LIVE], color="#172029", lw=2.0, marker="o", label=f"{LIVE} (live)")
    if chosen != LIVE:
        ax.plot(table.index, table[chosen], color="#2E6F9E", lw=2.0, marker="o", label=f"{chosen} (the rule's pick)")
    ax.axhline(1 - ALPHA, color="#B5432A", lw=1.0, ls="--", label="target 0.80")
    ax.set_ylabel("share of actuals inside the band")
    ax.set_title("Coverage of the 80% band in each walk-forward test window")
    ax.set_xticks(list(table.index))
    if windows is not None:
        ax.set_xticklabels([f"fold {r.fold}\n{r.test_from:%b %y} to {r.test_to:%b %y}" for r in windows.itertuples()],
                           fontsize=8)
    ax.legend(loc="best", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=130); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--end", default=None, help="where the newest test window ends (UTC), e.g. 2026-11-12T10:30:00Z. "
                                                "Default: the newest usable row in the feature file")
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    end = None
    if args.end is not None:
        end = pd.Timestamp(args.end)
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        f = f[f.index <= end]
    folds = walk_forward(f.index, end=end)
    cols = feature_columns(f)

    pd.set_option("display.width", 200)
    print(f"sensor {args.sensor} · usable rows {len(f):,} · {f.index.min():%Y-%m-%d} to {f.index.max():%Y-%m-%d %H:%M} UTC"
          f" · nominal coverage {1 - ALPHA:.0%}\n")
    d = describe(folds)
    print(d.assign(test_from=d["test_from"].dt.strftime("%Y-%m-%d"), test_to=d["test_to"].dt.strftime("%Y-%m-%d"))
          [["fold", "train_rows", "test_from", "test_to", "test_rows"]].to_string(index=False))

    per_fold, worst_diff = evaluate_schemes(f, folds, cols)
    print(f"\nself-check: {LIVE} here against intervals.py's residual-ratio band, largest difference {worst_diff:.2e}")
    if worst_diff > 1e-9:
        raise SystemExit("the two should be identical: stopping, nothing written")

    s = summarise(per_fold)
    print("\nmean over the folds (coverage target 0.80; fold_miss and interval_score: lower is better):")
    print(s[["coverage", "worst_fold", "best_fold", "fold_miss", "width", "interval_score", "below", "above"]]
          .round(3).to_string())
    print("\ncoverage per fold:")
    print(per_fold.pivot(index="scheme", columns="fold", values="coverage").loc[s.index].round(3).to_string())
    print("\nwidth per fold:")
    print(per_fold.pivot(index="scheme", columns="fold", values="width").loc[s.index].round(1).to_string())
    print("\nMAE per fold: the plain ridge, the ridge shifted to the middle of the band, and persistence:")
    middle = per_fold.pivot(index="scheme", columns="fold", values="mae_middle").loc[s.index]
    first = per_fold[per_fold["scheme"] == LIVE].set_index("fold")
    middle.loc["(plain ridge)"] = first["mae_ridge"]
    middle.loc["(persistence)"] = first["mae_persistence"]
    middle["mean"] = middle.mean(axis=1)
    print(middle.round(2).to_string())
    if s["fallback_share"].max() > 0:
        print("\nshare of test hours where a rolling window had fewer than "
              f"{MIN_ERRORS} known errors and {LIVE}'s numbers were used:")
        print(s.loc[s["fallback_share"] > 0, "fallback_share"].round(3).to_string())

    chosen, why = pick(s)
    print(f"\nTHE RULE says: {'keep' if chosen == LIVE else 'switch to'} {chosen}. Reason: {why}.")

    Path("results").mkdir(exist_ok=True)
    totals = per_fold.groupby("scheme", sort=False)[["n", "n_poor_plus"]].sum()
    mean_rows = s.join(totals).reset_index().assign(fold="mean")
    out = pd.concat([per_fold.assign(fold=per_fold["fold"].astype(str)), mean_rows], ignore_index=True)
    out.to_csv("results/band_calibration.csv", index=False)
    plot_coverage(per_fold, chosen, "figures/band_calibration.png", windows=d)
    print("written: results/band_calibration.csv, figures/band_calibration.png")


if __name__ == "__main__":
    main()
