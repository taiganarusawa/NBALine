"""Show how error changes as training goes on (boosting rounds / neural-net epochs).

    python learning_curve.py            # XGBoost: error on training data vs. an unseen season, per round
    python learning_curve.py --mlp      # neural net: loss per epoch

This is how you see overfitting: training error keeps falling forever, but error on
unseen games bottoms out and then creeps back up. Early stopping picks the bottom.
"""
import argparse
from dataclasses import replace

import numpy as np

from experiments import REGISTRY
from nbaline import features as F
from nbaline.modeling import Pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="B1")
    ap.add_argument("--season", type=int, default=2024, help="the unseen season to watch")
    ap.add_argument("--mlp", action="store_true")
    args = ap.parse_args()

    df = F.load_features()
    df = df[df["SEASON"] <= args.season]
    cfg = REGISTRY[args.config]
    if args.mlp:
        cfg = replace(cfg, model="mlp", rounds=None)
        pipe = Pipeline(cfg).fit(df, inner=args.season)
        loss, val = pipe.mlp_curve["loss"], pipe.mlp_curve["val_r2"]
        print("epoch   train loss   held-out R^2 (higher = better)")
        for e in range(len(loss)):
            mark = "  <- best" if e == int(np.argmax(val)) else ""
            print(f"{e + 1:>5}   {loss[e]:10.3f}   {val[e]:.4f}{mark}")
        return

    cfg = replace(cfg, patience=10_000, max_rounds=3000)  # run long so we can see past the best point
    pipe = Pipeline(cfg).fit(df, inner=args.season)
    tr, va = pipe.curve["train"]["mae"], pipe.curve["valid"]["mae"]
    best = int(np.argmin(va))
    print(f"Training on seasons < {args.season}, watching {args.season} (never trained on)\n")
    print("round   train MAE   unseen MAE")
    for r in [1, 10, 25, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 2500, 3000]:
        if r <= len(tr):
            print(f"{r:>5}   {tr[r - 1]:9.3f}   {va[r - 1]:9.3f}{'   <- best region' if abs(r - best) < r * 0.25 else ''}")
    print(f"\nBest unseen error at round {best + 1}: {va[best]:.3f}. After that, extra rounds only memorize "
          f"the training data (train MAE keeps falling to {tr[-1]:.3f}).")


if __name__ == "__main__":
    main()
