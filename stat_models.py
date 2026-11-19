"""Models for every PrizePicks stat besides points: rebounds, assists, 3-pointers, combos (PRA, ...),
steals, blocks, turnovers, fantasy score, shooting splits, fouls, dunks and double/triple-doubles.
Same method as the points model (double/triple-doubles predict a yes/no chance instead of a count).

    python stat_models.py --evaluate     # walk-forward test of every stat not tested yet (~1 min per stat)
    python stat_models.py --train        # train the final models -> models/stat_<KEY>.pkl (4 at a time)
    python stat_models.py --ab lineups   # do extra inputs help? every stat with vs. without them

How a stat is tested:
  * the 2023-24 and 2024-25 seasons choose its uncertainty method (volatility model vs. a count
    distribution), by the over/under Brier score on lines set at the player's recent-weighted average,
    among the methods that are well calibrated on those seasons;
  * the 2025-26 holdout is scored once with that choice and compared with a no-model baseline
    (the recent-weighted average itself, with the same kind of uncertainty).
A stat is marked "reliable" only if it beats the baseline on the holdout AND is well calibrated.
The model recipe itself is in nbaline/recipes.py (stat_recipe).
"""
import argparse
import json
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from nbaline import features as F
from nbaline.modeling import Config, Pipeline, is_up_to_date, load_model
from nbaline.paths import EXPERIMENTS as OUT, MODELS, STATS_META, stat_model
from nbaline.recipes import stat_baseline, stat_recipe

TUNE_FOLDS, HOLDOUT = [2023, 2024], 2025
MAX_CALIBRATION_ERROR = 0.03  # "said 60%" may be off from "happened X%" by this much on average, no more
# Final models trained side by side, each in its own process. With an NVIDIA GPU they share it
# (modeling.training_device); on the CPU each uses every thread. (Fewer CPU threads each would be
# faster still, but the thread count changes the trees slightly.)
TRAIN_AT_ONCE = 4
NAMES = {k: F.STAT_NAMES[k] for k in F.OTHER_STATS}


def line_metrics(p: np.ndarray, over: np.ndarray) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = sum(abs(p[bins == b].mean() - over[bins == b].mean()) * (bins == b).mean()
              for b in range(10) if (bins == b).any())
    return dict(brier=float(np.mean((p - over) ** 2)), ece=float(ece))


def dist_options(key: str) -> list[str]:
    """The uncertainty methods a stat can choose between in testing (the last one is the default)."""
    if key == "FS":
        return ["hetero"]          # fantasy score can go negative: not a count
    if key in F.YES_NO_STATS:
        return ["yes_no"]          # happens or doesn't: the model's output is the chance
    return ["hetero", "nbinom"]    # counts: nbinom won for every counting stat tested


def score_fold(key, df, S, dists):
    df = df[df[f"Y_{key}"].notna()]
    tr, te = df[df["SEASON"] < S], df[df["SEASON"] == S]
    y = te[f"Y_{key}"].to_numpy(float)
    line = np.floor(te[f"{key}_EWM"].to_numpy(float)) + 0.5
    over = (y > line).astype(float)
    out = {}
    for name, cfg in (("model", stat_recipe(key)), ("base", stat_baseline(key, "both"))):
        pipe = Pipeline(cfg).fit(tr)
        for d in dists:
            mu, p = pipe.prob_over(te, line, d)
            out[(name, d)] = dict(mae=float(np.mean(np.abs(y - mu))), **line_metrics(p, over),
                                  ece_off=off_line_error(pipe, te, y, line, d))
    return out


def off_line_error(pipe, te, y, line, dist) -> float:
    """Calibration error on lines 2 below and 2 above the usual one, where Goblin and Demon lines sit.
    It shows whether the spread is right, not just the middle. (Blank for yes/no stats: one line only.)"""
    if dist == "yes_no":
        return float("nan")
    errors = []
    for shift in (-2, 2):
        shifted = np.maximum(line + shift, 0.5)
        errors.append(line_metrics(pipe.prob_over(te, shifted, dist)[1], (y > shifted).astype(float))["ece"])
    return float(np.mean(errors))


