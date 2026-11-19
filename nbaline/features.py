"""Turn raw game logs into model features.

Every feature for a game is computed ONLY from games played before it
(that's what the shift(1) in lag() does). Without this, the model would
"see the future" in training and look far better than it really is.
"""
import functools
from pathlib import Path

import numpy as np
import pandas as pd

from . import hustle, lineups, shots, tracking
from .paths import (DUNKS, FEATURES_CACHE, HUSTLE as HUSTLE_FILE, PLAYER_LOGS, SHOTS as SHOTS_FILE, STARTERS,
                    TEAM_LOGS, TRACKING as TRACKING_FILE)

# ---- Feature sets. v1 = the original prototype; v2 adds groups that are tested one at a time.
V1 = [
    "PTS_L3", "PTS_L5", "PTS_L10", "PTS_L20", "PTS_EWM", "PTS_STD_L10",
    "PTS_SEASON", "PTS_PREV_SEASON",
    "MIN_L5", "MIN_L10", "MIN_SEASON",
    "FGA_L10", "FTA_L10", "FG3A_L10", "USG_L10",
    "GP_SEASON", "REST_DAYS", "B2B", "HOME",
    "OWN_PACE_L10", "OPP_PACE_L10", "OPP_DEF_RTG_L10",
    "MISSING_FGA", "MISSING_COUNT",
]
GROUPS = {
    "rates": ["PPM_L10", "PPM_SEASON", "TS_L10", "TS_L40", "USG_SHARE_L10"],
    "long": ["PTS_L40", "PTS_EWM15"],
    "minutes": ["MIN_L3", "MIN_EWM", "MIN_STD_L10", "GAMES_MISSED"],
    "game_ctx": ["OWN_OFF_RTG_L10", "OWN_NET_RTG_L10", "OPP_OFF_RTG_L10", "OPP_NET_RTG_L10",
                 "NET_DIFF", "EXP_TEAM_PTS", "OPP_REST", "OPP_B2B"],
    "absences": ["MISSING_MIN", "OPP_MISSING_FGA", "OPP_MISSING_COUNT"],
    "matchup": ["OPP_POE_L15", "OPP_POE_TYPE"],
}
V2 = V1 + [f for g in GROUPS.values() for f in g]
# Free extras from the analysts' reasoning, tested separately before any model uses them
EXTRA = {
    "close_min": ["MIN_CLOSE_L10", "BLOWOUT_L5", "MIN_CLOSE_GAP"],
    "wo_splits": ["WO_GP", "WO_MIN_DIFF", "WO_PPM_DIFF", "WO_FGA_PM_DIFF", "WO_REB_PM_DIFF", "WO_AST_PM_DIFF"],
    "opp_allow": ["OPP_FTA_ALLOW_L10", "OPP_FG3A_ALLOW_L10", "OPP_AST_ALLOW_L10", "OPP_TOV_FORCED_L10",
                  "OPP_OREB_ALLOW_L10"],
}
# Starting lineups (lineups.py, NBA.com, 2023-24 on): tonight's role and the minutes that usually come
# with it. Blank before 2023-24 and before tonight's lineup is posted. Tested on its own (E10).
LINEUPS = ["STARTING", "START_RATE_L10", "ROLE_CHANGE", "MIN_ROLE_L20", "MIN_ROLE_GAP"]
# Player tracking (tracking.py, NBA.com's camera tracking, every season): the chances behind the box score.
# Per minute over his last 10 games with tracking, and how often chances turn into the stat over his last
# 20 (a noisier rate, so a longer window). Tested on its own (E11); the stats in WITH_TRACKING now use the
# TRACKING_REL version below.
TRACKING_PER_MIN = {"POT_AST": "POTENTIAL_AST", "PASSES": "PASSES_MADE", "REB_CHANCES": "REB_CHANCES",
                    "OREB_CHANCES": "OREB_CHANCES", "DREB_CHANCES": "DREB_CHANCES", "DRIVES": "DRIVES",
                    "DRIVE_FTA": "DRIVE_FTA", "TOUCHES": "TOUCHES", "PAINT_TOUCHES": "PAINT_TOUCHES",
                    "TIME_OF_POSS": "TIME_OF_POSS"}
TRACKING = [f"{k}_PM_L10" for k in TRACKING_PER_MIN] + ["AST_PER_POT_L20", "REB_PER_CHANCE_L20", "TOV_PER_TOUCH_L20"]
# The same inputs measured against the league under the same counting (league_tracking_rates), because NBA.com
# has changed how it counts several of them: 1.0 = the league's rate. Tested against TRACKING
# (stat_models.py --ab tracking_rel, TRAINING.md 4h): the stats in WITH_TRACKING use this version.
CONVERSIONS = {"AST_PER_POT": ("AST", "POTENTIAL_AST"), "REB_PER_CHANCE": ("REB", "REB_CHANCES"),
               "TOV_PER_TOUCH": ("TOV", "TOUCHES")}   # name -> (what the chances became, the chances)
TRACKING_REL = [f"{k}_REL_L10" for k in TRACKING_PER_MIN] + [f"{k}_REL_L20" for k in CONVERSIONS]
LEAGUE_MIN_GAMES = 10   # a day's league rates pool it with the days just before it (same season) up to 10+ games
# Shot profile (shots.py, NBA.com's shot charts, every season): where and how he shoots. Attempts per minute
# in each zone and of self-created jumpers, and his average shot distance, over his last 10 games; over his
# last 20, his shooting at the rim, the points per shot his zones would score at league-average accuracy,
# and how far above or below that he shot. Tested on its own (E12): used by the stats in WITH_SHOTS.
SHOT_KINDS = [*shots.ZONES, "SELF"]
SHOTS = ([f"{k}_FGA_PM_L10" for k in SHOT_KINDS]
         + ["SHOT_FEET_L10", "RIM_PCT_L20", "XPTS_PER_SHOT_L20", "SHOT_MAKING_L20"])
SHOT_COLS = [c for c in shots.COLUMNS if c != "DUNKS"]   # each game's counts; DUNKS comes from dunks.csv
LEAGUE_WINDOW = "365D"   # league-wide accuracy in each zone: over the year before each game day
# Hustle stats (hustle.py, logged by people at each game, every season): deflections, contested 2s and 3s,
# screen assists, loose balls and box outs, per minute against the league's rate under the same counting (like
# TRACKING_REL), over his last 10 games. Box outs only from 2022-23: before that every box out was logged, not
# just the ones that won the ball. Charges are too rare to use (TRAINING.md 4i). Tested on its own (E13):
# used by the stats in WITH_HUSTLE.
HUSTLE_PER_MIN = {"DEFLECTIONS": "DEFLECTIONS", "CONTESTED_2PT": "CONTESTED_SHOTS_2PT",
                  "CONTESTED_3PT": "CONTESTED_SHOTS_3PT", "SCREEN_AST": "SCREEN_ASSISTS",
                  "LOOSE_BALLS": "LOOSE_BALLS_RECOVERED", "BOX_OUTS": "BOX_OUTS"}
HUSTLE = [f"{k}_REL_L10" for k in HUSTLE_PER_MIN]
BOX_OUTS_FROM = 2022    # the first season box outs were logged the way they are now
# Coming back from an absence (box scores): minutes run 12-24% short in the first game back and catch up
# over about 3 games, more slowly after a longer absence (TRAINING.md 4j). GAMES_MISSED only flags the first
# game back, so these follow the whole return: how many games since, how long he was out, his minutes before
# it and since, and his last game's minutes. Tested on its own (E14): used by Points (recipes.points_recipe)
# and the stats in WITH_RETURN.
RETURN = ["GAMES_SINCE_RETURN", "ABSENCE_GAMES", "PRE_ABSENCE_MIN", "MIN_SINCE_RETURN", "RETURN_RECOVERY", "MIN_L1"]
RETURN_AFTER = 2        # missing this many team games or more in a row starts a return
RETURN_WINDOW = 10      # the RETURN inputs follow the first 10 games back; after that he counts as settled
FEATURES = V1  # overwritten by the trained model's saved feature list at prediction time

