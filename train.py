"""Train the final points model and save it to models/pipeline.pkl.

Usage:
    python train.py               # the winning recipe (nbaline/recipes.py)
    python train.py --config B1   # any experiment from experiments.py instead

The other stats have their own script: stat_models.py.
"""
import argparse
import json
import pickle
from datetime import date
import pandas as pd

from nbaline import features as F
from nbaline.modeling import Pipeline, is_up_to_date, load_model
from nbaline.paths import EXPERIMENTS, MODELS, POINTS_META, POINTS_MODEL
from nbaline.recipes import points_recipe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="FINAL")
    args = ap.parse_args()

    if args.config == "FINAL":
        cfg = points_recipe()
    else:
        from experiments import REGISTRY  # the lab notebook, only needed for other configs
        cfg = REGISTRY[args.config]
    df = F.load_features()
    seasons = sorted(df["SEASON"].unique())
    calib = seasons[-2]  # last complete season: early stopping + uncertainty calibration
    previous = load_model(POINTS_MODEL)
    if is_up_to_date(previous, cfg, df, inner=calib):
        print("No new data since the last training: models/pipeline.pkl is already up to date.")
        return
    print(f"Training '{cfg.name}' ({cfg.note}) on {len(df):,} player-games, {seasons[0]}-{seasons[-1]}")
    pipe = Pipeline(cfg).fit(df, inner=calib, previous=previous)
    print(f"  trees: {pipe.best_rounds}"
          + ("  (early stopping and calibration reused from the last training)" if pipe.reused_inner_fit else ""))

    MODELS.mkdir(exist_ok=True)
    with open(POINTS_MODEL, "wb") as f:
        pickle.dump(pipe, f)
    holdout = {}
    hp = EXPERIMENTS / "holdout.csv"
    if hp.exists():
        h = pd.read_csv(hp)
        h = h[h["name"] == cfg.name].drop_duplicates("fold", keep="last")
        holdout = {str(r.fold): {k: round(float(getattr(r, k)), 4) for k in ("CRPS", "MAE", "EWM_BRIER")}
                   for r in h.itertuples()}
    meta = dict(config=cfg.name, note=cfg.note, features=cfg.features, trained_on=str(date.today()),
                rows=len(df), data_through=str(df["GAME_DATE"].max().date()), holdout=holdout)
    POINTS_META.write_text(json.dumps(meta, indent=2))
    print(f"Saved models/pipeline.pkl  (data through {meta['data_through']})")


if __name__ == "__main__":
    main()