def evaluate(redo: bool = False, only: list | None = None):
    """Test every stat that hasn't been tested yet (all of them with redo=True, or just `only`)."""
    df = F.load_features()
    OUT.mkdir(exist_ok=True)
    part = OUT / "stat_models_partial.csv"  # saved after every stat, so a stopped run picks up where it left off
    final = OUT / "stat_models.csv"
    todo = only or F.OTHER_STATS
    read = lambda f: {r["key"]: r for r in pd.read_csv(f).to_dict("records") if r["key"] in NAMES}
    rows = read(final) if final.exists() else {}
    if redo:  # forget the old results for these stats (other stats keep theirs)
        rows = {k: r for k, r in rows.items() if k not in todo}
    if part.exists():  # a run that was stopped: its finished stats count as done
        rows.update(read(part))
    for key in todo:
        if key in rows:
            print(f"{NAMES[key]:<22} already tested", flush=True)
            continue
        dists = dist_options(key)
        t0 = time.time()
        tune = [score_fold(key, df, S, dists) for S in TUNE_FOLDS]
        on_tune = lambda d, metric: np.mean([f[("model", d)][metric] for f in tune])
        # a method must be well calibrated on the tuning seasons to be chosen, however good its Brier
        # (free throw attempts: the count method scores better but runs ~3 points low at the usual line)
        calibrated = [d for d in dists if on_tune(d, "ece") <= MAX_CALIBRATION_ERROR] or dists
        best = min(calibrated, key=lambda d: on_tune(d, "brier"))
        hold = score_fold(key, df, HOLDOUT, [best])
        m, b = hold[("model", best)], hold[("base", best)]
        reliable = (m["brier"] < b["brier"]) and (m["ece"] <= MAX_CALIBRATION_ERROR)
        r = rows[key] = dict(key=key, stat=NAMES[key], dist=best, mae=m["mae"], mae_base=b["mae"],
                             brier=m["brier"], brier_base=b["brier"], ece=m["ece"], ece_off=m["ece_off"],
                             reliable=reliable, secs=round(time.time() - t0))
        print(f"{NAMES[key]:<22} dist={best:<7} MAE {r['mae']:.2f} (base {r['mae_base']:.2f})  "
              f"Brier {r['brier']:.4f} (base {r['brier_base']:.4f})  calib.err {r['ece']:.3f}  "
              f"off-line calib.err {r['ece_off']:.3f}  "
              f"{'RELIABLE' if reliable else 'not reliable'}  [{r['secs']}s]", flush=True)
        pd.DataFrame(rows.values()).to_csv(part, index=False)
    order = {k: i for i, k in enumerate(F.OTHER_STATS)}
    res = pd.DataFrame(rows.values()).sort_values("key", key=lambda s: s.map(order))
    res.to_csv(OUT / "stat_models.csv", index=False)
    part.unlink(missing_ok=True)
    print("\nSaved experiments/stat_models.csv")


def final_recipe(key: str, ev: pd.DataFrame) -> tuple[Config, dict]:
    """A stat's final model settings, and what models/stats.json says about it."""
    if key in ev.index:
        e = ev.loc[key]
        info = dict(dist=e["dist"], reliable=bool(e["reliable"]), tested=True,
                    holdout_brier=round(float(e["brier"]), 4), baseline_brier=round(float(e["brier_base"]), 4),
                    calibration_error=round(float(e["ece"]), 4))
    else:  # not tested: the setting every counting stat chose in testing, and marked as untested
        info = dict(dist=dist_options(key)[-1], reliable=False, tested=False)
    return stat_recipe(key, info["dist"]), info