LABELS = {
    "PTS_L3": "Points, last 3 games", "PTS_L5": "Points, last 5 games",
    "PTS_L10": "Points, last 10 games", "PTS_L20": "Points, last 20 games",
    "PTS_L40": "Points, last 40 games", "PTS_EWM": "Recent-weighted scoring average",
    "PTS_EWM15": "Long-run weighted scoring average", "PTS_STD_L10": "Scoring volatility (last 10)",
    "PTS_SEASON": "Points, season average", "PTS_PREV_SEASON": "Points, last season average",
    "MIN_L3": "Minutes, last 3 games", "MIN_L5": "Minutes, last 5 games", "MIN_L10": "Minutes, last 10 games",
    "MIN_SEASON": "Minutes, season average", "MIN_EWM": "Recent-weighted minutes",
    "MIN_STD_L10": "Minutes volatility (last 10)", "GAMES_MISSED": "Team games missed before this one",
    "FGA_L10": "Shot attempts, last 10", "FTA_L10": "Free-throw attempts, last 10",
    "FG3A_L10": "3-pt attempts, last 10", "USG_L10": "Usage per minute, last 10",
    "USG_SHARE_L10": "Share of team's possessions used (last 10)",
    "PPM_L10": "Points per minute, last 10", "PPM_SEASON": "Points per minute, season",
    "TS_L10": "Shooting efficiency (TS%), last 10", "TS_L40": "Shooting efficiency (TS%), last 40",
    "GP_SEASON": "Games played this season", "REST_DAYS": "Days of rest", "B2B": "Back-to-back",
    "HOME": "Home game", "OWN_PACE_L10": "Own team pace (last 10)",
    "OPP_PACE_L10": "Opponent pace (last 10)", "OPP_DEF_RTG_L10": "Opponent points allowed per 100 poss (last 10)",
    "OWN_OFF_RTG_L10": "Own team offense per 100 poss (last 10)", "OWN_NET_RTG_L10": "Own team net rating (last 10)",
    "OPP_OFF_RTG_L10": "Opponent offense per 100 poss (last 10)", "OPP_NET_RTG_L10": "Opponent net rating (last 10)",
    "NET_DIFF": "Team strength gap (blowout risk)", "EXP_TEAM_PTS": "Expected team points",
    "OPP_REST": "Opponent days of rest", "OPP_B2B": "Opponent on back-to-back",
    "MISSING_FGA": "Shot attempts freed up by absent teammates", "MISSING_COUNT": "Rotation teammates out",
    "MISSING_MIN": "Minutes freed up by absent teammates",
    "OPP_MISSING_FGA": "Opponent shot attempts missing", "OPP_MISSING_COUNT": "Opponent rotation players out",
    "OPP_POE_L15": "Opponent: points allowed vs. players' own averages (last 15)",
    "OPP_POE_TYPE": "Opponent: points allowed vs. averages, this player type (last 15)",
    "MIN_CLOSE_L10": "Minutes in close games (last 10)", "BLOWOUT_L5": "Share of recent games that were blowouts",
    "MIN_CLOSE_GAP": "Extra minutes he plays in close games vs. lately",
    "WO_GP": "Past games without tonight's missing teammates",
    "WO_MIN_DIFF": "Extra minutes without tonight's missing teammates",
    "WO_PPM_DIFF": "Extra points per minute without tonight's missing teammates",
    "WO_FGA_PM_DIFF": "Extra shots per minute without tonight's missing teammates",
    "WO_REB_PM_DIFF": "Extra rebounds per minute without tonight's missing teammates",
    "WO_AST_PM_DIFF": "Extra assists per minute without tonight's missing teammates",
    "OPP_FTA_ALLOW_L10": "Opponent: free throws allowed per 100 poss (last 10)",
    "OPP_FG3A_ALLOW_L10": "Opponent: 3-pt attempts allowed per 100 poss (last 10)",
    "OPP_AST_ALLOW_L10": "Opponent: assists allowed per 100 poss (last 10)",
    "OPP_TOV_FORCED_L10": "Opponent: turnovers forced per 100 poss (last 10)",
    "OPP_OREB_ALLOW_L10": "Opponent: offensive rebound share allowed (last 10)",
    "STARTING": "Starting tonight", "START_RATE_L10": "Games started (share of last 10)",
    "ROLE_CHANGE": "Role change tonight (+1 new starter, -1 sent to the bench)",
    "MIN_ROLE_L20": "His minutes in tonight's role (starter or bench)",
    "MIN_ROLE_GAP": "Extra minutes tonight's role usually brings",
    "POT_AST_PM_L10": "Potential assists per minute (last 10)", "PASSES_PM_L10": "Passes per minute (last 10)",
    "REB_CHANCES_PM_L10": "Rebound chances per minute (last 10)",
    "OREB_CHANCES_PM_L10": "Offensive rebound chances per minute (last 10)",
    "DREB_CHANCES_PM_L10": "Defensive rebound chances per minute (last 10)",
    "DRIVES_PM_L10": "Drives per minute (last 10)", "DRIVE_FTA_PM_L10": "Free throws from drives per minute (last 10)",
    "TOUCHES_PM_L10": "Touches per minute (last 10)", "PAINT_TOUCHES_PM_L10": "Paint touches per minute (last 10)",
    "TIME_OF_POSS_PM_L10": "Share of his minutes holding the ball (last 10)",
    "AST_PER_POT_L20": "Assists per potential assist (last 20)",
    "REB_PER_CHANCE_L20": "Rebounds per rebound chance (last 20)",
    "TOV_PER_TOUCH_L20": "Turnovers per 100 touches (last 20)",
    "RIM_FGA_PM_L10": "Shots at the rim per minute (last 10)",
    "PAINT_FGA_PM_L10": "Paint shots away from the rim per minute (last 10)",
    "MID_FGA_PM_L10": "Midrange shots per minute (last 10)",
    "C3_FGA_PM_L10": "Corner 3s per minute (last 10)",
    "AB3_FGA_PM_L10": "Above-the-break 3s per minute (last 10)",
    "SELF_FGA_PM_L10": "Pull-ups, step-backs and fadeaways per minute (last 10)",
    "SHOT_FEET_L10": "Average shot distance in feet (last 10)",
    "RIM_PCT_L20": "Shooting at the rim (last 20)",
    "XPTS_PER_SHOT_L20": "Points per shot from his shot mix at league-average accuracy (last 20)",
    "SHOT_MAKING_L20": "Points per shot above or below what his shot mix usually scores (last 20)",
}
LABELS.update({f"{k}_REL_L10": LABELS[f"{k}_PM_L10"].replace(" (last 10)", ", vs. the league (last 10)")
               for k in TRACKING_PER_MIN})
LABELS.update({"AST_PER_POT_REL_L20": "Assists from his potential assists, vs. the league (last 20)",
               "REB_PER_CHANCE_REL_L20": "Rebounds from his rebound chances, vs. the league (last 20)",
               "TOV_PER_TOUCH_REL_L20": "Turnovers per touch, vs. the league (last 20)",
               "DEFLECTIONS_REL_L10": "Deflections per minute, vs. the league (last 10)",
               "CONTESTED_2PT_REL_L10": "Contested 2-point shots per minute, vs. the league (last 10)",
               "CONTESTED_3PT_REL_L10": "Contested 3-point shots per minute, vs. the league (last 10)",
               "SCREEN_AST_REL_L10": "Screen assists per minute, vs. the league (last 10)",
               "LOOSE_BALLS_REL_L10": "Loose balls recovered per minute, vs. the league (last 10)",
               "BOX_OUTS_REL_L10": "Box outs per minute, vs. the league (last 10, from 2022-23)",
               "GAMES_SINCE_RETURN": "Games since returning from an absence (1 = first game back)",
               "ABSENCE_GAMES": "Team games he missed in that absence",
               "PRE_ABSENCE_MIN": "His minutes before the absence (last 10)",
               "MIN_SINCE_RETURN": "His minutes since returning",
               "RETURN_RECOVERY": "Minutes since returning, as a share of before the absence",
               "MIN_L1": "Minutes, last game"})


def load_raw():
    p = pd.read_csv(PLAYER_LOGS, dtype={"GAME_ID": str})
    t = pd.read_csv(TEAM_LOGS, dtype={"GAME_ID": str})
    for df in (p, t):
        df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"])
        df["SEASON"] = df["SEASON_ID"].astype(str).str[1:].astype(int)  # 22025 -> 2025
    return add_hustle(add_shots(add_tracking(add_starters(add_prizepicks_columns(p))))), t


