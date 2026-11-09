"""Step 10 (1/3). Fit the v1 product model ONCE and save it as numbers, not as a pickle.

    python fit_model.py                          # reads data/features_12238693.csv -> models/v1.json
    python fit_model.py --sensor 12236443 --version v1-mhada

What it fits is exactly what Step 8 chose and Step 9 banded, refitted on every usable row:

  point   ridge(alpha=1) on standardised features (train.py: make_ridge)
  band    the residual-ratio 80% band (intervals.py: residual_band with ratio=True): the point model
          is fitted on everything except the last 8 weeks, its RELATIVE errors on those 8 weeks give
          the 10th and 90th percentile ratios lo_q and hi_q. Then the point model is refitted on all rows.

Why JSON and not joblib/pickle: StandardScaler + Ridge is a mean vector, a scale vector, a coefficient
vector and one intercept: 3 x 21 + 1 numbers. Saved as JSON the model is readable, diffable in git,
and needs only numpy to run (forecast.py). A pickle needs the same scikit-learn version wherever it is
loaded and executes code on load. tests/test_forecast.py checks the JSON reproduces scikit-learn's
predictions to 1e-8 and that forecast.py's band equals intervals.py's band.

The file also records where every number came from: rows and dates trained on, the calibration rows,
the walk-forward MAEs read from results/model_comparison.csv, library versions, the git commit.
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
from dataset import PRIMARY, HORIZON, usable, feature_columns
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
    """Everything forecast.py needs, plus the provenance. Pure: no files, no database."""
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
        "walk_forward": walk_forward_numbers(),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sensor", type=int, default=PRIMARY)
    ap.add_argument("--version", default="v1")
    ap.add_argument("--out", default=None, help="default: models/<version>.json")
    args = ap.parse_args()

    f = usable(load_features(args.sensor))
    cols = feature_columns(f)
    spec, model = build_spec(f, cols, version=args.version, sensor_id=args.sensor)
    spec.update(provenance())

    # self-check: the saved numbers must give the same predictions as the scikit-learn object
    from forecast import predict                              # the code that will use the file
    point, _, _ = predict(spec, f, clip=False)
    gap = float(np.abs(point.to_numpy() - model.predict(f[cols])).max())
    if gap > 1e-6:
        raise SystemExit(f"JSON model disagrees with scikit-learn by {gap:.2e}; not saving")

    out = Path(args.out or f"models/{args.version}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n")

    b, t = spec["band"], spec["trained_on"]
    print(f"model {spec['version']} for sensor {spec['sensor_id']}, {spec['horizon_hours']} h ahead")
    print(f"trained on     : {t['rows']} rows, {t['from'][:10]} -> {t['through'][:16]}")
    print(f"features       : {len(spec['features'])}")
    print(f"band           : {b['method']}, lo_q {b['lo_q']:+.3f}  hi_q {b['hi_q']:+.3f} "
          f"(from {b['calibration_rows']} calibration rows, last {b['calibration_weeks']} weeks)")
    wf = spec["walk_forward"]
    if wf:
        print(f"walk-forward   : ridge {wf['ridge_mae']} vs persistence {wf['persistence_mae']} "
              f"over {wf['folds']} folds ({wf['source']})")
    print(f"self-check     : max |json - sklearn| = {gap:.1e}")
    print(f"written        : {out}  ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
