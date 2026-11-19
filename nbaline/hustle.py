"""Hustle stats from NBA.com: the effort plays a box score doesn't count, per player per game.

NBA.com's hustle dashboard (free, no login: the one behind its "Hustle" pages) can be asked for a single
day, which gives each player's numbers for his one game that day, like the tracking dashboards
(tracking.py). One request per game day.

    contested shots   shots he contested (2s and 3s)
    deflections       passes and dribbles he got a hand on
    charges drawn
    screen assists    screens that freed a teammate for a made shot, and the points from them
    loose balls       loose balls he recovered, on offense and defense
    box outs          times he boxed out, on offense and defense, and how many led to a rebound for him
                      or his team

    data/hustle.csv   one row per player per game day: GAME_DATE, PLAYER_ID, TEAM_ID + COLUMNS below

    python -m nbaline.hustle      # download every game day that isn't saved yet (~30 minutes the first time)
"""
import sys
import time
from datetime import date, datetime

import pandas as pd
from nba_api.stats.endpoints import leaguehustlestatsplayer

from .paths import HUSTLE
from .tracking import PAUSE, season_of, update_days

# NBA.com's column names. Counts only: rates are worked out from them.
COLUMNS = ["CONTESTED_SHOTS", "CONTESTED_SHOTS_2PT", "CONTESTED_SHOTS_3PT", "DEFLECTIONS", "CHARGES_DRAWN",
           "SCREEN_ASSISTS", "SCREEN_AST_PTS", "OFF_LOOSE_BALLS_RECOVERED", "DEF_LOOSE_BALLS_RECOVERED",
           "LOOSE_BALLS_RECOVERED", "OFF_BOXOUTS", "DEF_BOXOUTS", "BOX_OUTS", "BOX_OUT_PLAYER_REBS",
           "BOX_OUT_PLAYER_TEAM_REBS"]


def fetch_day(day: date) -> pd.DataFrame:
    """Every player's hustle stats for that day's games."""
    when = f"{day:%m/%d/%Y}"
    for attempt in range(3):
        try:
            df = leaguehustlestatsplayer.LeagueHustleStatsPlayer(
                season=season_of(day), season_type_all_star="Regular Season", per_mode_time="Totals",
                date_from_nullable=when, date_to_nullable=when, timeout=60).get_data_frames()[0]
            break
        except Exception:   # stats.nba.com drops requests now and then
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"Couldn't download hustle stats for {day}")
    time.sleep(PAUSE)
    out = df[["PLAYER_ID", "TEAM_ID", *COLUMNS]].copy()
    out.insert(0, "GAME_DATE", day.isoformat())
    return out


def load() -> pd.DataFrame:
    """Every saved row (empty, with the right columns, if nothing is saved yet)."""
    if not HUSTLE.exists():
        return pd.DataFrame(columns=["GAME_DATE", "PLAYER_ID", "TEAM_ID", *COLUMNS]).astype(
            {"PLAYER_ID": int, "TEAM_ID": int, **{c: float for c in COLUMNS}})
    return pd.read_csv(HUSTLE)


def update(save_every: int = 25) -> int:
    """Download every game day that isn't saved yet. Returns how many were downloaded."""
    return update_days(HUSTLE, fetch_day, load, "hustle", save_every)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = datetime.now()
    n = update()
    print(f"Saved {HUSTLE.name}: {n} day(s) downloaded ({(datetime.now() - t0).seconds}s)")
