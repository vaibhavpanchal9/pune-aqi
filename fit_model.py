"""Step 10 (1/3). Fit the product model ONCE and save it as numbers, not as a pickle.

    python tiers.py                              # first: evaluates the tiers -> results/tier_comparison.csv
    python fit_model.py                          # reads data/features_12238693.csv -> models/v2.json
    python fit_model.py --version v3 --sensor 12236443

What it fits is what was evaluated, refitted on every row each tier can use:

  point   ridge(alpha=1) on standardised features (train.py: make_ridge), once per tier (tiers.py):
          full (every feature), day (no lag beyond 24 h), short (no lag beyond 3 h)
  band    the residual-ratio 80% band (intervals.py: residual_band with ratio=True), per tier: the point
          model is fitted on everything except the last 8 weeks, its RELATIVE errors on those 8 weeks
          give the 10th and 90th percentile ratios lo_q and hi_q. Then the point model is refitted on all rows.

Why JSON and not joblib/pickle: StandardScaler + Ridge is a mean vector, a scale vector, a coefficient
vector and one intercept. Saved as JSON the model is readable, diffable in git, and needs only numpy to
run (forecast.py). A pickle needs the same scikit-learn version wherever it is loaded and executes code
on load. tests/test_forecast.py checks the JSON reproduces scikit-learn's predictions to 1e-8 and that
forecast.py's band equals intervals.py's band.

The file also records where every number came from: rows and dates each tier was trained on, the
calibration rows, the walk-forward figures read from results/tier_comparison.csv, library versions,
the git commit. Version 1 (models/v1.json, 9 Nov) was the full tier alone and stays in the repository.
"""

import argparse
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from baselines import load_features
from dataset import PRIMARY, HORIZON, feature_columns
from intervals import ALPHA, CAL_WEEKS, split_calibration

TARGET = "y"
RIDGE_ALPHA = 1.0             # the same alpha as train.py's make_ridge


def fit_pipeline(train, cols):
    """The Step 8 ridge: standardise, then Ridge(alpha=1). Returns the fitted scikit-learn pipeline."""
    model = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))
    model.fit(train[cols], train[TARGET])
    return model


def ratio_quantiles(train, cols, alpha=ALPHA):
    """(lo_q, hi_q, n_calibration): the Step 9 residual-ratio band, measured on the last CAL_WEEKS of train."""
    fit, cal = split_calibration(train)
    if len(fit) < 24 * 30:
        raise ValueError(f"only {len(fit)} rows left to fit on after holding out {CAL_WEEKS} weeks "
                         f"for calibration; the training window is too short")
    cal_pred = pd.Series(fit_pipeline(fit, cols).predict(cal[cols]), index=cal.index)
    ratio = (cal[TARGET] - cal_pred) / cal_pred.clip(lower=1.0)
    return float(np.quantile(ratio, alpha / 2)), float(np.quantile(ratio, 1 - alpha / 2)), int(len(cal))


def pipeline_numbers(model, cols):
    """The four things a StandardScaler + Ridge pipeline is: mean, scale, coef, intercept."""
    scaler, ridge = model.named_steps["standardscaler"], model.named_steps["ridge"]
    return {"features": list(cols),
            "mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist(),
            "coef": ridge.coef_.tolist(), "intercept": float(ridge.intercept_)}


def build_spec(train, cols, version="v1", sensor_id=PRIMARY, horizon=HORIZON):
    """One ridge + band on `cols`, as plain numbers with their provenance. Pure: no files, no database.

    Used once per tier by build_tiered_spec(); on its own it is the single-model layout of v1.
    """
    lo_q, hi_q, n_cal = ratio_quantiles(train, cols)
    model = fit_pipeline(train, cols)
    spec = {
        "version": version,
        "model": "ridge(alpha=1.0) on standardised features: "
                 "point = ((x - mean) / scale) . coef + intercept",
        "sensor_id": int(sensor_id),
        "horizon_hours": int(horizon),
        **pipeline_numbers(model, cols),
        "band": {
            "method": "residual_ratio",
            "nominal_coverage": round(1 - ALPHA, 2),
            "lo_q": lo_q, "hi_q": hi_q,
            "calibration_weeks": CAL_WEEKS, "calibration_rows": n_cal,
            "rule": "lower = point + lo_q * max(point, 1); upper = point + hi_q * max(point, 1); "
                    "point, lower, upper are then clipped at 0",
        },
        "trained_on": {"rows": int(len(train)),
                       "from": train.index.min().isoformat(),
                       "through": train.index.max().isoformat()},
    }
    return spec, model


