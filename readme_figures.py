"""The two README pictures that put forecasts next to what was measured.

    python readme_figures.py      # -> figures/forecast_example.png, figures/forecast_diwali.png

Both use the walk-forward test rows, scored with the band exactly as it is live (band_weekly.out_of_sample),
so every forecast on them was made by a model that had not seen that hour.

Three things the old picture (figures/intervals.png) got wrong, and these get right:
  * The time axis is the hour being FORECAST. A forecast made at hour t is for t + 24 h, and that is
    where it is drawn, next to the reading of the same hour.
  * A missing hour is a break in the line. Nothing is drawn across a hole in the data.
  * The title says which days are shown.

forecast_example.png   an ordinary fortnight, chosen by a rule and not by eye: the most recent 14 days of
                       the test windows in which at least 80% of the hours have a forecast.
forecast_diwali.png    the week of Diwali 2026 (5 to 11 Nov), the clearest case of what the model cannot
                       do: it only knows the station's past, so it cannot see a jump coming.
"""

from pathlib import Path

import pandas as pd

from band_weekly import fold_windows, out_of_sample
from baselines import load_features
from dataset import HORIZON, IST, PRIMARY, usable, feature_columns
from splits import walk_forward

DAYS = 14
MIN_SHARE = 0.80
EVENT = ("2026-11-05", "2026-11-12", "Diwali week")        # IST days: from the first, up to but not the second


def at_target_time(oos, horizon=HORIZON):
    """The same rows, indexed by the hour each forecast is FOR (origin + horizon), in IST."""
    out = oos.copy()
    out.index = (oos.index + pd.Timedelta(hours=horizon)).tz_convert(IST)
    return out.sort_index()


def recent_dense_window(index, windows, days=DAYS, min_share=MIN_SHARE):
    """(start, end, share): the most recent `days`-day stretch, inside one test window, in which at least
    `min_share` of the hours are in `index`. A row t is in the stretch if start < t <= end.

    Candidates end at a window's end, or a whole number of days before it. If no stretch reaches
    `min_share`, the best-filled one is returned, so the caller always gets a window and its true share.
    """
    span, best = pd.Timedelta(days=days), None
    for lo, hi in reversed(windows):                               # newest test window first
        end = hi
        while end - span >= lo:
            start = end - span
            share = ((index > start) & (index <= end)).sum() / (days * 24)
            if share >= min_share:
                return start, end, float(share)
            if best is None or share > best[2]:
                best = (start, end, float(share))
            end -= pd.Timedelta(days=1)
    return best


def on_hourly_grid(frame, start, end):
    """The rows with start < t <= end on a full hourly grid. A missing hour becomes a row of NaN, and
    matplotlib breaks a line at NaN: that is what keeps holes in the data visible as holes."""
    grid = pd.date_range(start + pd.Timedelta(hours=1), end, freq="h")
    return frame[(frame.index > start) & (frame.index <= end)].reindex(grid)


def describe_window(g):
    """Plain numbers about what is on a picture, for its caption."""
    have = g.dropna(subset=["y", "point"])
    inside = (have["y"] >= have["lower"]) & (have["y"] <= have["upper"])
    out = {"hours": int(len(g)), "scored": int(len(have))}
    if len(have):
        peak = have["y"].idxmax()
        out.update(mae=float((have["point"] - have["y"]).abs().mean()),
                   mae_persistence=float((have["persistence"] - have["y"]).abs().mean()),
                   inside=float(inside.mean()), peak_time=peak, peak_actual=float(have.loc[peak, "y"]),
                   peak_forecast=float(have.loc[peak, "point"]), peak_upper=float(have.loc[peak, "upper"]))
    return out


def plot_window(g, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.fill_between(g.index, g["lower"], g["upper"], color="#2E6F9E", alpha=0.2, label="80% band")
    ax.plot(g.index, g["point"], color="#2E6F9E", lw=1.3, label="forecast, made 24 h earlier")
    ax.plot(g.index, g["y"], color="#172029", lw=1.0, label="measured")
    ax.set_ylabel("PM2.5, µg/m³"); ax.set_title(title)
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(g) // 24 // 8), tz=g.index.tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b", tz=g.index.tz))
    ax.set_xlabel("hour being forecast (IST); a break in a line = no forecast or no reading for that hour")
    ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(path).parent.mkdir(exist_ok=True)
    fig.savefig(path, dpi=130); plt.close(fig)


def say(name, d):
    print(f"{name}: {d['scored']} of {d['hours']} hours have a forecast and a reading")
    if d["scored"]:
        print(f"  MAE {d['mae']:.2f} against {d['mae_persistence']:.2f} for persistence · inside the band {d['inside']:.2f}")
        print(f"  highest reading {d['peak_actual']:.0f} at {d['peak_time']:%a %d %b %H:%M} IST; "
              f"the forecast for that hour was {d['peak_forecast']:.0f} (band up to {d['peak_upper']:.0f})")


def main():
    f = usable(load_features(PRIMARY))
    end = f.index.max()
    folds = walk_forward(f.index, end=end)
    oos = at_target_time(out_of_sample(f, folds, feature_columns(f)))
    shift = pd.Timedelta(hours=HORIZON)
    windows = [((lo + shift).tz_convert(IST), (hi + shift).tz_convert(IST)) for lo, hi in fold_windows(end)]
    print(f"sensor {PRIMARY} · {len(oos):,} test forecasts · hours being forecast: "
          f"{oos.index.min():%d %b %Y} to {oos.index.max():%d %b %Y} (IST)\n")

    start, stop, share = recent_dense_window(oos.index, windows)
    g = on_hourly_grid(oos, start, stop)
    title = (f"What the forecast said a day ahead, and what was measured: "
             f"{start + pd.Timedelta(hours=1):%d %b} to {stop:%d %b %Y}")
    plot_window(g, "figures/forecast_example.png", title)
    print(f"forecast_example.png: the most recent {DAYS} days with at least {MIN_SHARE:.0%} of hours forecast"
          f" -> {start + pd.Timedelta(hours=1):%d %b %H:%M} to {stop:%d %b %H:%M %Y} IST, share {share:.2f}")
    say("  on it", describe_window(g))

    first, last = (pd.Timestamp(d, tz=IST) for d in EVENT[:2])
    g = on_hourly_grid(oos, first - pd.Timedelta(hours=1), last - pd.Timedelta(hours=1))
    d = describe_window(g)
    if d["scored"]:
        plot_window(g, "figures/forecast_diwali.png",
                    f"{EVENT[2]}, {first:%d %b} to {last - pd.Timedelta(days=1):%d %b %Y}: "
                    f"what the forecast said a day ahead, and what was measured")
        print(f"\nforecast_diwali.png: {EVENT[2]}, {first:%d %b} to {last - pd.Timedelta(days=1):%d %b %Y}")
        say("  on it", d)
    else:
        print(f"\nno test forecasts between {EVENT[0]} and {EVENT[1]}: forecast_diwali.png not written")
    print("\nwritten: figures/forecast_example.png" + (", figures/forecast_diwali.png" if d["scored"] else ""))


if __name__ == "__main__":
    main()
