"""Step 8 (3/3). Where does the model win, and where does it lose to "same as now"?

    python error_analysis.py            # -> results/error_analysis.csv, figures/error_by_hour.png,
                                        #    figures/error_vs_level.png, figures/pred_vs_actual.png

Every forecast here is out-of-sample: each test row was predicted by a model trained only on data before
its fold (evaluate.predictions). Over six folds that is 48 weeks of honest forecasts, which are then cut
four ways -- by fold, by month, by time of day, by how polluted the air actually turned out to be -- and
the model's MAE is put next to the benchmark's in every slice. A slice where the benchmark wins is not
an embarrassment; it is a sentence for the README and an answer in an interview.
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from baselines import load_features
from dataset import PRIMARY, usable, feature_columns
from evaluate import predictions, persistence
from metrics import mae
from splits import walk_forward
from train import make_ridge

MODEL_NAME = "ridge"
BANDS = [(0, 30, "1 Good (<=30)"), (30, 60, "2 Satisfactory (31-60)"), (60, 90, "3 Moderate (61-90)"),
         (90, 10_000, "4 Poor or worse (>90)")]
TIME_OF_DAY = [(0, 6, "night 00-05"), (6, 12, "morning 06-11"), (12, 18, "afternoon 12-17"), (18, 24, "evening 18-23")]


def label(value, bands):
    for lo, hi, name in bands:
        if lo <= value < hi or (hi == bands[-1][1] and value >= lo):
            return name
    return bands[-1][2]


def slice_table(df, by):
    """MAE of model and benchmark per group of `by`, with the winner and the margin."""
    rows = []
    for key, g in df.groupby(by, observed=True, sort=True):
        m, b = mae(g["y"], g["yhat_model"]), mae(g["y"], g["yhat_bench"])
        rows.append({"dimension": by, "segment": str(key), "n": len(g), "mae_model": round(m, 2),
                     "mae_benchmark": round(b, 2), "model_minus_benchmark": round(m - b, 2),
                     "winner": MODEL_NAME if m < b else "persistence"})
    return pd.DataFrame(rows)


def build_frame(sensor_id):
    f = usable(load_features(sensor_id))
    folds = walk_forward(f.index)
    model = make_ridge(feature_columns(f))
    df = pd.DataFrame({"y": f["y"]})
    df["yhat_model"] = predictions(model, f, folds)
    df["yhat_bench"] = predictions(persistence, f, folds)
    df = df.dropna()
    local = df.index.tz_convert("Asia/Kolkata")
    df["fold"] = 0
    for i, (_, te) in enumerate(folds, start=1):
        df.loc[df.index.isin(te), "fold"] = i
    df["month"] = local.strftime("%Y-%m")
    df["hour_ist"] = local.hour
    df["time_of_day"] = [label(h, TIME_OF_DAY) for h in df["hour_ist"]]
    df["level"] = [label(v, BANDS) for v in df["y"]]
    return df


def figures(df):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    Path("figures").mkdir(exist_ok=True)

    # 1. MAE by hour of day
    by_hour = df.groupby("hour_ist").apply(
        lambda g: pd.Series({"model": mae(g["y"], g["yhat_model"]), "benchmark": mae(g["y"], g["yhat_bench"])}),
        include_groups=False)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(by_hour.index, by_hour["benchmark"], marker="o", color="#B7791F", label="persistence (same as now)")
    ax.plot(by_hour.index, by_hour["model"], marker="o", color="#2E6F9E", label=MODEL_NAME)
    ax.set_xlabel("hour of day (IST)"); ax.set_ylabel("MAE, µg/m³"); ax.set_xticks(range(0, 24, 2))
    ax.set_title("24 h-ahead forecast error by hour of day, 48 weeks out-of-sample"); ax.grid(alpha=0.3); ax.legend()
    fig.tight_layout(); fig.savefig("figures/error_by_hour.png", dpi=130); plt.close(fig)

    # 2. MAE by actual pollution level
    by_level = df.groupby("level").apply(
        lambda g: pd.Series({"model": mae(g["y"], g["yhat_model"]), "benchmark": mae(g["y"], g["yhat_bench"]), "n": len(g)}),
        include_groups=False)
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(by_level)); w = 0.38
    ax.bar(x - w / 2, by_level["benchmark"], w, color="#B7791F", label="persistence")
    ax.bar(x + w / 2, by_level["model"], w, color="#2E6F9E", label=MODEL_NAME)
    ax.set_xticks(x); ax.set_xticklabels([f"{i}\n(n={int(n)})" for i, n in zip(by_level.index, by_level["n"])])
    ax.set_ylabel("MAE, µg/m³"); ax.set_title("Error by how polluted the air actually was"); ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig("figures/error_vs_level.png", dpi=130); plt.close(fig)

    # 3. predicted vs actual
    fig, ax = plt.subplots(figsize=(5.5, 5.5))
    ax.scatter(df["y"], df["yhat_model"], s=4, alpha=0.3, color="#2E6F9E")
    lim = [0, float(max(df["y"].max(), df["yhat_model"].max()))]
    ax.plot(lim, lim, color="#A23B3B", lw=1)
    ax.set_xlabel("actual PM2.5 24 h later"); ax.set_ylabel(f"{MODEL_NAME} forecast")
    ax.set_title("Forecast vs actual, 48 weeks out-of-sample"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig("figures/pred_vs_actual.png", dpi=130); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    args = ap.parse_args()

    df = build_frame(args.sensor)
    tables = pd.concat([slice_table(df, "fold"), slice_table(df, "month"),
                        slice_table(df, "time_of_day"), slice_table(df, "level")], ignore_index=True)
    Path("results").mkdir(exist_ok=True)
    tables.to_csv("results/error_analysis.csv", index=False)
    figures(df)

    pd.set_option("display.width", 160)
    print(f"sensor {args.sensor} · {len(df)} out-of-sample forecasts · overall MAE {MODEL_NAME} "
          f"{mae(df['y'], df['yhat_model']):.2f} vs persistence {mae(df['y'], df['yhat_bench']):.2f}")
    for dim in ("fold", "time_of_day", "level", "month"):
        print(f"\n== by {dim} ==")
        print(tables[tables["dimension"] == dim].drop(columns="dimension").to_string(index=False))
    losses = tables[tables["winner"] == "persistence"]
    print(f"\nsegments where persistence wins: {len(losses)} of {len(tables)}")
    print("written: results/error_analysis.csv, figures/error_by_hour.png, error_vs_level.png, pred_vs_actual.png")


if __name__ == "__main__":
    main()