def add_tracking(p: pd.DataFrame) -> pd.DataFrame:
    """Each game's tracking counts (tracking.COLUMNS: potential assists, rebound chances, drives,
    touches, ...). Blank for a game whose day isn't downloaded yet. A player plays one game a day."""
    tr = tracking.load().drop(columns="TEAM_ID").drop_duplicates(["GAME_DATE", "PLAYER_ID"])
    tr["GAME_DATE"] = pd.to_datetime(tr["GAME_DATE"])
    return p.merge(tr, on=["GAME_DATE", "PLAYER_ID"], how="left")


def league_tracking_rates() -> pd.DataFrame:
    """League-wide tracking rates for each game day: each TRACKING_PER_MIN count per minute played, and
    how often potential assists, rebound chances and touches became assists, rebounds and turnovers
    (CONVERSIONS). NBA.com has changed how it counts several of these: for the same players, drives rose
    49% and time holding the ball 84% from 2023-24 to 2024-25, and rebound chances ran about 30% low from
    November 2025 until March 24, 2026 (TRAINING.md 4h). So each game is measured against the league under
    the same counting: that day, pooled with the days just before it in the same season until it covers
    LEAGUE_MIN_GAMES games, never a later day. Built from the whole tracking file, so training and the app
    get the same values; recomputed when the tracking file or the box scores change."""
    return _league_tracking_rates(TRACKING_FILE.stat().st_mtime if TRACKING_FILE.exists() else 0,
                                  PLAYER_LOGS.stat().st_mtime)


@functools.lru_cache(maxsize=1)
def _league_tracking_rates(*file_times: float) -> pd.DataFrame:
    logs = pd.read_csv(PLAYER_LOGS, usecols=["GAME_DATE", "GAME_ID", "PLAYER_ID", "MIN", "AST", "REB", "TOV"])
    games = logs.merge(tracking.load().drop(columns="TEAM_ID"), on=["GAME_DATE", "PLAYER_ID"])
    w = _pooled_by_day(games, ["MIN", "AST", "REB", "TOV", *TRACKING_PER_MIN.values()])
    rates = pd.DataFrame({c: w[c] / w["MIN"] for c in TRACKING_PER_MIN.values()})
    for name, (made, chances) in CONVERSIONS.items():
        rates[name] = w[made] / w[chances]
    return rates.replace(0, np.nan)


def tracking_features(p: pd.DataFrame) -> pd.DataFrame:
    """TRACKING inputs, as of before each game: his chances per minute over his last 10 tracked games,
    and how often they became assists, rebounds and turnovers over his last 20. Only games with tracking
    count, minutes included. TRACKING_REL: the same against the league's rates under the same counting
    (each game's counts divided by the league's per-minute rate that day; his assists, rebounds and
    turnovers against what the league's conversion would give his chances). p: sorted by player and date."""
    tracked = p["TOUCHES"].notna()
    league = league_tracking_rates().reindex(p["GAME_DATE"].to_numpy()).set_axis(p.index)
    temp = {"_TMIN": p["MIN"], "_TAST": p["AST"], "_TREB": p["REB"], "_TTOV": p["TOV"]}
    temp.update({f"_REL_{col}": p[col] / league[col] for col in TRACKING_PER_MIN.values()})
    temp.update({f"_X{made}": p[chances] * league[name] for name, (made, chances) in CONVERSIONS.items()})
    p = p.assign(**{k: v.where(tracked) for k, v in temp.items()})
    s = lambda col, n: lag(p, "PLAYER_ID", col, n, "sum")
    minutes = s("_TMIN", 10).clip(lower=1)
    new = {f"{name}_PM_L10": s(col, 10) / minutes for name, col in TRACKING_PER_MIN.items()}
    new["AST_PER_POT_L20"] = s("_TAST", 20) / s("POTENTIAL_AST", 20).clip(lower=1)
    new["REB_PER_CHANCE_L20"] = s("_TREB", 20) / s("REB_CHANCES", 20).clip(lower=1)
    new["TOV_PER_TOUCH_L20"] = 100 * s("_TTOV", 20) / s("TOUCHES", 20).clip(lower=1)
    new.update({f"{name}_REL_L10": s(f"_REL_{col}", 10) / minutes for name, col in TRACKING_PER_MIN.items()})
    new.update({f"{name}_REL_L20": s(f"_T{made}", 20) / s(f"_X{made}", 20).clip(lower=1)
                for name, (made, _) in CONVERSIONS.items()})
    # .copy() packs the table back into one block per type: build_features adds dozens more columns one at
    # a time after this, and pandas warns ("highly fragmented") once a table is in 100+ pieces
    return pd.concat([p.drop(columns=list(temp)), pd.DataFrame(new, index=p.index)], axis=1).copy()


def league_hustle_rates() -> pd.DataFrame:
    """League-wide hustle rates for each game day: each HUSTLE_PER_MIN count per minute played, pooled like
    league_tracking_rates. Deflections rose 15% at the start of 2024-25 and screen assists fell 15% at the
    start of 2025-26, and contested shots and loose balls drift down every season (TRAINING.md 4i), so each
    game is measured against the league under the same counting."""
    return _league_hustle_rates(HUSTLE_FILE.stat().st_mtime if HUSTLE_FILE.exists() else 0,
                                PLAYER_LOGS.stat().st_mtime)


@functools.lru_cache(maxsize=1)
def _league_hustle_rates(*file_times: float) -> pd.DataFrame:
    logs = pd.read_csv(PLAYER_LOGS, usecols=["GAME_DATE", "GAME_ID", "PLAYER_ID", "MIN"])
    games = logs.merge(hustle.load()[["GAME_DATE", "PLAYER_ID", *HUSTLE_PER_MIN.values()]],
                       on=["GAME_DATE", "PLAYER_ID"])
    w = _pooled_by_day(games, ["MIN", *HUSTLE_PER_MIN.values()])
    return pd.DataFrame({c: w[c] / w["MIN"] for c in HUSTLE_PER_MIN.values()}).replace(0, np.nan)


def _pooled_by_day(games: pd.DataFrame, counts: list[str]) -> pd.DataFrame:
    """League totals of `counts` for each game day (games: one row per player-game), pooled with the days
    just before it in the same season until they cover LEAGUE_MIN_GAMES games. Never a later day, and never
    the season before: NBA.com's counting changes at season starts."""
    day = games.groupby("GAME_DATE").agg(GAMES=("GAME_ID", "nunique"), **{c: (c, "sum") for c in counts})
    day.index = pd.to_datetime(day.index)
    pooled = []
    for _, d in day.groupby(day.index.map(lambda t: tracking.season_of(t.date()))):
        total = d.cumsum().to_numpy()                                    # season totals through each day
        before = np.vstack([np.zeros(d.shape[1]), total[:-1]])           # and before it
        # the latest first day that still gives LEAGUE_MIN_GAMES games (the season so far if it has fewer)
        first = np.searchsorted(before[:, 0], total[:, 0] - LEAGUE_MIN_GAMES, side="right") - 1
        pooled.append(pd.DataFrame(total - before[np.clip(first, 0, None)], index=d.index, columns=d.columns))
    return pd.concat(pooled)


def add_hustle(p: pd.DataFrame) -> pd.DataFrame:
    """Each game's hustle counts (HUSTLE_PER_MIN). Blank for a game whose day isn't downloaded yet, and box
    outs blank before BOX_OUTS_FROM. A player plays one game a day."""
    h = hustle.load()[["GAME_DATE", "PLAYER_ID", *HUSTLE_PER_MIN.values()]].drop_duplicates(["GAME_DATE", "PLAYER_ID"])
    h["GAME_DATE"] = pd.to_datetime(h["GAME_DATE"])
    p = p.merge(h, on=["GAME_DATE", "PLAYER_ID"], how="left")
    p["BOX_OUTS"] = p["BOX_OUTS"].where(p["SEASON"] >= BOX_OUTS_FROM)
    return p


