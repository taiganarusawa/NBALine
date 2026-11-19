"""Player tracking from NBA.com: the chances behind the box score, per player per game.

A box score says a player had 3 assists; tracking says he made 9 passes that led to a shot. NBA.com's
camera-tracking dashboards (free, no login: the ones behind its "Player Tracking" pages) can be asked for
a single day, which gives each player's numbers for his one game that day. Checked against our box
scores for Nov 15, 2017: the same players, and every player's assists matched. Four categories:

    Passing      passes made, potential assists (passes the receiver shot from: an assist if it went in),
                 secondary assists (the pass before the assist), free-throw assists
    Rebounding   rebound chances (he was near the ball when it was rebounded), offensive and defensive
    Drives       drives to the basket, and the shots, free throws, points, passes and turnovers from them
    Possessions  touches, seconds holding the ball, touches in the paint, the post and at the elbow

    data/tracking.csv   one row per player per game day: GAME_DATE, PLAYER_ID, TEAM_ID + COLUMNS below

    python -m nbaline.tracking      # download every game day that isn't saved yet (~2 hours the first time)
"""
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import pandas as pd
from nba_api.stats.endpoints import leaguedashptstats

from .paths import PLAYER_LOGS, TRACKING

# NBA.com's column names, per category. Counts only: rates are worked out from them in features.py.
MEASURES = {
    "Passing": ["PASSES_MADE", "POTENTIAL_AST", "SECONDARY_AST", "FT_AST"],
    "Rebounding": ["OREB_CHANCES", "DREB_CHANCES", "REB_CHANCES"],
    "Drives": ["DRIVES", "DRIVE_FGA", "DRIVE_FTA", "DRIVE_PTS", "DRIVE_PASSES", "DRIVE_TOV"],
    "Possessions": ["TOUCHES", "TIME_OF_POSS", "PAINT_TOUCHES", "POST_TOUCHES", "ELBOW_TOUCHES"],
}
COLUMNS = [c for cols in MEASURES.values() for c in cols]
FIRST_SEASON = 2017     # the first season the models train on
RECHECK_DAYS = 7        # a recent day missing a game's worth of players (MISSING_GAME) is downloaded again
MISSING_GAME = 5        # tracking can leave out a player or two with a few seconds played; a whole game is ~20
PAUSE = 0.6             # seconds between requests: be polite to stats.nba.com


def season_of(day: date) -> str:
    """NBA season of a game day: Nov 15, 2017 -> "2017-18"."""
    start = day.year if day.month >= 8 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def _measure(day: date, measure: str) -> pd.DataFrame:
    when = f"{day:%m/%d/%Y}"
    for attempt in range(3):
        try:
            return leaguedashptstats.LeagueDashPtStats(
                season=season_of(day), season_type_all_star="Regular Season", player_or_team="Player",
                pt_measure_type=measure, per_mode_simple="Totals", date_from_nullable=when, date_to_nullable=when,
                timeout=60).get_data_frames()[0]
        except Exception:   # stats.nba.com drops requests now and then
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Couldn't download {measure} tracking for {day}")


def fetch_day(day: date) -> pd.DataFrame:
    """Every player's tracking numbers for that day's games. A player missing from one category (the
    rebounding one leaves out players who had no rebound chance) gets 0 there."""
    parts = []
    for measure, cols in MEASURES.items():
        parts.append(_measure(day, measure)[["PLAYER_ID", "TEAM_ID", *cols]])
        time.sleep(PAUSE)
    out = pd.concat(p[["PLAYER_ID", "TEAM_ID"]] for p in parts).drop_duplicates("PLAYER_ID")
    for p in parts:
        out = out.merge(p.drop(columns="TEAM_ID"), on="PLAYER_ID", how="left")
    out[COLUMNS] = out[COLUMNS].fillna(0)
    out.insert(0, "GAME_DATE", day.isoformat())
    return out


def load() -> pd.DataFrame:
    """Every saved row (empty, with the right columns, if nothing is saved yet)."""
    if not TRACKING.exists():
        return pd.DataFrame(columns=["GAME_DATE", "PLAYER_ID", "TEAM_ID", *COLUMNS])
    return pd.read_csv(TRACKING)


def update(save_every: int = 25) -> int:
    """Download every tracking day that isn't saved yet (update_days). Returns how many were downloaded."""
    return update_days(TRACKING, fetch_day, load, "tracking", save_every)


def update_days(path: Path, fetch: Callable[[date], pd.DataFrame], saved_rows: Callable[[], pd.DataFrame],
                label: str, save_every: int = 25) -> int:
    """Download every game day in the box scores after the last one saved in `path`, and any recent day
    saved without one of its games (still being played when it was downloaded). Saves as it goes, so a
    stopped run picks up where it left off. A few old days have no tracking at NBA.com (the 2020 restart,
    Aug 1-14, and two single days): they stay missing rather than being asked for again every time.
    Used for tracking and hustle stats (hustle.py), which both come one day at a time.
    Returns how many days were downloaded."""
    if not PLAYER_LOGS.exists():
        return 0
    logs = pd.read_csv(PLAYER_LOGS, usecols=["GAME_DATE", "SEASON_ID"])
    logs = logs[logs["SEASON_ID"].astype(str).str[1:].astype(int) >= FIRST_SEASON]
    played = logs.groupby("GAME_DATE").size()
    saved = saved_rows()
    have = saved.groupby("GAME_DATE").size()
    recent = (date.today() - timedelta(days=RECHECK_DAYS)).isoformat()
    last = max(have.index, default="")
    todo = [d for d, n in played.items()
            if d > last or (d >= recent and have.get(d, 0) <= n - MISSING_GAME)]
    done = []
    for i, d in enumerate(todo, 1):
        done.append(fetch(date.fromisoformat(d)))
        if i % save_every == 0 or i == len(todo):
            new = pd.concat(done)
            saved = pd.concat([saved[~saved["GAME_DATE"].isin(set(new["GAME_DATE"]))], new])
            saved.sort_values(["GAME_DATE", "TEAM_ID", "PLAYER_ID"]).to_csv(path, index=False)
            if len(todo) > save_every:
                print(f"    {label}: {i} of {len(todo)} days ({d})", flush=True)
    return len(done)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = datetime.now()
    n = update()
    print(f"Saved {TRACKING.name}: {n} day(s) downloaded ({(datetime.now() - t0).seconds}s)")