def train(keys: list | None = None):
    """Train the final model for every tested stat (or just `keys`). A model that already learned
    from exactly this data is kept as it is; the others are trained TRAIN_AT_ONCE at a time."""
    ev = OUT / "stat_models.csv"
    if not ev.exists():
        sys.exit("Run  python stat_models.py --evaluate  first (it chooses each stat's settings).")
    ev = pd.read_csv(ev).set_index("key")
    df = F.load_features()   # also rebuilds the saved inputs if the box scores changed, before the workers read them
    inner = sorted(df["SEASON"].unique())[-2]
    MODELS.mkdir(exist_ok=True)
    summary = json.loads(STATS_META.read_text()) if STATS_META.exists() else {}
    todo = []
    for key in keys or [k for k in F.OTHER_STATS if k in ev.index or k in summary]:
        cfg, info = final_recipe(key, ev)
        if is_up_to_date(load_model(stat_model(key)), cfg, df, inner):
            trained_on = summary.get(key, {}).get("trained_on", str(date.today()))
            summary[key] = dict(stat=NAMES[key], **info, trained_on=trained_on)
            print(f"  {NAMES[key]:<22} up to date (no new data since it was trained)", flush=True)
        else:
            todo.append((key, cfg, info))
    STATS_META.write_text(json.dumps(summary, indent=2))
    del df   # each worker loads its own copy

    if todo:
        with ProcessPoolExecutor(min(TRAIN_AT_ONCE, len(todo)), initializer=_load_training_rows) as pool:
            jobs = {pool.submit(_fit_and_save, key, cfg, inner): (key, info) for key, cfg, info in todo}
            for job in as_completed(jobs):
                key, info = jobs[job]
                secs, reused = job.result()
                summary[key] = dict(stat=NAMES[key], **info, trained_on=str(date.today()))
                STATS_META.write_text(json.dumps(summary, indent=2))  # after each stat, so a stopped run keeps what's done
                print(f"  {NAMES[key]:<22} trained ({secs}s{', calibration reused' if reused else ''})", flush=True)
    print("Saved models/stat_*.pkl and models/stats.json")