def hustle_features(p: pd.DataFrame) -> pd.DataFrame:
    """HUSTLE inputs, as of before each game: each hustle count per minute against the league's rate that
    day, over his last 10 games with hustle stats (1.0 = league average). p: sorted by player and date."""
    league = league_hustle_rates().reindex(p["GAME_DATE"].to_numpy()).set_axis(p.index)
    temp = {"_HMIN": p["MIN"].where(p["DEFLECTIONS"].notna()), "_HBOX_MIN": p["MIN"].where(p["BOX_OUTS"].notna())}
    temp.update({f"_HREL_{col}": p[col] / league[col] for col in HUSTLE_PER_MIN.values()})
    p = p.assign(**temp)
    s = lambda col, n: lag(p, "PLAYER_ID", col, n, "sum")
    minutes = {col: s("_HBOX_MIN" if col == "BOX_OUTS" else "_HMIN", 10).clip(lower=1) for col in HUSTLE_PER_MIN.values()}
    new = {f"{name}_REL_L10": s(f"_HREL_{col}", 10) / minutes[col] for name, col in HUSTLE_PER_MIN.items()}
    return pd.concat([p.drop(columns=list(temp)), pd.DataFrame(new, index=p.index)], axis=1).copy()


def return_features(p: pd.DataFrame, same_team: pd.Series) -> pd.DataFrame:
    """RETURN inputs, as of before each game (known then: the schedule says how many games he missed).
    An absence is RETURN_AFTER+ team games missed in a row; a player's first game of a season counts the
    team's games before it, so a season-opening injury is a return too. A trade isn't an absence. p: sorted
    by player and date, with GAMES_MISSED's same_team (his previous game was this season, for this team)."""
    P = "PLAYER_ID"
    g = p.groupby(P)
    first_of_season = g["SEASON"].shift(1) != p["SEASON"]
    absence = (p["TEAM_GAME_NUM"] - g["TEAM_GAME_NUM"].shift(1) - 1).where(same_team)
    absence = absence.fillna(p["TEAM_GAME_NUM"].where(first_of_season)).clip(upper=82)
    returned = (absence >= RETURN_AFTER) & p["MIN_L10"].notna()     # a debut isn't a return
    stint = returned.astype(int).groupby(p[P]).cumsum()             # 0 until his first return in the data
    key = [p[P], stint]
    n = p.groupby(key).cumcount() + 1                               # 1 = the game he came back in
    recent = (stint > 0) & (n <= RETURN_WINDOW)
    before = p["MIN"].groupby(key).shift(1)                         # his minutes since, before tonight
    since = before.groupby(key).cumsum() / before.notna().groupby(key).cumsum().replace(0, np.nan)
    pre = p["MIN_L10"].where(returned).groupby(key).transform("first")  # last 10 games before he went out
    new = pd.DataFrame({
        "GAMES_SINCE_RETURN": n.where(recent, RETURN_WINDOW + 1),
        "ABSENCE_GAMES": absence.where(returned).groupby(key).transform("first").where(recent, 0),
        "PRE_ABSENCE_MIN": pre.where(recent),
        "MIN_SINCE_RETURN": since.where(recent),
        "RETURN_RECOVERY": (since / pre.clip(lower=1)).where(recent),
        "MIN_L1": lag(p, P, "MIN", 1),
    }, index=p.index)
    return pd.concat([p, new], axis=1)


def add_shots(p: pd.DataFrame) -> pd.DataFrame:
    """Each game's shot profile (SHOT_COLS: attempts and makes in each zone, self-created jumpers, total
    shot distance). Blank for a game whose shot chart isn't downloaded yet, 0 for a player who played in a
    charted game without taking a shot."""
    s = shots.load()
    p = p.merge(s[["GAME_ID", "PLAYER_ID", *SHOT_COLS]], on=["GAME_ID", "PLAYER_ID"], how="left")
    charted = p["GAME_ID"].isin(set(s["GAME_ID"])) & p["PTS"].notna()
    p.loc[charted, SHOT_COLS] = p.loc[charted, SHOT_COLS].fillna(0)
    return p


def league_zone_points() -> pd.DataFrame:
    """Points per attempt in each zone, league-wide, over the year before each game day (never that day
    itself): a rim attempt is worth about 1.3 points, a midrange one about 0.8. From the whole shots file,
    so training and the app get the same values. One row per game day, one column per zone."""
    s = shots.load()
    s["GAME_DATE"] = pd.to_datetime(s["GAME_DATE"])
    day = s.groupby("GAME_DATE")[[f"SHOT_{z}_{c}" for z in shots.ZONES for c in ("FGA", "FGM")]].sum()
    before = day.rolling(LEAGUE_WINDOW).sum().shift(1)   # shift(1): up to the previous game day
    return pd.DataFrame({z: before[f"SHOT_{z}_FGM"] / before[f"SHOT_{z}_FGA"] * (3 if z in shots.THREES else 2)
                         for z in shots.ZONES})


def shot_features(p: pd.DataFrame) -> pd.DataFrame:
    """SHOTS inputs, as of before each game. Only games with a shot chart count, minutes included.
    His expected points per shot weigh each zone by what the league scored from it the year before that
    game, so a shift toward the rim and corner 3s shows up before his makes do; SHOT_MAKING is the gap
    between his points per shot and that. p: sorted by player and date."""
    charted = p["SHOT_RIM_FGA"].notna()
    value = league_zone_points().reindex(p["GAME_DATE"].to_numpy()).set_axis(p.index)
    attempts = sum(p[f"SHOT_{z}_FGA"] for z in shots.ZONES)
    expected = sum(p[f"SHOT_{z}_FGA"] * value[z] for z in shots.ZONES)   # blank on the very first game day
    scored = sum(p[f"SHOT_{z}_FGM"] * (3 if z in shots.THREES else 2) for z in shots.ZONES)
    priced = expected.notna()
    temp = {"_SMIN": p["MIN"].where(charted), "_SFGA": attempts, "_SXFGA": attempts.where(priced),
            "_SXPTS": expected, "_SPTS": scored.where(priced)}
    p = p.assign(**temp)
    s = lambda col, n: lag(p, "PLAYER_ID", col, n, "sum")
    minutes = s("_SMIN", 10).clip(lower=1)
    new = {f"{k}_FGA_PM_L10": s(f"SHOT_{k}_FGA", 10) / minutes for k in SHOT_KINDS}
    new["SHOT_FEET_L10"] = s("SHOT_FEET", 10) / s("_SFGA", 10).clip(lower=1)
    new["RIM_PCT_L20"] = s("SHOT_RIM_FGM", 20) / s("SHOT_RIM_FGA", 20).clip(lower=1)
    priced_shots = s("_SXFGA", 20).clip(lower=1)
    new["XPTS_PER_SHOT_L20"] = s("_SXPTS", 20) / priced_shots
    new["SHOT_MAKING_L20"] = (s("_SPTS", 20) - s("_SXPTS", 20)) / priced_shots
    return pd.concat([p.drop(columns=list(temp)), pd.DataFrame(new, index=p.index)], axis=1).copy()


def add_starters(p: pd.DataFrame) -> pd.DataFrame:
    """STARTED: 1 if he started the game, 0 if he came off the bench, blank before 2023-24 (or a day
    NBA.com has no lineup for). From lineups.py."""
    s = lineups.history().drop_duplicates(["GAME_ID", "PLAYER_ID"])
    return p.merge(s, on=["GAME_ID", "PLAYER_ID"], how="left")


def add_prizepicks_columns(p: pd.DataFrame) -> pd.DataFrame:
    """PrizePicks stats that aren't box score columns:
    DD / TD  1 for a double-double / triple-double (10+ in two / three of PTS, REB, AST, STL, BLK), else 0;
    DUNKS    made dunks, from the shot charts. Blank for a game whose shot chart isn't downloaded yet,
             so it's never mistaken for 0 dunks."""
    tens = (p[["PTS", "REB", "AST", "STL", "BLK"]] >= 10).sum(axis=1)
    played = p["PTS"].notna()
    p["DD"] = (tens >= 2).astype(float).where(played)
    p["TD"] = (tens >= 3).astype(float).where(played)
    if not DUNKS.exists():
        p["DUNKS"] = np.nan
        return p
    d = pd.read_csv(DUNKS, dtype={"GAME_ID": str})
    p = p.merge(d, on=["GAME_ID", "PLAYER_ID"], how="left")
    covered = p["GAME_ID"].isin(set(d["GAME_ID"])) & played
    p.loc[covered, "DUNKS"] = p.loc[covered, "DUNKS"].fillna(0)  # played but took no shots
    return p


# ------------------------------------------------------------------ helpers
def _strip(r: pd.Series) -> pd.Series:
    """Drop the group levels pandas adds to groupby().rolling() results so they align with the frame."""
    return r.droplevel(list(range(r.index.nlevels - 1)))


