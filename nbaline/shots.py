"""Shot profile from NBA.com's shot charts: where and how each player shot, per game.

The shot chart lists every shot with its zone ("Restricted Area", "Mid-Range", "Left Corner 3", ...), its
distance and its type ("Pullup Jump shot", "Driving Layup Shot", ...). fetch_data.py already downloads it to
count dunks; this keeps the rest, summed per player per game:

    SHOT_<zone>_FGA / _FGM   attempts and makes in each zone (ZONES below); half-court heaves left out
    SHOT_SELF_FGA / _FGM     self-created jumpers: pull-ups, step-backs, fadeaways, turnarounds
    SHOT_FEET                total distance of his shots in feet (divide by the zone attempts: average distance)
    DUNKS                    made dunks (the same count as data/dunks.csv)

    data/raw/shots_<season>.csv   one file per season (past seasons are downloaded once)
    data/shots.csv                every season, finished games only: GAME_ID, GAME_DATE, PLAYER_ID + COLUMNS

    python -m nbaline.shots      # download every season not saved yet, and this season again (~10 minutes)
"""
import sys
import time
from datetime import date

import pandas as pd
from nba_api.stats.endpoints import shotchartdetail

from .paths import PLAYER_LOGS, RAW, SHOTS

ZONES = {"RIM": ["Restricted Area"], "PAINT": ["In The Paint (Non-RA)"], "MID": ["Mid-Range"],
         "C3": ["Left Corner 3", "Right Corner 3"], "AB3": ["Above the Break 3"]}
THREES = {"C3", "AB3"}
SELF_CREATED = r"pull|step back|fadeaway|turnaround jump"   # matched against the shot type, any case
COLUMNS = ([f"SHOT_{z}_{c}" for z in [*ZONES, "SELF"] for c in ("FGA", "FGM")] + ["SHOT_FEET", "DUNKS"])
FIRST_SEASON = 2017     # the first season the models train on
PAUSE = 1.0             # seconds between requests: be polite to stats.nba.com


def season_str(start: int) -> str:
    return f"{start}-{str(start + 1)[-2:]}"   # 2025 -> "2025-26"


def _month(season: str, month: str) -> pd.DataFrame:
    """Every shot taken in one month. The shot chart stops at about 100,000 shots per request (half a
    season), so it's asked for a month at a time."""
    first = pd.Timestamp(month + "-01")
    last = first + pd.offsets.MonthEnd(0)
    for attempt in range(3):
        try:
            return shotchartdetail.ShotChartDetail(
                team_id=0, player_id=0, season_nullable=season, season_type_all_star="Regular Season",
                context_measure_simple="FGA", date_from_nullable=f"{first:%m/%d/%Y}",
                date_to_nullable=f"{last:%m/%d/%Y}", timeout=120).get_data_frames()[0]
        except Exception:   # stats.nba.com drops requests now and then
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Couldn't download the shot chart for {month}")


def summarize(shots: pd.DataFrame) -> pd.DataFrame:
    """Every shot -> one row per player per game (COLUMNS). Everyone who took a shot gets a row."""
    made = shots["SHOT_MADE_FLAG"] == 1
    cols = {}
    for zone, names in ZONES.items():
        inside = shots["SHOT_ZONE_BASIC"].isin(names)
        cols[f"SHOT_{zone}_FGA"], cols[f"SHOT_{zone}_FGM"] = inside, inside & made
    self_created = shots["ACTION_TYPE"].str.contains(SELF_CREATED, case=False)
    cols["SHOT_SELF_FGA"], cols["SHOT_SELF_FGM"] = self_created, self_created & made
    cols["SHOT_FEET"] = shots["SHOT_DISTANCE"].where(shots["SHOT_ZONE_BASIC"] != "Backcourt", 0)
    cols["DUNKS"] = shots["ACTION_TYPE"].str.contains("Dunk", case=False) & made
    per_shot = pd.DataFrame(cols).astype(int).assign(
        GAME_ID=shots["GAME_ID"].astype(str), PLAYER_ID=shots["PLAYER_ID"],
        GAME_DATE=pd.to_datetime(shots["GAME_DATE"].astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d"))
    return per_shot.groupby(["GAME_ID", "GAME_DATE", "PLAYER_ID"], as_index=False)[COLUMNS].sum()


def download_season(season: str, game_dates: pd.Series) -> pd.DataFrame:
    """One season's shot profile, a month at a time for each month that had games."""
    parts = []
    for month in sorted({d[:7] for d in game_dates.astype(str)}):   # "2025-11", ...
        parts.append(_month(season, month))
        time.sleep(PAUSE)
    return summarize(pd.concat(parts))


def load() -> pd.DataFrame:
    """Every saved row (empty, with the right columns, if nothing is saved yet)."""
    if not SHOTS.exists():
        return pd.DataFrame(columns=["GAME_ID", "GAME_DATE", "PLAYER_ID", *COLUMNS]).astype(
            {"PLAYER_ID": int, **{c: float for c in COLUMNS}})
    return pd.read_csv(SHOTS, dtype={"GAME_ID": str})


def update(current: int) -> int:
    """Download each season since FIRST_SEASON that isn't saved yet, and the current season again (its
    games keep coming), then save data/shots.csv with the games in the box scores (finished ones).
    Returns how many seasons were downloaded."""
    logs = pd.read_csv(PLAYER_LOGS, usecols=["GAME_ID", "GAME_DATE", "SEASON_ID"], dtype={"GAME_ID": str})
    logs["SEASON"] = logs["SEASON_ID"].astype(str).str[1:].astype(int)
    seasons, downloaded = [], 0
    for start in range(FIRST_SEASON, current + 1):
        path = RAW / f"shots_{season_str(start)}.csv"
        if path.exists() and start != current:
            seasons.append(pd.read_csv(path, dtype={"GAME_ID": str}))
            continue
        print(f"  {season_str(start)} shot charts: downloading...", flush=True)
        df = download_season(season_str(start), logs.loc[logs["SEASON"] == start, "GAME_DATE"])
        df.to_csv(path, index=False)
        seasons.append(df)
        downloaded += 1
    shots = pd.concat(seasons)
    shots = shots[shots["GAME_ID"].isin(set(logs["GAME_ID"]))]
    shots.sort_values(["GAME_ID", "PLAYER_ID"]).to_csv(SHOTS, index=False)
    return downloaded


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = time.time()
    today = date.today()
    n = update(today.year if today.month >= 10 else today.year - 1)
    print(f"Saved {SHOTS.name}: {n} season(s) downloaded ({time.time() - t0:.0f}s)")
