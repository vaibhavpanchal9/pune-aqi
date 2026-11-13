"""The model file: where it is, how to read it, and its tiers.

One place for the path, so forecast.py (which writes forecasts) and service.py (which serves them)
cannot point at different models. No pandas and no numpy here: the API imports this module.

A model file is JSON. Version 1 (models/v1.json) is one ridge model. From version 2 a file holds
several "tiers" of the same recipe, richest first; forecast.py uses the first tier whose features
are all present for an hour. tiers_of() reads both layouts.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = "models/v2.json"

_TIER_KEYS = ("features", "mean", "scale", "coef", "intercept", "band", "trained_on")


def load_model(path=DEFAULT_MODEL):
    p = Path(path)
    if not p.is_absolute() and not p.exists():       # run from another directory: look next to this file
        p = ROOT / path
    return json.loads(p.read_text())


def tiers_of(spec):
    """The model's tiers, richest first. A v1 file (no "tiers" key) is a single tier called 'full'."""
    if "tiers" in spec:
        return spec["tiers"]
    tier = {"name": "full", **{k: spec[k] for k in _TIER_KEYS if k in spec}}
    tier["walk_forward"] = spec.get("walk_forward")
    return [tier]