def lag(df, keys, col, n=None, how="mean", min_periods=1, ewm=None, expanding=False):
    """Rolling stat over the PREVIOUS n games (never includes the current game)."""
    by = [df[k] for k in ([keys] if isinstance(keys, str) else keys)]
    s = df.groupby(by)[col].shift(1)
    g = s.groupby(by)
    if ewm is not None:
        return _strip(g.ewm(halflife=ewm).mean())
    r = g.expanding(min_periods=min_periods) if expanding else g.rolling(n, min_periods=min_periods)
    return _strip(getattr(r, how)())


# ---------------------------------------------------------------- team-level
def team_features(t: pd.DataFrame) -> pd.DataFrame:
    """Pace, offense, defense and rest for each team, as of before each game."""
    t = t.copy()
    t["POSS"] = t["FGA"] + 0.44 * t["FTA"] - t["OREB"] + t["TOV"]  # standard possession estimate
    opp = t[["GAME_ID", "TEAM_ID", "PTS", "POSS", "FTA", "FG3A", "AST", "TOV", "OREB"]].rename(
        columns={"TEAM_ID": "OPP_ID", "PTS": "OPP_PTS", "POSS": "OPP_POSS", "FTA": "O_FTA", "FG3A": "O_FG3A",
                 "AST": "O_AST", "TOV": "O_TOV", "OREB": "O_OREB"})
    m = t.merge(opp, on="GAME_ID")
    m = m[m["TEAM_ID"] != m["OPP_ID"]].sort_values(["TEAM_ID", "GAME_DATE"]).reset_index(drop=True)
    m["GAME_POSS"] = (m["POSS"] + m["OPP_POSS"]) / 2
    m["DEF_RTG"] = 100 * m["OPP_PTS"] / m["GAME_POSS"]  # points allowed per 100 possessions
    m["OFF_RTG"] = 100 * m["PTS"] / m["GAME_POSS"]
    # what this defense gives up, per 100 possessions (free throws, threes, assists, turnovers forced)
    for col, name in (("O_FTA", "FTA_ALLOW"), ("O_FG3A", "FG3A_ALLOW"), ("O_AST", "AST_ALLOW"), ("O_TOV", "TOV_FORCED")):
        m[name] = 100 * m[col] / m["GAME_POSS"]
    m["OREB_ALLOW"] = m["O_OREB"] / (m["O_OREB"] + m["DREB"]).clip(lower=1)  # share of its misses the opponent grabs
    for col, name in (("GAME_POSS", "PACE"), ("DEF_RTG", "DEF_RTG"), ("OFF_RTG", "OFF_RTG"), ("FTA_ALLOW", "FTA_ALLOW"),
                      ("FG3A_ALLOW", "FG3A_ALLOW"), ("AST_ALLOW", "AST_ALLOW"), ("TOV_FORCED", "TOV_FORCED"),
                      ("OREB_ALLOW", "OREB_ALLOW")):
        m[f"{name}_L10"] = lag(m, "TEAM_ID", col, 10, min_periods=3)
    m["NET_RTG_L10"] = m["OFF_RTG_L10"] - m["DEF_RTG_L10"]
    m["TEAM_REST"] = m.groupby("TEAM_ID")["GAME_DATE"].diff().dt.days.clip(upper=10)
    m["TEAM_GAME_NUM"] = m.groupby(["TEAM_ID", "SEASON"]).cumcount()
    m["MARGIN"] = m["PLUS_MINUS"].abs()  # final margin of THIS game: only ever used through lag() for later games
    return m[["GAME_ID", "TEAM_ID", "OPP_ID", "GAME_DATE", "SEASON", "PACE_L10", "DEF_RTG_L10",
              "OFF_RTG_L10", "NET_RTG_L10", "TEAM_REST", "TEAM_GAME_NUM", "MARGIN", "FTA_ALLOW_L10",
              "FG3A_ALLOW_L10", "AST_ALLOW_L10", "TOV_FORCED_L10", "OREB_ALLOW_L10"]]


# ------------------------------------------------------- missing teammates
# With no injury report, a rotation player is assumed out once he has missed this many team games in a
# row. Tested on 2025-26 (points CRPS with guessed absences): 1 game 3.524, 2 games 3.542, 3 games 3.554;
# knowing exactly who sat 3.489. Missing a real absence costs more than a wrong "out".
GUESS_OUT_AFTER = 1


def missing_players(p: pd.DataFrame, t: pd.DataFrame, overrides: dict | None = None,
                    official: set | None = None):
    """For each team-game: how many rotation players (20+ min/game lately) were absent,
    and how many shots / minutes per game they usually take.

    overrides = {game_id: set_of_player_ids_out} lets predict.py describe an upcoming game.
    For an overridden game, players who missed their team's last GUESS_OUT_AFTER games are also
    assumed out, unless (game_id, team_id) is in `official`: then the official injury report was
    used and anyone not listed out is expected to play.
    Returns (DataFrame keyed on GAME_ID+TEAM_ID, {game_id: {player_id: fga}} for override games).
    """
    overrides, official = overrides or {}, official or set()
    p = p.sort_values(["PLAYER_ID", "GAME_DATE"])
    g = p.groupby("PLAYER_ID")
    roll = lambda c: _strip(g[c].rolling(10, min_periods=1).mean())
    p = p.assign(_MIN10=roll("MIN"), _FGA10=roll("FGA"), _REB10=roll("REB"), _AST10=roll("AST"))
    last_team = {pid: (grp["GAME_DATE"].values, grp["TEAM_ID"].values) for pid, grp in g}
    roster = {key: dict(zip(grp["PLAYER_ID"], zip(grp["_MIN10"], grp["_FGA10"], grp["_REB10"], grp["_AST10"])))
              for key, grp in p.groupby(["TEAM_ID", "GAME_ID"])}

    def still_on_team(pid, when, team):
        d, tm = last_team[pid]
        j = np.searchsorted(d, np.datetime64(when)) - 1
        return j >= 0 and tm[j] == team

    rows, details = [], {}
    for (team, season), tg in t.groupby(["TEAM_ID", "SEASON"]):
        order = tg.sort_values("GAME_DATE")[["GAME_ID", "GAME_DATE"]].values
        for i, (gid, when) in enumerate(order):
            latest = {}
            for x in order[max(0, i - 10):i, 0]:  # later games overwrite earlier ones
                latest.update(roster.get((team, x), {}))
            cands = {pid: v for pid, v in latest.items() if v[0] >= 20 and still_on_team(pid, when, team)}
            here = roster.get((team, gid), {})
            if gid in overrides:
                played_lately = set().union(*[roster.get((team, x), {})
                                              for x in order[max(0, i - GUESS_OUT_AFTER):i, 0]])
                guess = (gid, team) not in official
                out = [pid for pid in cands if pid not in here  # not the player we're predicting
                       and (pid in overrides[gid] or (guess and pid not in played_lately))]
                details.setdefault(gid, {}).update({pid: cands[pid][1] for pid in out})
            else:
                out = [pid for pid in cands if pid not in here]
            tot = lambda j: float(sum(cands[q][j] for q in out))
            rows.append((gid, team, tot(1), len(out), tot(0), tot(2), tot(3), frozenset(out)))
    df = pd.DataFrame(rows, columns=["GAME_ID", "TEAM_ID", "MISSING_FGA", "MISSING_COUNT", "MISSING_MIN",
                                     "MISSING_REB", "MISSING_AST", "_ABSENT"])  # _ABSENT: who exactly was out
    return df, details


WO_STATS = (("PPM", "PTS"), ("FGA_PM", "FGA"), ("REB_PM", "REB"), ("AST_PM", "AST"))


