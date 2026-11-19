"""Hyperparameter tuning with Optuna (Bayesian search).

Each trial picks a set of settings (tree depth, regularization, ...), trains with early
stopping on 2 walk-forward folds, and is scored by average CRPS. Optuna learns which
regions of the search space work and samples there more. Bad trials are stopped early
(pruned) after the first fold to save time.

Usage:
    python tune.py --base B1 --trials 40
Writes experiments/best_params.json, which nbaline/recipes.py reads as TUNED.
"""
import argparse
import json
from dataclasses import replace

import numpy as np
import optuna

from experiments import OUT, REGISTRY
from nbaline import features as F
from nbaline.evaluate import crps
from nbaline.modeling import BASE_PARAMS, Pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="B1", help="experiment whose features/loss/distribution to tune")
    ap.add_argument("--trials", type=int, default=30)
    ap.add_argument("--folds", type=int, nargs="*", default=[2023, 2024],
                    help="search on these folds (the winner is re-checked on all folds afterwards)")
    args = ap.parse_args()

    base = REGISTRY[args.base]
    df = F.load_features()
    folds = [(df[df["SEASON"] < S], df[df["SEASON"] == S]) for S in args.folds]

    def objective(trial: optuna.Trial):
        params = dict(BASE_PARAMS,
                      learning_rate=trial.suggest_float("learning_rate", 0.05, 0.15, log=True),  # fast while searching
                      max_depth=trial.suggest_int("max_depth", 3, 8),
                      min_child_weight=trial.suggest_float("min_child_weight", 1, 300, log=True),
                      subsample=trial.suggest_float("subsample", 0.5, 1.0),
                      colsample_bytree=trial.suggest_float("colsample_bytree", 0.3, 1.0),
                      reg_lambda=trial.suggest_float("reg_lambda", 0.01, 100, log=True),
                      reg_alpha=trial.suggest_float("reg_alpha", 0.001, 10, log=True),
                      gamma=trial.suggest_float("gamma", 0.0, 2.0),
                      max_delta_step=trial.suggest_float("max_delta_step", 0.3, 2.0))
        cfg = replace(base, name=f"trial{trial.number}", params=params, patience=100)
        scores, n = [], []
        for i, (train, test) in enumerate(folds):
            mu, Q = Pipeline(cfg).fit(train).predict(test)
            scores.append(crps(Q, test["PTS"].to_numpy(float)).mean())
            n.append(len(test))
            trial.report(float(np.average(scores, weights=n)), i)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.average(scores, weights=n))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42),
                                pruner=optuna.pruners.MedianPruner(n_startup_trials=6))
    # trial 0 = the current defaults, so we always know whether tuning beat them
    study.enqueue_trial({k: BASE_PARAMS.get(k, d) for k, d in
                         dict(learning_rate=0.05, max_depth=5, min_child_weight=20, subsample=0.8,
                              colsample_bytree=0.8, reg_lambda=1.0, reg_alpha=0.001, gamma=0.0,
                              max_delta_step=0.7).items()})

    def log(study, trial):
        if trial.state == optuna.trial.TrialState.COMPLETE:
            print(f"  trial {trial.number:>3}: CRPS {trial.value:.4f}  (best {study.best_value:.4f})", flush=True)
        else:
            print(f"  trial {trial.number:>3}: pruned", flush=True)

    study.optimize(objective, n_trials=args.trials, callbacks=[log])
    print(f"\nBest CRPS {study.best_value:.4f} (defaults: {study.trials[0].value:.4f})")
    print(json.dumps(study.best_params, indent=2))
    (OUT / "best_params.json").write_text(json.dumps({"base": args.base, **study.best_params}, indent=2))
    study.trials_dataframe().to_csv(OUT / "optuna_trials.csv", index=False)


if __name__ == "__main__":
    main()
