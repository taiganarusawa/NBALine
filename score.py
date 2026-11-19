"""Grade everything against what actually happened: predictions made with predict.py, and the web
app's PrizePicks entries and checked lines.

    python fetch_data.py     # pull the latest results first
    python score.py

The key test is "Model vs. market": both we and the sportsbook give a probability for
every over. The Brier score (lower = better) says whose probabilities were closer to
reality. If ours is not lower than the book's over a few hundred lines, the model has
no real edge, whatever the win rate looks like over a small sample.
"""
import sys

import numpy as np
import pandas as pd

from nbaline import features as F
from nbaline.evaluate import calibration_table
from nbaline.paths import PREDICTIONS_LOG as LOG
from nbaline.pickem import store


def payout(odds: int) -> float:
    """Profit on a 1-unit winning bet."""
    return 100 / -odds if odds < 0 else odds / 100


def grade_pickem():
    """Grade the web app's PrizePicks entries and checked lines (they're saved in data/prizepicks.db)."""
    graded = store.grade_all()
    s = store.summary()["entries"]
    print(f"PrizePicks: graded {graded['picks']} pick(s) and {graded['entries']} entr{'y' if graded['entries'] == 1 else 'ies'}. "
          f"Entries {s['won']} won, {s['partial']} partial, {s['lost']} lost, {s['open']} open | profit {s['profit']:+.2f}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console + accented names
    grade_pickem()
    print()
    grade_predictions_log()


def grade_predictions_log():
    """Grade predictions_log.csv (predict.py) and compare the model with the sportsbook."""
    if not LOG.exists():
        return print("No predictions_log.csv yet. Make some predictions with predict.py first.")
    log = pd.read_csv(LOG, dtype={"game_id": str})
    log = log.drop_duplicates(["player_id", "game_date", "line"], keep="last")
    p, t = F.load_raw()
    last_data = p["GAME_DATE"].max()
    finished = set(t["GAME_ID"].astype(str).str.zfill(10))  # games with a final result
    actual = p[["PLAYER_ID", "GAME_DATE", "PTS"]].assign(game_date=p["GAME_DATE"].dt.strftime("%Y-%m-%d"))
    df = log.merge(actual.rename(columns={"PLAYER_ID": "player_id"})[["player_id", "game_date", "PTS"]],
                   on=["player_id", "game_date"], how="left")
    # A game counts as over only if it has a final result; then a missing player row means he didn't play.
    gid = df["game_id"].astype(str).str.split(".").str[0].str.zfill(10) if "game_id" in df else pd.Series("", index=df.index)
    known = gid.str.match(r"^\d{10}$") & (gid != "0000000000")
    over = np.where(known, gid.isin(finished), pd.to_datetime(df["game_date"]) <= last_data)
    df["status"] = np.where(df["PTS"].notna(), "graded", np.where(over, "void (did not play)", "pending"))
    print(df["status"].value_counts().to_string(), "\n")

    g = df[(df["status"] == "graded") & (df["PTS"] != df["line"])].copy()  # drop pushes
    if g.empty:
        return print(f"Nothing to grade yet (results through {last_data.date()}).")
    g["over"] = (g["PTS"] > g["line"]).astype(float)

    n = len(g)
    if "pregame" in g and (g["pregame"] == 0).any():
        print(f"Note: {(g['pregame'] == 0).sum()} of these were predicted after tip-off "
              f"(no in-game info was used, but they couldn't have been bet pre-game).")
    ours = np.mean((g["p_over"] - g["over"]) ** 2)
    book = np.mean((g["book_fair_over"] - g["over"]) ** 2)
    print(f"Graded lines: {n}")
    print(f"Projection miss (MAE)     : {np.mean(np.abs(g['PTS'] - g['proj'])):.2f} pts")
    print(f"Inside 10-90% range       : {np.mean((g['PTS'] >= g['q10']) & (g['PTS'] <= g['q90'])):.0%} (should be ~80%)")
    print(f"Brier, model              : {ours:.4f}")
    print(f"Brier, sportsbook (no-vig): {book:.4f}   -> {'MODEL closer' if ours < book else 'BOOK closer'}")

    bets = g[g["verdict"] != "NO EDGE"].copy()
    if len(bets):
        side_over = bets["verdict"] == "LEAN OVER"
        won = np.where(side_over, bets["over"] == 1, bets["over"] == 0)
        odds = np.where(side_over, bets["over_odds"], bets["under_odds"])
        profit = np.where(won, [payout(o) for o in odds], -1.0)
        se = np.sqrt(won.mean() * (1 - won.mean()) / len(won))
        print(f"\nLeans: {len(bets)}  record {won.sum()}-{len(won) - won.sum()}  hit rate {won.mean():.1%} (+/- {1.96 * se:.1%})")
        print(f"Profit at logged odds: {profit.sum():+.2f} units  (ROI {profit.mean():+.1%} per bet)")
    if n >= 30:
        print("\nCalibration:")
        print(calibration_table(g["p_over"].to_numpy(), g["over"].to_numpy()).to_string(
            float_format=lambda x: f"{x:.1%}"))
    if n < 300:
        print(f"\nOnly {n} graded lines: still mostly luck. Judge the model after ~300+.")


if __name__ == "__main__":
    main()