def without_splits(p: pd.DataFrame, rows: np.ndarray | None = None) -> pd.DataFrame:
    """How this player did in his earlier games (same team, this season or last) when at least one of
    tonight's absent teammates also sat, compared with all his games over that span: extra minutes, and
    extra points / shots / rebounds / assists per minute. WO_GP = how many such games (trust it more when
    it's bigger). `rows` limits the work to those row positions (prediction time). p: sorted by player, date."""
    n = len(p)
    out = {"WO_GP": np.full(n, np.nan), "WO_MIN_DIFF": np.full(n, np.nan)}
    out.update({f"WO_{k}_DIFF": np.full(n, np.nan) for k, _ in WO_STATS})
    want = np.zeros(n, bool)
    want[np.arange(n) if rows is None else rows] = True
    team, season, absent = p["TEAM_ID"].to_numpy(), p["SEASON"].to_numpy(), p["_ABSENT"].to_numpy()
    mins = p["MIN"].to_numpy(float)
    vals = {k: p[c].to_numpy(float) for k, c in WO_STATS}
    for idx in p.groupby("PLAYER_ID", sort=False).indices.values():
        for k, i in enumerate(idx):
            if not want[i]:
                continue
            a = absent[i]
            if not isinstance(a, frozenset) or not a:
                out["WO_GP"][i] = 0
                continue
            prev = [j for j in idx[max(0, k - 120):k]
                    if team[j] == team[i] and season[j] >= season[i] - 1 and mins[j] == mins[j]]  # played
            wo = [j for j in prev if isinstance(absent[j], frozenset) and not a.isdisjoint(absent[j])]
            out["WO_GP"][i] = len(wo)
            if not wo:
                continue
            m_all, m_wo = mins[prev].sum(), mins[wo].sum()
            out["WO_MIN_DIFF"][i] = m_wo / len(wo) - m_all / len(prev)
            for key, _ in WO_STATS:
                v = vals[key]
                out[f"WO_{key}_DIFF"][i] = v[wo].sum() / max(m_wo, 1) - v[prev].sum() / max(m_all, 1)
    return pd.DataFrame(out, index=p.index)


def set_role(p: pd.DataFrame, starting: pd.Series):
    """Tonight's role inputs from STARTING (1 starting, 0 off the bench, blank unknown): the change from
    his recent role, and the minutes he usually plays in it. p needs START_RATE_L10, MIN_AS_STARTER_L20,
    MIN_OFF_BENCH_L20 and MIN_L10."""
    p["STARTING"] = starting
    p["ROLE_CHANGE"] = starting - p["START_RATE_L10"]   # +1: a first start in a while, -1: sent to the bench
    p["MIN_ROLE_L20"] = np.where(starting == 1, p["MIN_AS_STARTER_L20"],
                                 np.where(starting == 0, p["MIN_OFF_BENCH_L20"], np.nan))
    p["MIN_ROLE_GAP"] = p["MIN_ROLE_L20"] - p["MIN_L10"]
    # Before tonight's lineup is posted these stay blank. Assuming his usual role instead was tested and
    # was worse (TRAINING.md 4e): the usual role is tonight's in only 85% of games, and the misses are
    # exactly the role changes that matter.


# ------------------------------------------------------------- player-level
def build_features(p: pd.DataFrame, t: pd.DataFrame, overrides: dict | None = None,
                   official: set | None = None, stats: list | None = None, stat_players: set | None = None):
    """stats: extra stats (keys of STAT_KEYS) to build history features for.
    stat_players: only build those for these players (much faster at prediction time)."""
    tf = team_features(t)
    team_box = t[["GAME_ID", "TEAM_ID", "FGA", "FTA", "TOV"]].rename(
        columns={"FGA": "T_FGA", "FTA": "T_FTA", "TOV": "T_TOV"})
    p = p.merge(team_box, on=["GAME_ID", "TEAM_ID"], how="left")
    p = p.sort_values(["PLAYER_ID", "GAME_DATE"]).reset_index(drop=True)

    p["HOME"] = p["MATCHUP"].str.contains(" vs. ").astype(int)
    p["USG"] = (p["FGA"] + 0.44 * p["FTA"] + p["TOV"]) / p["MIN"].clip(lower=1)
    p["USG_SHARE"] = (p["FGA"] + 0.44 * p["FTA"] + p["TOV"]) / (p["T_FGA"] + 0.44 * p["T_FTA"] + p["T_TOV"])
    p["TSA"] = p["FGA"] + 0.44 * p["FTA"]

    P, PS = "PLAYER_ID", ["PLAYER_ID", "SEASON"]
    for n in (3, 5, 10, 20, 40):
        p[f"PTS_L{n}"] = lag(p, P, "PTS", n)
    p["PTS_EWM"] = lag(p, P, "PTS", ewm=5)
    p["PTS_EWM15"] = lag(p, P, "PTS", ewm=15)
    p["PTS_STD_L10"] = lag(p, P, "PTS", 10, "std", min_periods=3)
    for n in (3, 5, 10):
        p[f"MIN_L{n}"] = lag(p, P, "MIN", n)
    p["MIN_EWM"] = lag(p, P, "MIN", ewm=5)
    p["MIN_STD_L10"] = lag(p, P, "MIN", 10, "std", min_periods=3)
    for col in ("FGA", "FTA", "FG3A", "USG", "USG_SHARE"):
        p[f"{col}_L10"] = lag(p, P, col, 10)

    # rates = ratio of sums (more stable than averaging per-game ratios)
    s = lambda col, n: lag(p, P, col, n, "sum")
    p["PPM_L10"] = s("PTS", 10) / s("MIN", 10).clip(lower=1)
    p["TS_L10"] = s("PTS", 10) / (2 * s("TSA", 10)).clip(lower=1)
    p["TS_L40"] = s("PTS", 40) / (2 * s("TSA", 40)).clip(lower=1)
    p = tracking_features(p)
    p = shot_features(p)
    p = hustle_features(p)

    p["PTS_SEASON"] = lag(p, PS, "PTS", expanding=True)
    p["MIN_SEASON"] = lag(p, PS, "MIN", expanding=True)
    p["PPM_SEASON"] = lag(p, PS, "PTS", how="sum", expanding=True) / \
        lag(p, PS, "MIN", how="sum", expanding=True).clip(lower=1)
    p["GP_SEASON"] = p.groupby(PS).cumcount()

    prev = p.groupby(PS)["PTS"].mean().rename("PTS_PREV_SEASON").reset_index()
    prev["SEASON"] += 1
    p = p.merge(prev, on=PS, how="left")

    p["REST_DAYS"] = p.groupby(P)["GAME_DATE"].diff().dt.days.clip(upper=10)
    p["B2B"] = (p["REST_DAYS"] == 1).astype(int)

    # ---- team / opponent context
    own = tf.rename(columns={"PACE_L10": "OWN_PACE_L10", "OFF_RTG_L10": "OWN_OFF_RTG_L10",
                             "NET_RTG_L10": "OWN_NET_RTG_L10"})[
        ["GAME_ID", "TEAM_ID", "OPP_ID", "OWN_PACE_L10", "OWN_OFF_RTG_L10", "OWN_NET_RTG_L10", "TEAM_GAME_NUM", "MARGIN"]]
    allow = ["FTA_ALLOW_L10", "FG3A_ALLOW_L10", "AST_ALLOW_L10", "TOV_FORCED_L10", "OREB_ALLOW_L10"]
    opp = tf.drop(columns="OPP_ID").rename(columns={"TEAM_ID": "OPP_ID", "PACE_L10": "OPP_PACE_L10", "DEF_RTG_L10": "OPP_DEF_RTG_L10",
                             "OFF_RTG_L10": "OPP_OFF_RTG_L10", "NET_RTG_L10": "OPP_NET_RTG_L10",
                             "TEAM_REST": "OPP_REST", **{c: f"OPP_{c}" for c in allow}})[
        ["GAME_ID", "OPP_ID", "OPP_PACE_L10", "OPP_DEF_RTG_L10", "OPP_OFF_RTG_L10", "OPP_NET_RTG_L10", "OPP_REST"]
        + [f"OPP_{c}" for c in allow]]
    p = p.merge(own, on=["GAME_ID", "TEAM_ID"], how="left").merge(opp, on=["GAME_ID", "OPP_ID"], how="left")
    p["OPP_B2B"] = (p["OPP_REST"] == 1).astype(int)
    p["NET_DIFF"] = (p["OWN_NET_RTG_L10"] - p["OPP_NET_RTG_L10"]).abs()  # big gap = blowout risk either way
    pace = (p["OWN_PACE_L10"] + p["OPP_PACE_L10"]) / 2
    p["EXP_TEAM_PTS"] = (p["OWN_OFF_RTG_L10"] + p["OPP_DEF_RTG_L10"]) / 2 * pace / 100

    # games missed right before this one (returning from injury => minutes limits)
    p = p.sort_values([P, "GAME_DATE"]).reset_index(drop=True)
    g = p.groupby(P)
    same = (g["TEAM_ID"].shift(1) == p["TEAM_ID"]) & (g["SEASON"].shift(1) == p["SEASON"])
    p["GAMES_MISSED"] = (p["TEAM_GAME_NUM"] - g["TEAM_GAME_NUM"].shift(1) - 1).where(same).clip(0, 20)
    p = return_features(p, same)

    # ---- minutes in close games: blowouts (benched 4th quarter) shouldn't drag a starter's minutes down
    p["_MIN_CLOSE"] = p["MIN"].where(p["MARGIN"] <= 10)
    p["_BLOWOUT"] = (p["MARGIN"] >= 20).astype(float).where(p["MARGIN"].notna())
    p["MIN_CLOSE_L10"] = lag(p, P, "_MIN_CLOSE", 10)
    p["BLOWOUT_L5"] = lag(p, P, "_BLOWOUT", 5)
    p["MIN_CLOSE_GAP"] = p["MIN_CLOSE_L10"] - p["MIN_L5"]
    p = p.drop(columns=["_MIN_CLOSE", "_BLOWOUT", "MARGIN"])  # MARGIN is this game's result: never an input

    # ---- starting lineups: tonight's role, how often he's started lately, and his usual minutes in
    # that role. This game's STARTED is posted before tip-off (Expected, then Confirmed), so it's known
    # when a line is checked; for an upcoming game predictor.py fills it in from tonight's lineup.
    if "STARTED" not in p:
        p["STARTED"] = np.nan
    p["START_RATE_L10"] = lag(p, P, "STARTED", 10)
    p["_MIN_START"] = p["MIN"].where(p["STARTED"] == 1)
    p["_MIN_BENCH"] = p["MIN"].where(p["STARTED"] == 0)
    p["MIN_AS_STARTER_L20"] = lag(p, P, "_MIN_START", 20)   # his minutes in the games he started, of his last 20
    p["MIN_OFF_BENCH_L20"] = lag(p, P, "_MIN_BENCH", 20)
    p = p.drop(columns=["_MIN_START", "_MIN_BENCH"]).copy()   # .copy(): one block again after ~100 added columns
    set_role(p, p["STARTED"])

    # ---- absences on both teams
    miss, details = missing_players(p, t, overrides, official)
    p = p.merge(miss, on=["GAME_ID", "TEAM_ID"], how="left")
    p = p.merge(miss.drop(columns="_ABSENT").rename(columns={"TEAM_ID": "OPP_ID", "MISSING_FGA": "OPP_MISSING_FGA",
                                     "MISSING_COUNT": "OPP_MISSING_COUNT", "MISSING_MIN": "_OMM",
                                     "MISSING_REB": "OPP_MISSING_REB", "MISSING_AST": "_OMA"}),
                on=["GAME_ID", "OPP_ID"], how="left").drop(columns=["_OMM", "_OMA"])
    # ---- this player's own record without tonight's absent teammates
    p = p.sort_values([P, "GAME_DATE"]).reset_index(drop=True)
    rows = None
    if stat_players is not None:  # prediction: only the games being predicted
        rows = np.flatnonzero(p["PLAYER_ID"].isin(stat_players) & p["GAME_ID"].astype(str).str.startswith("PRED"))
    p = pd.concat([p, without_splits(p, rows)], axis=1).drop(columns="_ABSENT")

    # ---- matchup: how much do players score vs. their own averages against this defense?
    p["PERIM"] = (p["FG3A_L10"] / p["FGA_L10"].clip(lower=1) >= 0.4).astype(int)
    rot = p[(p["MIN_L10"] >= 15) & p["PTS"].notna() & p["PTS_EWM"].notna()].assign(
        RESID=lambda d: d["PTS"] - d["PTS_EWM"])
    agg = rot.groupby(["GAME_ID", "OPP_ID"])["RESID"].mean().rename("POE_ALL")
    by_type = rot.pivot_table(index=["GAME_ID", "OPP_ID"], columns="PERIM", values="RESID", aggfunc="mean")
    by_type.columns = [f"POE_T{c}" for c in by_type.columns]
    d = tf[["GAME_ID", "TEAM_ID", "GAME_DATE"]].rename(columns={"TEAM_ID": "OPP_ID"})
    d = d.merge(agg.reset_index(), on=["GAME_ID", "OPP_ID"], how="left") \
         .merge(by_type.reset_index(), on=["GAME_ID", "OPP_ID"], how="left") \
         .sort_values(["OPP_ID", "GAME_DATE"]).reset_index(drop=True)
    for c in ("POE_ALL", "POE_T0", "POE_T1"):
        d[c + "_L15"] = lag(d, "OPP_ID", c, 15, min_periods=5)
    p = p.merge(d[["GAME_ID", "OPP_ID", "POE_ALL_L15", "POE_T0_L15", "POE_T1_L15"]],
                on=["GAME_ID", "OPP_ID"], how="left")
    p["OPP_POE_L15"] = p["POE_ALL_L15"]
    p["OPP_POE_TYPE"] = np.where(p["PERIM"] == 1, p["POE_T1_L15"], p["POE_T0_L15"])
    if stats:
        p = add_stat_features(p, stats, stat_players)
    return p, details