def build_tiered_spec(f, tier_defs, version="v2", sensor_id=PRIMARY, horizon=HORIZON):
    """The v2 layout: one build_spec() per tier, richest first. `f` is the whole feature table.

    Returns (spec, {tier name: (fitted pipeline, the rows it was trained on)}) -- the second part is
    for the self-check in main() and for the tests.
    """
    tiers, fitted = [], {}
    for t in tier_defs:
        rows = f.dropna(subset=list(t["features"]) + [TARGET])
        one, model = build_spec(rows, t["features"], version=version, sensor_id=sensor_id, horizon=horizon)
        tiers.append({"name": t["name"], "needs_hours": int(t["needs_hours"]),
                      **{k: one[k] for k in ("features", "mean", "scale", "coef", "intercept", "band", "trained_on")}})
        fitted[t["name"]] = (model, rows)
    spec = {
        "version": version,
        "model": "ridge(alpha=1.0) on standardised features, in tiers: for each hour the first tier "
                 "whose features are all present is used. point = ((x - mean) / scale) . coef + intercept",
        "sensor_id": int(sensor_id),
        "horizon_hours": int(horizon),
        "tiers": tiers,
    }
    return spec, fitted


def walk_forward_numbers(path="results/model_comparison.csv"):
    """The Step 8 result the model was chosen on, read from the file -- never typed in."""
    p = Path(path)
    if not p.exists():
        return None
    t = pd.read_csv(p, dtype={"fold": str})
    means = t[t["fold"] == "mean"].set_index("model")["mae"]
    folds = int((t["model"] == "ridge").sum()) - 1
    return {"ridge_mae": round(float(means["ridge"]), 3),
            "persistence_mae": round(float(means["persistence"]), 3),
            "folds": folds, "source": path}


def tier_numbers(path="results/tier_comparison.csv"):
    """{tier name: its out-of-sample figures} from tiers.py's result file; {} if it has not been run."""
    p = Path(path)
    if not p.exists():
        return {}
    counts = {"features", "needs_hours", "usable_rows", "n_common", "n_served"}
    out = {}
    for row in pd.read_csv(p).to_dict("records"):
        clean = {k: (int(v) if k in counts else round(float(v), 3))
                 for k, v in row.items() if k != "tier" and not pd.isna(v)}
        clean["source"] = path
        out[row["tier"]] = clean
    return out


def check_not_overwriting(path, overwrite=False):
    """A model version is immutable: the forecasts table refers to it by name. Refuse to replace a file.

    On 13 Nov a rerun of this script replaced models/v1.json with a refit that was still called "v1".
    Nothing was issued from it, but from then on "v1" would have meant two different models.
    """
    if Path(path).exists() and not overwrite:
        raise SystemExit(f"{path} already exists. A model version is never overwritten once it may have issued "
                         f"forecasts: fit under a new --version. (Use --overwrite only for a file that was "
                         f"never committed or used.)")


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:                                         # not a git checkout, or git missing
        return None


def provenance():
    return {
        "fitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "scikit-learn": sklearn.__version__},
    }


def main():
    from forecast import predict                              # the code that will use the file
    from tiers import tier_defs                               # the tier definitions that were evaluated

    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--version", default="v2")
    ap.add_argument("--out", default=None, help="default: models/<version>.json")
    ap.add_argument("--overwrite", action="store_true", help="replace an existing model file (never a used one)")
    args = ap.parse_args()

    out = Path(args.out or f"models/{args.version}.json")
    check_not_overwriting(out, args.overwrite)                # before any work: fail fast

    f = load_features(args.sensor)
    defs = tier_defs(feature_columns(f))
    spec, fitted = build_tiered_spec(f, defs, version=args.version, sensor_id=args.sensor)

    numbers = tier_numbers()
    if not numbers:
        raise SystemExit("results/tier_comparison.csv not found. Run: python tiers.py")
    for tier in spec["tiers"]:
        tier["walk_forward"] = numbers.get(tier["name"])
    spec["cascade"] = numbers.get("cascade (v2)")
    spec.update(provenance())

    # self-check: for every tier, the saved numbers must predict what the scikit-learn object predicts
    gaps = {}
    for tier in spec["tiers"]:
        model, rows = fitted[tier["name"]]
        point, _, _ = predict(tier, rows, clip=False)
        gaps[tier["name"]] = float(np.abs(point.to_numpy() - model.predict(rows[tier["features"]])).max())
    worst = max(gaps.values())
    if worst > 1e-6:
        raise SystemExit(f"JSON model disagrees with scikit-learn by {worst:.2e}; not saving")

    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n")

    print(f"model {spec['version']} for sensor {spec['sensor_id']}, {spec['horizon_hours']} h ahead, "
          f"{len(spec['tiers'])} tiers")
    for tier in spec["tiers"]:
        b, t, wf = tier["band"], tier["trained_on"], tier["walk_forward"] or {}
        print(f"  {tier['name']:<5} : {len(tier['features'])} features, needs {tier['needs_hours']} h · "
              f"trained on {t['rows']} rows through {t['through'][:16]} · "
              f"band {b['lo_q']:+.3f} / {b['hi_q']:+.3f} ({b['calibration_rows']} calibration rows) · "
              f"walk-forward MAE {wf.get('mae_folds')}")
    c = spec["cascade"] or {}
    print(f"cascade        : MAE {c.get('mae_served')} on {c.get('n_served')} out-of-sample hours "
          f"(persistence {c.get('persistence_served')}), from results/tier_comparison.csv")
    print(f"self-check     : max |json - sklearn| = {worst:.1e} over {len(gaps)} tiers")
    print(f"written        : {out}  ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
