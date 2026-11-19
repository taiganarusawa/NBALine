"""The lab notebook: every modeling idea that was tried, scored with walk-forward validation.

The winners live in nbaline/recipes.py (used for the real models); TRAINING.md explains the results.

Walk-forward = always train on the past, test on the next season, like real life:
    fold 2022: train 2017-2021 -> test 2022-23
    fold 2023: train 2017-2022 -> test 2023-24
    fold 2024: train 2017-2023 -> test 2024-25
2025-26 is the HOLDOUT: never used while choosing settings, only for the final check.

Usage:
    python experiments.py base_ewm E0 E1          # run named experiments on the tuning folds
    python experiments.py E0 --holdout            # final check on 2025-26 (+ the current season)
    python experiments.py --list
"""
import argparse
import time
from dataclasses import replace
from datetime import datetime

import numpy as np
import pandas as pd

from nbaline import features as F
from nbaline.evaluate import crps, score
from nbaline.modeling import Config, Pipeline
from nbaline.paths import EXPERIMENTS as OUT
from nbaline.recipes import POINTS_FEATURES as BEST_FEATS, POISSON_HETERO as B1, TUNED, points_recipe
TUNE_FOLDS = [2022, 2023, 2024]
HOLDOUT_FOLDS = [2025, 2026]
SHOW = ["MAE", "RMSE", "BIAS", "CRPS", "COV80", "EWM_BRIER", "EWM_LOGLOSS", "EWM_ECE", "EWM_ACC", "L10_BRIER"]

V1, V2 = F.V1, F.V2
REGISTRY: dict[str, Config] = {}


def reg(cfg: Config):
    REGISTRY[cfg.name] = cfg


# ---- baselines: no ML, just an average + the same uncertainty method
reg(Config("base_l10", V1, mean_from="PTS_L10", dist="bins", note="last-10 average"))
reg(Config("base_ewm", V1, mean_from="PTS_EWM", dist="bins", note="recent-weighted average"))
# ---- E0: the prototype (5 seasons, 600 trees, v1 features)
reg(Config("E0", V1, min_season=2020, note="prototype: 5 seasons, fixed 600 trees"))
# ---- E1: early stopping (let validation error choose the number of rounds/'epochs')
reg(Config("E1", V1, min_season=2020, rounds=None, note="early stopping"))
# ---- E2: all 10 seasons of data
reg(Config("E2", V1, rounds=None, note="+ all seasons"))
# ---- E3: loss functions (what the model is trained to minimize)
for obj in ("count:poisson", "reg:tweedie", "reg:pseudohubererror", "reg:absoluteerror"):
    reg(Config(f"E3_{obj.split(':')[1]}", V1, objective=obj, rounds=None, note=f"objective {obj}"))
# ---- E4: uncertainty methods
for d in ("scaled", "hetero", "quantile"):
    reg(Config(f"E4_{d}", V1, rounds=None, dist=d, note=f"distribution: {d}"))

# ---- B1: best so far = all seasons + early stopping + Poisson loss + volatility model
reg(Config("B1", V1, **B1, note="Poisson + hetero (best of E3/E4)"))
# ---- E5: feature groups, added one at a time, then all, then all-minus-one
for gname, cols in F.GROUPS.items():
    reg(Config(f"E5_add_{gname}", V1 + cols, **B1, note=f"v1 + {gname}"))
reg(Config("E5_v2", V2, **B1, note="all features"))
for gname, cols in F.GROUPS.items():
    reg(Config(f"E5_v2_minus_{gname}", [f for f in V2 if f not in cols], **B1, note=f"v2 - {gname}"))

# ---- winners so far: BEST_FEATS (E5: v2 minus the noisy matchup group) and TUNED (tune.py), from recipes.py
# ---- E6: Optuna-tuned hyperparameters (run tune.py first)
reg(Config("E6_tuned", BEST_FEATS, **B1, params=TUNED, note="tuned hyperparameters"))
# ---- E7: training-schedule ideas
reg(Config("E7_lowlr", BEST_FEATS, **B1, params=dict(TUNED, learning_rate=TUNED["learning_rate"] / 2),
           note="half learning rate, ~2x rounds"))
for h in (2, 4):
    reg(Config(f"E7_recency{h}", BEST_FEATS, **B1, params=TUNED, recency_halflife=h,
               note=f"recent seasons weigh more (half-life {h} seasons)"))
reg(Config("E7_finetune", BEST_FEATS, **B1, params=TUNED, finetune=dict(rounds=150, lr=0.01),
           note="fine-tune: +150 trees fit only on the latest season"))
# ---- E8: neural net (epochs) and blends
reg(Config("E8_mlp", BEST_FEATS, **dict(B1, model="mlp"), note="neural net only"))
for w in (0.3, 0.5):
    reg(Config(f"E8_ens{int(w * 10)}", BEST_FEATS, **dict(B1, model="ens"), params=TUNED, ens_w=w,
               note=f"blend: {1 - w:.0%} XGBoost + {w:.0%} neural net"))

# ---- FINAL: the winner of all the above (= E8_ens3; chosen on 2022-24 folds only, checked once on the holdout)
reg(points_recipe())

# ---- E9: free extras from analysts' reasoning (close-game minutes, splits without absent teammates,
# what the opponent allows). Compared against E6_tuned (same XGBoost recipe, current inputs).
EXTRA_ALL = [f for cols in F.EXTRA.values() for f in cols]
for gname, cols in F.EXTRA.items():
    reg(Config(f"E9_{gname}", BEST_FEATS + cols, **B1, params=TUNED, note=f"+ {gname}"))