# ------------------------------------------------------- other PrizePicks stats
# key -> how to compute it from a box score (PrizePicks' fantasy scoring for FS)
STAT_KEYS = {
    "PTS": {"PTS": 1}, "REB": {"REB": 1}, "AST": {"AST": 1}, "FG3M": {"FG3M": 1},
    "STL": {"STL": 1}, "BLK": {"BLK": 1}, "TOV": {"TOV": 1},
    "PRA": {"PTS": 1, "REB": 1, "AST": 1}, "PR": {"PTS": 1, "REB": 1}, "PA": {"PTS": 1, "AST": 1},
    "RA": {"REB": 1, "AST": 1}, "BS": {"BLK": 1, "STL": 1},
    "FS": {"PTS": 1, "REB": 1.2, "AST": 1.5, "BLK": 3, "STL": 3, "TOV": -1},
    # shooting / rebounding splits / fouls (keys start with X so they never clash with existing columns)
    "XFGA": {"FGA": 1}, "XFGM": {"FGM": 1}, "X3PA": {"FG3A": 1}, "XFTM": {"FTM": 1}, "XFTA": {"FTA": 1},
    "XOREB": {"OREB": 1}, "XDREB": {"DREB": 1}, "X2PM": {"FGM": 1, "FG3M": -1}, "X2PA": {"FGA": 1, "FG3A": -1},
    "XPF": {"PF": 1},
    # yes/no stats and dunks (columns added by add_prizepicks_columns)
    "XDD": {"DD": 1}, "XTD": {"TD": 1}, "XDUNK": {"DUNKS": 1},
}
# 1 or 0 each game: modeled as a chance (logistic), not a count
YES_NO_STATS = {"XDD", "XTD"}
# A double-double takes two stats at once, so these models also see the player's other stats
# (his points history is already in SHARED and the base features).
ALSO_SEES = {k: ["REB", "AST", "BLK", "STL"] for k in YES_NO_STATS}
# context every stat model gets (minutes, role, pace, blowout risk, absences)
SHARED = ["MIN_L3", "MIN_L5", "MIN_L10", "MIN_SEASON", "MIN_EWM", "MIN_STD_L10", "GAMES_MISSED",
          "FGA_L10", "FTA_L10", "FG3A_L10", "USG_L10", "USG_SHARE_L10", "PTS_EWM", "GP_SEASON",
          "REST_DAYS", "B2B", "HOME", "OWN_PACE_L10", "OPP_PACE_L10", "OPP_DEF_RTG_L10", "OWN_OFF_RTG_L10",
          "OWN_NET_RTG_L10", "OPP_OFF_RTG_L10", "OPP_NET_RTG_L10", "NET_DIFF", "EXP_TEAM_PTS", "OPP_REST",
          "OPP_B2B", "MISSING_FGA", "MISSING_COUNT", "MISSING_MIN", "MISSING_REB", "MISSING_AST",
          "OPP_MISSING_FGA", "OPP_MISSING_COUNT", "OPP_MISSING_REB"]
SHARED += [f for cols in EXTRA.values() for f in cols]  # helped assists, turnovers, free throws (E9 test)
HIST = ["L3", "L5", "L10", "L20", "L40", "EWM", "EWM15", "STD_L10", "SEASON", "PREV_SEASON", "PM_L10", "PM_SEASON"]