def ab_test(group: str, folds: list[int], keys: list | None = None):
    """Do extra inputs help the stat models? Each stat's final settings with and without a feature group
    (EXTRA_GROUPS), trained on the seasons before each fold and scored on it: Brier and calibration error
    at the usual line, and MAE. A change counts as real when its 95% interval (resampling whole nights)
    leaves out zero. Saved to experiments/stat_ab_<group>.csv."""
    extra = EXTRA_GROUPS[group]
    ev = pd.read_csv(OUT / "stat_models.csv").set_index("key")
    keys = keys or [k for k in F.OTHER_STATS if k in ev.index]
    jobs = [(key, S, with_extra) for key in keys for S in folds for with_extra in (False, True)]
    F.load_features()   # rebuilds the saved inputs if they're stale, before the workers each read them
    scored = {}   # (key, fold, with_extra) -> each test row's squared error and night
    with ProcessPoolExecutor(TRAIN_AT_ONCE, initializer=_load_training_rows) as pool:
        futures = {pool.submit(_ab_fold, key, S, extra, with_extra, ev.loc[key]["dist"]): (key, S, with_extra)
                   for key, S, with_extra in jobs}
        for job in as_completed(futures):
            key, S, with_extra = futures[job]
            scored[(key, S, with_extra)] = job.result()
            print(f"  {NAMES[key]:<22} {S} {'with' if with_extra else 'without'} {group}: "
                  f"Brier {scored[(key, S, with_extra)]['brier']:.4f}", flush=True)
    rows = []
    for key in keys:
        old = [scored[(key, S, False)] for S in folds]
        new = [scored[(key, S, True)] for S in folds]
        diff = np.concatenate([n["sq"] - o["sq"] for o, n in zip(old, new)])
        nights = np.concatenate([o["night"] for o in old])
        lo, hi = night_bootstrap(diff, nights)
        n = sum(o["n"] for o in old)
        avg = lambda runs, m: sum(r[m] * r["n"] for r in runs) / n
        rows.append(dict(key=key, stat=NAMES[key], brier=avg(old, "brier"), brier_new=avg(new, "brier"),
                         change=float(diff.mean()), ci_low=lo, ci_high=hi, ece=avg(old, "ece"), ece_new=avg(new, "ece"),
                         mae=avg(old, "mae"), mae_new=avg(new, "mae"), n=n,
                         verdict="better (real)" if hi < 0 else "worse (real)" if lo > 0 else "no clear difference"))
    res = pd.DataFrame(rows).sort_values("change")
    res.to_csv(OUT / f"stat_ab_{group}.csv", index=False)
    print("\n" + res[["stat", "brier", "brier_new", "change", "ci_low", "ci_high", "ece_new", "verdict"]]
          .to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print(f"\nSaved experiments/stat_ab_{group}.csv")


def night_bootstrap(diff: np.ndarray, nights: np.ndarray, draws: int = 1000) -> tuple[float, float]:
    """95% interval of the average change, resampling whole nights (players in one game share its luck)."""
    codes, idx = np.unique(nights, return_inverse=True)
    sums, counts = np.bincount(idx, diff), np.bincount(idx)
    rng = np.random.default_rng(0)
    pick = rng.integers(0, len(codes), (draws, len(codes)))
    means = sums[pick].sum(axis=1) / counts[pick].sum(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


EXTRA_GROUPS = {"lineups": F.LINEUPS, "tracking": F.TRACKING, "shots": F.SHOTS}


def _ab_fold(key: str, S: int, extra: list, with_extra: bool, dist: str) -> dict:
    """In a worker: one stat, one fold, with or without the extra inputs (whatever its recipe has)."""
    df = _ROWS[_ROWS[f"Y_{key}"].notna()]
    tr, te = df[df["SEASON"] < S], df[df["SEASON"] == S]
    y = te[f"Y_{key}"].to_numpy(float)
    line = np.floor(te[f"{key}_EWM"].to_numpy(float)) + 0.5
    cfg = stat_recipe(key, dist)
    base = [f for f in cfg.features if f not in extra]
    cfg = replace(cfg, features=base + extra if with_extra else base)
    mu, p = Pipeline(cfg).fit(tr).prob_over(te, line, dist)
    over = (y > line).astype(float)
    return dict(n=len(te), mae=float(np.mean(np.abs(y - mu))), **line_metrics(p, over),
                sq=(np.clip(p, 1e-4, 1 - 1e-4) - over) ** 2, night=te["GAME_DATE"].astype(str).to_numpy())


_ROWS = None   # a training worker's own copy of the training rows


def _load_training_rows():
    global _ROWS
    _ROWS = F.load_features()


def _fit_and_save(key: str, cfg: Config, inner: int) -> tuple[int, bool]:
    """In a training worker: fit one stat's final model and save it. Returns (seconds, whether
    early stopping and calibration were reused from the model it replaces)."""
    t0 = time.time()
    pipe = Pipeline(cfg).fit(_ROWS, inner=inner, previous=load_model(stat_model(key)))
    with open(stat_model(key), "wb") as f:
        pickle.dump(pipe, f)
    return round(time.time() - t0), pipe.reused_inner_fit


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--evaluate", action="store_true", help="test every stat not tested yet")
    ap.add_argument("--redo", action="store_true", help="with --evaluate: test all stats again")
    ap.add_argument("--train", action="store_true", help="train every tested stat")
    ap.add_argument("--only", help="comma-separated keys, e.g. XFGA,XFTM (just these stats)")
    ap.add_argument("--ab", choices=sorted(EXTRA_GROUPS), help="test extra inputs: with vs. without, e.g. lineups")
    ap.add_argument("--folds", default="2024,2025", help="with --ab: seasons to test on")
    a = ap.parse_args()
    only = a.only.split(",") if a.only else None
    if a.ab:
        ab_test(a.ab, [int(s) for s in a.folds.split(",")], only)
    if a.evaluate:
        evaluate(redo=a.redo, only=only)
    if a.train:
        train(only)
    if not (a.evaluate or a.train or a.ab):
        ap.print_help()