reg(Config("E9_all", BEST_FEATS + EXTRA_ALL, **B1, params=TUNED, note="+ all free extras"))
reg(replace(points_recipe(), name="FINAL_X", features=BEST_FEATS + EXTRA_ALL, note="FINAL + all free extras"))

# ---- E10: starting lineups (NBA.com has them from 2023-24 on): tonight's role, how often he's started
# lately and the minutes that come with his role. Compared against E6_tuned. Only folds whose training
# seasons include lineups can learn from them, so it's judged on fold 2024 and the holdout:
#     python experiments.py E6_tuned E10_lineups --folds 2024
reg(Config("E10_lineups", BEST_FEATS + F.LINEUPS, **B1, params=TUNED, note="+ starting lineups"))
# (it won: FINAL above now includes them; FINAL_NOL is the final model as it was before)
reg(replace(points_recipe(), name="FINAL_NOL", features=BEST_FEATS, note="FINAL without starting lineups"))

# ---- E11: player tracking (tracking.py, every season): potential assists, rebound chances, drives,
# touches per minute and how often they turn into the stat. Compared against E10_lineups (the same
# XGBoost recipe with today's inputs) on the tuning folds; FINAL_T is the final model with them.
reg(Config("E11_tracking", BEST_FEATS + F.LINEUPS + F.TRACKING, **B1, params=TUNED, note="+ player tracking"))
reg(replace(points_recipe(), name="FINAL_T", features=points_recipe().features + F.TRACKING,
            note="FINAL + player tracking"))

# ---- E12: shot profile (shots.py, every season): attempts per minute in each zone and of self-created
# jumpers, shot distance, shooting at the rim, and his shooting against what his shot mix usually scores.
# Compared against E10_lineups on the tuning folds; FINAL_S is the final model with them.
reg(Config("E12_shots", BEST_FEATS + F.LINEUPS + F.SHOTS, **B1, params=TUNED, note="+ shot profile"))
reg(replace(points_recipe(), name="FINAL_S", features=points_recipe().features + F.SHOTS,
            note="FINAL + shot profile"))


def run(cfg: Config, folds, df) -> pd.DataFrame:
    rows, per_row = [], {}
    for S in folds:
        t0 = time.time()
        pipe = Pipeline(cfg).fit(df[df["SEASON"] < S])
        test = df[df["SEASON"] == S]
        mu, Q = pipe.predict(test)
        m = score(test, mu, Q)
        per_row[str(S)] = crps(Q, test["PTS"].to_numpy(float))
        rows.append(dict(name=cfg.name, fold=S, rounds=pipe.best_rounds, secs=round(time.time() - t0), **m))
        print(f"  {cfg.name} fold {S}: CRPS {m['CRPS']:.4f}  MAE {m['MAE']:.3f}  "
              f"rounds {pipe.best_rounds}  ({rows[-1]['secs']}s)", flush=True)
    (OUT / "rows").mkdir(parents=True, exist_ok=True)
    tag = "" if folds == TUNE_FOLDS else "_holdout" if folds == HOLDOUT_FOLDS else "_f" + "-".join(map(str, folds))
    np.savez(OUT / "rows" / f"{cfg.name}{tag}.npz", **per_row)   # per-game CRPS for --compare (e.g. E10_lineups_f2024)
    res = pd.DataFrame(rows)
    res["note"], res["config"], res["when"] = cfg.note, cfg.to_json(), datetime.now().isoformat(timespec="seconds")
    return res


def summarize(res: pd.DataFrame) -> pd.DataFrame:
    """Average across folds, weighted by number of games."""
    w = res["N"]
    agg = {c: (res[c] * w).groupby(res["name"]).sum() / w.groupby(res["name"]).sum() for c in SHOW}
    return pd.DataFrame(agg)


def compare(a: str, b: str):
    """Paired test: is B's CRPS really lower than A's on the same games? (bootstrap 95% interval)"""
    ra, rb = np.load(OUT / "rows" / f"{a}.npz"), np.load(OUT / "rows" / f"{b}.npz")
    d = np.concatenate([rb[k] - ra[k] for k in ra.files])
    rng = np.random.default_rng(0)
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(1000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    verdict = "B better (real)" if hi < 0 else "A better (real)" if lo > 0 else "no clear difference"
    print(f"{b} vs {a}: CRPS change {d.mean():+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  -> {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"))
    ap.add_argument("--folds", help="comma-separated seasons to test on instead, e.g. 2024")
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)
    if args.list:
        for k, c in REGISTRY.items():
            print(f"{k:<24} {c.note}")
        return

    df = F.load_features()
    folds = HOLDOUT_FOLDS if args.holdout else [int(s) for s in args.folds.split(",")] if args.folds else TUNE_FOLDS
    OUT.mkdir(exist_ok=True)
    log = OUT / ("holdout.csv" if args.holdout else "results.csv")
    allres = []
    for name in args.names:
        print(f"> {name}: {REGISTRY[name].note}", flush=True)
        res = run(REGISTRY[name], folds, df)
        res.to_csv(log, mode="a", header=not log.exists(), index=False)
        allres.append(res)
    print("\n" + summarize(pd.concat(allres)).to_string(float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
