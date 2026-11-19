"""The model settings that won the experiments, in one place.

experiments.py is the lab notebook (every idea that was tried, scored the same honest way);
this module is what production uses: train.py builds the points model from points_recipe(),
stat_models.py builds every other stat from stat_recipe(). See TRAINING.md for the results.
"""
import json
from dataclasses import replace

from . import features as F
from .modeling import BASE_PARAMS, Config
from .paths import EXPERIMENTS

# Inputs for the points model: every tested feature group except "matchup", which added noise.
POINTS_FEATURES = [f for f in F.V2 if f not in F.GROUPS["matchup"]]

# Hyperparameters found by tune.py (Optuna). They barely beat the defaults, but they're the best found.
_tuned_file = EXPERIMENTS / "best_params.json"
TUNED = dict(BASE_PARAMS)
if _tuned_file.exists():
    TUNED.update({k: v for k, v in json.loads(_tuned_file.read_text()).items() if k != "base"})

# Poisson loss (points are counts) + early stopping + a volatility model for the uncertainty.
POISSON_HETERO = dict(objective="count:poisson", rounds=None, dist="hetero")


def points_recipe() -> Config:
    """The final points model: 70% XGBoost + 30% neural net, with a volatility model. Since November 2026
    it also sees the starting lineups (E10: a real gain on every unseen season, see TRAINING.md 4e)."""
    return Config("FINAL", POINTS_FEATURES + F.LINEUPS, **POISSON_HETERO, model="ens", ens_w=0.3, params=TUNED,
                  note="v2 features (no matchup) + starting lineups + Poisson XGBoost 70% / neural net 30% + volatility model")


def stat_recipe(key: str, dist: str = "both") -> Config:
    """Model for one non-points stat (key from features.STAT_KEYS, e.g. "REB").

    dist: how its uncertainty is modeled. "nbinom" (a count distribution whose spread follows the
    projection) won for most stats, "hetero" (a volatility model) for a few such as assists and free
    throw attempts. "both" fits both so they can be compared.
    Fantasy score can be negative, so it uses squared error and the volatility model.
    Double/triple-doubles happen or don't, so they predict a chance directly (logistic loss)."""
    if key in F.YES_NO_STATS:
        objective, dist = "binary:logistic", "yes_no"
    elif key == "FS":
        objective, dist = "reg:squarederror", "hetero"
    else:
        objective = "count:poisson"
    return Config(f"STAT_{key}", F.stat_feature_list(key), target=f"Y_{key}", objective=objective,
                  params=dict(TUNED), rounds=None, patience=100, dist=dist,
                  sig_floor=0.3, note=f"{F.STAT_NAMES[key]} model")


def stat_baseline(key: str, dist: str) -> Config:
    """No-model comparison for a stat: the player's recent-weighted average, same uncertainty."""
    return replace(stat_recipe(key, dist), name=f"BASE_{key}", mean_from=f"{key}_EWM")
