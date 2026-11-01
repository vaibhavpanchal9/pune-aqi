"""Step 6 (2/2). Error metrics, written by hand so you can say exactly what each one is.

    from metrics import mae, rmse, bias, score

All three take two array-likes of the same length: y (what happened) and yhat (what was forecast).
Rows where either is missing are ignored, and the count that was actually scored is returned too.

  MAE  — mean absolute error: the average size of the mistake, in µg/m³. Easy to explain, robust to
         a few huge misses. The headline number of this project.
  RMSE — root mean squared error: like MAE but squares the mistakes first, so big misses count more.
         Always >= MAE; the gap between them says how spiky the errors are.
  bias — mean of (yhat - y): positive means the forecaster runs high on average, negative runs low.
         A forecaster can have a fine MAE and a bad bias; the model's residuals need both.
"""

import numpy as np


def _pair(y, yhat):
    y = np.asarray(y, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    if y.shape != yhat.shape:
        raise ValueError(f"y and yhat have different shapes: {y.shape} vs {yhat.shape}")
    ok = ~(np.isnan(y) | np.isnan(yhat))
    return y[ok], yhat[ok]


def mae(y, yhat):
    y, yhat = _pair(y, yhat)
    return float(np.mean(np.abs(yhat - y))) if len(y) else float("nan")


def rmse(y, yhat):
    y, yhat = _pair(y, yhat)
    return float(np.sqrt(np.mean((yhat - y) ** 2))) if len(y) else float("nan")


def bias(y, yhat):
    y, yhat = _pair(y, yhat)
    return float(np.mean(yhat - y)) if len(y) else float("nan")


def score(y, yhat):
    """All three plus the number of rows that were scored, as a dict."""
    yy, hh = _pair(y, yhat)
    return {"n": int(len(yy)), "mae": mae(y, yhat), "rmse": rmse(y, yhat), "bias": bias(y, yhat)}
