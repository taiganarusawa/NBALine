"""Starting lineups from NBA.com: who started each past game, and who is starting tonight.

NBA.com's "Today's Starting Lineups" page reads one small file per day (free, no login):
    https://stats.nba.com/js/data/leaders/00_daily_lineups_20261116.json
Each game lists both teams' players: the five starters (with a position), then everyone else. Before
tip-off the starters are "Expected" (from team news and beat reporters), then "Confirmed" about 30
minutes before. The files go back to the first night of 2023-24, so the models learn from three-plus
seasons of who started, and see tonight's lineup as soon as it's posted.

    data/starters.csv   one row per player listed for a finished game:
                        GAME_DATE, GAME_ID, TEAM_ID, PLAYER_ID, STARTED (1 starter, 0 not), STATUS,
                        ACTIVE (0: on the inactive list, out for the game; blank in rows saved before it)
The inactive list is the official one teams submit before tip-off, so it also catches a late scratch
that the injury report doesn't.

    python -m nbaline.lineups       # download every game day that isn't saved yet
"""
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from .paths import PLAYER_LOGS, STARTERS

URL = "https://stats.nba.com/js/data/leaders/00_daily_lineups_{d:%Y%m%d}.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (NBALine personal project)"}
FIRST_DAY = date(2023, 10, 24)   # the first day NBA.com has a lineup file for
TODAY_EVERY = 5 * 60             # tonight's lineup is fetched again after this many seconds
COLUMNS = ["GAME_DATE", "GAME_ID", "TEAM_ID", "PLAYER_ID", "STARTED", "STATUS", "ACTIVE"]

_today: dict = {}                # day -> (time fetched, that day's lineups)


def fetch_day(day: date) -> pd.DataFrame | None:
    """Every player NBA.com lists for that day's games, or None if it has no file for the day."""
    try:
        r = requests.get(URL.format(d=day), headers=HEADERS, timeout=20, allow_redirects=False)
    except requests.RequestException:
        return None
    if r.status_code != 200:   # a day without a file redirects to an error page
        return None
    rows = []
    for game in r.json().get("games", []):
        for side in ("homeTeam", "awayTeam"):
            for pl in game[side]["players"]:
                rows.append((day.isoformat(), str(game["gameId"]), int(game[side]["teamId"]), int(pl["personId"]),
                             int(bool(pl.get("position"))), pl.get("lineupStatus") or "",
                             int(pl.get("rosterStatus") != "Inactive")))
    return one_row_each(pd.DataFrame(rows, columns=COLUMNS))


def one_row_each(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player and game. A player can be listed twice: among his team's expected starters and
    again on its confirmed roster (where nobody has a position until the confirmed lineup is out), or in
    both an expected and a confirmed lineup. A team with five confirmed starters goes by those, any other
    team by its expected starters; STATUS says which. A player inactive in either listing is inactive."""
    starter = df["STARTED"] == 1
    confirmed = starter & (df["STATUS"] == "Confirmed")
    team_confirmed = confirmed.groupby([df["GAME_ID"], df["TEAM_ID"]]).transform("sum") >= 5
    deciding = confirmed | (starter & ~team_confirmed)   # the starter rows that count
    starters = set(zip(df.loc[deciding, "GAME_ID"], df.loc[deciding, "PLAYER_ID"]))
    out = df.assign(STATUS=team_confirmed.map({True: "Confirmed", False: "Expected"}))
    if "ACTIVE" in out:
        out["ACTIVE"] = out.groupby(["GAME_ID", "PLAYER_ID"])["ACTIVE"].transform("min")
    out = out.drop_duplicates(["GAME_ID", "PLAYER_ID"]).copy()
    out["STARTED"] = [int(key in starters) for key in zip(out["GAME_ID"], out["PLAYER_ID"])]
    return out


def history() -> pd.DataFrame:
    """Who started each saved game: GAME_ID, PLAYER_ID, STARTED (empty if nothing is saved yet)."""
    if not STARTERS.exists():
        return pd.DataFrame(columns=["GAME_ID", "PLAYER_ID", "STARTED"])
    return pd.read_csv(STARTERS, dtype={"GAME_ID": str}, usecols=["GAME_ID", "PLAYER_ID", "STARTED"])


def update(pause: float = 0.3) -> int:
    """Download the lineups of every finished game day that isn't saved yet (and any day from the last
    few whose starters were still "Expected", for the confirmed ones). Returns how many days were added."""
    if not PLAYER_LOGS.exists():
        return 0
    played = pd.read_csv(PLAYER_LOGS, usecols=["GAME_DATE"])["GAME_DATE"].unique()
    saved = pd.read_csv(STARTERS, dtype={"GAME_ID": str}) if STARTERS.exists() else pd.DataFrame(columns=COLUMNS)
    # a recent day saved before its lineups were confirmed is fetched again (a few old files never were)
    recent = (date.today() - timedelta(days=3)).isoformat()
    unconfirmed = set(saved.loc[(saved["STARTED"] == 1) & (saved["STATUS"] != "Confirmed")
                                & (saved["GAME_DATE"] >= recent), "GAME_DATE"])
    todo = sorted(d for d in played if d >= FIRST_DAY.isoformat() and (d not in set(saved["GAME_DATE"]) or d in unconfirmed))
    added = []
    for i, d in enumerate(todo, 1):
        day = fetch_day(date.fromisoformat(d))
        if day is not None and len(day):
            added.append(day)
        if len(todo) > 20 and i % 50 == 0:
            print(f"    lineups: {i} of {len(todo)} days", flush=True)
        time.sleep(pause)   # be polite: one small file at a time
    if added:
        new = pd.concat(added)
        saved = pd.concat([saved[~saved["GAME_DATE"].isin(set(new["GAME_DATE"]))], new])
        saved.sort_values(["GAME_DATE", "GAME_ID", "TEAM_ID", "STARTED"], ascending=[True, True, True, False]) \
            .to_csv(STARTERS, index=False)
    return len(added)


def for_day(day: date) -> dict[int, tuple[int, str, bool]]:
    """Who's starting that day, for the teams whose lineup is posted:
    {player_id: (1 starter / 0 not, "Expected" | "Confirmed", on the inactive list)}.
    Today's (or a later day's) is fetched again every few minutes; a past day comes from starters.csv,
    or from NBA.com if it isn't saved."""
    df = None
    if day < date.today() and STARTERS.exists():
        s = pd.read_csv(STARTERS, dtype={"GAME_ID": str})
        df = s[s["GAME_DATE"] == day.isoformat()]
    if df is None or not len(df):
        hit = _today.get(day)
        if hit and time.time() - hit[0] < TODAY_EVERY:
            return hit[1]
        df = fetch_day(day)
    out = {}
    if df is not None and len(df):
        posted = df.groupby("TEAM_ID")["STARTED"].transform("sum") >= 5   # a team's lineup is posted: five starters
        inactive = df["ACTIVE"].eq(0) if "ACTIVE" in df else pd.Series(False, index=df.index)
        out = {int(r.PLAYER_ID): (int(r.STARTED), r.STATUS, bool(gone))
               for r, gone in zip(df[posted].itertuples(), inactive[posted])}
    if day >= date.today():
        _today[day] = (time.time(), out)
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    t0 = datetime.now()
    n = update()
    print(f"Saved {STARTERS.name}: {n} day(s) added ({(datetime.now() - t0).seconds}s)")