OTHER_STATS = [k for k in STAT_KEYS if k != "PTS"]  # Points keeps its own tested features (V2)
STAT_NAMES = {"PTS": "Points", "REB": "Rebounds", "AST": "Assists", "FG3M": "3-PT Made", "STL": "Steals",
              "BLK": "Blocked Shots", "TOV": "Turnovers", "PRA": "Pts+Rebs+Asts", "PR": "Pts+Rebs",
              "PA": "Pts+Asts", "RA": "Rebs+Asts", "BS": "Blks+Stls", "FS": "Fantasy Score",
              "XFGA": "FG Attempted", "XFGM": "FG Made", "X3PA": "3-PT Attempted", "XFTM": "Free Throws Made",
              "XFTA": "Free Throws Attempted", "XOREB": "Offensive Rebounds", "XDREB": "Defensive Rebounds",
              "X2PM": "Two Pointers Made", "X2PA": "Two Pointers Attempted", "XPF": "Personal Fouls",
              "XDD": "Double Doubles", "XTD": "Triple Doubles", "XDUNK": "Dunks"}
NAME_TO_KEY = {v: k for k, v in STAT_NAMES.items()}
HIST_LABELS = {"L3": "last 3 games", "L5": "last 5 games", "L10": "last 10 games", "L20": "last 20 games",
               "L40": "last 40 games", "EWM": "recent-weighted average", "EWM15": "long-run weighted average",
               "STD_L10": "volatility (last 10)", "SEASON": "season average", "PREV_SEASON": "last season average",
               "PM_L10": "per minute, last 10", "PM_SEASON": "per minute, season"}
LABELS.update({"MISSING_REB": "Rebounds freed up by absent teammates",
               "MISSING_AST": "Assists freed up by absent teammates",
               "OPP_MISSING_REB": "Opponent rebounds missing (absences)"})


def feature_label(f: str) -> str:
    if f in LABELS:
        return LABELS[f]
    key, _, hist = f.partition("_")
    if key in STAT_NAMES and hist in HIST_LABELS:
        return f"{STAT_NAMES[key]}, {HIST_LABELS[hist]}"
    return f


# Starting lineups helped 21 of 25 stats and made no real difference to 3 (E10, TRAINING.md 4e); only
# triple-doubles came out (very slightly) worse, so they go without.
NO_LINEUPS = {"XTD"}
# Player tracking helped these 6 stats on 2023-24 and 2024-25 and none got worse on 2025-26 (E11, TRAINING.md
# 4f): rebound chances the rebound stats, touches turnovers. It made no difference to 17 others, and made
# assists and Pts+Asts worse, so they go without. Since Nov 19, 2026 they get it measured against the league
# (TRACKING_REL): never worse than the raw counts in three test periods, better in one for 4 of the 6 (4h).
WITH_TRACKING = {"TOV", "REB", "XOREB", "RA", "X2PM", "XFTA"}
# The shot profile helped these 10 stats on 2023-24 and 2024-25 and none got worse on 2025-26 (E12, TRAINING.md
# 4g): mostly shot and free-throw volume, where a player shoots and how he gets his shots. It made no difference
# to Points and 14 others, so they go without.
WITH_SHOTS = {"XFGA", "X3PA", "X2PA", "XFTA", "XFTM", "PRA", "STL", "BLK", "BS", "XDREB"}
# Hustle stats helped these 5 on 2023-24 and 2024-25 and none got worse on 2025-26 or 2026-27 so far (E13,
# TRAINING.md 4i): deflections steals (better in every period), contested shots blocks, box outs offensive
# rebounds. Blks+Stls just missed on the deciding seasons and was better on both later ones. No difference to
# Points and 17 others; Pts+Asts was slightly worse.
WITH_HUSTLE = {"STL", "BLK", "BS", "XOREB", "XDUNK", "XFTA"}
# Coming back from an absence helped the 4 scoring combos on 2023-24 and 2024-25 and none got worse on 2025-26
# (E14, TRAINING.md 4k); Points has it in its recipe. The other 20 stats haven't been tested with it yet.
WITH_RETURN = {"PRA", "PR", "PA", "FS"}


def stat_feature_list(key: str) -> list[str]:
    others = [f"{k}_{h}" for k in ALSO_SEES.get(key, []) for h in ("L10", "EWM", "SEASON", "STD_L10")]
    if others:
        others += ["PTS_L10", "PTS_SEASON", "PTS_STD_L10"]
    return ([f"{key}_{h}" for h in HIST] + others + SHARED + ([] if key in NO_LINEUPS else LINEUPS)
            + (TRACKING_REL if key in WITH_TRACKING else []) + (SHOTS if key in WITH_SHOTS else [])
            + (HUSTLE if key in WITH_HUSTLE else []) + (RETURN if key in WITH_RETURN else []))


def history_keys(keys) -> list[str]:
    """The stats whose history must be built to predict these stats (they plus ALSO_SEES)."""
    return sorted(set(keys) | {k for key in keys for k in ALSO_SEES.get(key, [])})


def add_stat_features(p: pd.DataFrame, keys: list, players: set | None = None) -> pd.DataFrame:
    """Target column Y_<key> plus history features <key>_L3 ... <key>_PM_SEASON for each stat."""
    p = p.sort_values(["PLAYER_ID", "GAME_DATE"]).reset_index(drop=True)
    sub_ = p[p["PLAYER_ID"].isin(players)].copy() if players is not None else p.copy()
    P, PS = "PLAYER_ID", ["PLAYER_ID", "SEASON"]
    keys = [k for k in keys if k != "PTS"]  # Points already has its own history features
    new = {}
    for k in keys:
        y = f"Y_{k}"
        sub_[y] = sum(w * sub_[c] for c, w in STAT_KEYS[k].items())
        for n in (3, 5, 10, 20, 40):
            new[f"{k}_L{n}"] = lag(sub_, P, y, n)
        new[f"{k}_EWM"] = lag(sub_, P, y, ewm=5)
        new[f"{k}_EWM15"] = lag(sub_, P, y, ewm=15)
        new[f"{k}_STD_L10"] = lag(sub_, P, y, 10, "std", min_periods=3)
        new[f"{k}_SEASON"] = lag(sub_, PS, y, expanding=True)
        new[f"{k}_PM_L10"] = lag(sub_, P, y, 10, "sum") / lag(sub_, P, "MIN", 10, "sum").clip(lower=1)
        new[f"{k}_PM_SEASON"] = lag(sub_, PS, y, how="sum", expanding=True) / \
            lag(sub_, PS, "MIN", how="sum", expanding=True).clip(lower=1)
    sub_ = pd.concat([sub_, pd.DataFrame(new, index=sub_.index)], axis=1)
    ys = [f"Y_{k}" for k in keys]
    prev = sub_.groupby(PS)[ys].mean().rename(columns={f"Y_{k}": f"{k}_PREV_SEASON" for k in keys}).reset_index()
    prev["SEASON"] += 1
    sub_ = sub_.merge(prev, on=PS, how="left")
    cols = ys + [c for k in keys for c in (f"{k}_{h}" for h in HIST)]
    if players is None:
        return sub_
    keep = sub_[["PLAYER_ID", "GAME_ID"] + cols]
    return p.merge(keep, on=["PLAYER_ID", "GAME_ID"], how="left")


# The models are trained and tested only on players averaging at least this many minutes over their
# last 10 games. Below it their chances are noticeably less accurate, so the app flags those players.
MIN_TESTED_MINUTES = 15


def training_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Keep rotation players with some history: the kind of players who get prop lines."""
    return df[(df["MIN_L10"] >= MIN_TESTED_MINUTES) & df["PTS_L10"].notna() & df["PTS"].notna()]


def load_features(rebuild: bool = False) -> pd.DataFrame:
    """Training rows for all seasons. Building them takes about a minute, so they're cached
    (compressed: ~200 MB instead of ~570 MB, identical data) and rebuilt whenever the box scores
    or this file change."""
    cache = FEATURES_CACHE
    srcs = [PLAYER_LOGS, TEAM_LOGS, Path(__file__)] + [
        f for f in (DUNKS, STARTERS, TRACKING_FILE, SHOTS_FILE, HUSTLE_FILE) if f.exists()]
    if not rebuild and cache.exists() and cache.stat().st_mtime > max(f.stat().st_mtime for f in srcs):
        return pd.read_pickle(cache)
    p, t = load_raw()
    df, _ = build_features(p, t, stats=OTHER_STATS)
    df = training_rows(df).reset_index(drop=True)
    df.to_pickle(cache, compression={"method": "gzip", "compresslevel": 1})
    return df
