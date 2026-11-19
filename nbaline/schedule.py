"""The NBA schedule: who plays whom, where, and when (official NBA data via nba_api).

    python schedule.py                 # today's games
    python schedule.py 2026-11-12      # another date
    python schedule.py --team GSW      # a team's next 5 games

predict.py uses this to fill in the opponent and home/away automatically, refuse
matchups that aren't on the schedule, and flag predictions made after tip-off.
The schedule is cached in data/ and refreshed when it's more than 3 hours old.
"""
import argparse
import sys
import time
from datetime import date, datetime, timezone

import pandas as pd

from .paths import DATA

MAX_AGE_HOURS = 3               # re-download the schedule when the saved copy is older than this
RETRY_AFTER_FAILURE_MIN = 15    # after a failed download, use the saved copy this long before retrying
_last_failure: dict = {}        # season -> when its download last failed (in this run of the program)
STATUS = {1: "scheduled", 2: "in progress", 3: "final"}


def season_of(d: date) -> str:
    start = d.year if d.month >= 8 else d.year - 1   # seasons start in October
    return f"{start}-{str(start + 1)[-2:]}"


def _download(season: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import scheduleleaguev2
    g = scheduleleaguev2.ScheduleLeagueV2(season=season, timeout=30).get_data_frames()[0]
    g = g[g["homeTeam_teamTricode"].astype(str).str.len() == 3]  # drop placeholder (TBD) games
    return pd.DataFrame({
        "GAME_ID": g["gameId"].astype(str),
        "GAME_DATE": pd.to_datetime(g["gameDate"], format="%m/%d/%Y %H:%M:%S").dt.date.astype(str),
        "TIPOFF_UTC": g["gameDateTimeUTC"].astype(str),
        "STATUS": g["gameStatus"].astype(int),
        "STATUS_TEXT": g["gameStatusText"].astype(str).str.strip(),
        "HOME": g["homeTeam_teamTricode"], "AWAY": g["awayTeam_teamTricode"],
        "POSTPONED": g["postponedStatus"].astype(str),
    })


def load(d: date, refresh: bool = False) -> pd.DataFrame:
    """Season schedule containing date d. Uses the cache if it's fresh; falls back to a stale
    cache (with a warning) if the NBA site can't be reached. After a failed download it waits
    RETRY_AFTER_FAILURE_MIN before trying again (unless refresh=True), so a slow NBA site
    doesn't make every prediction wait for a timeout."""
    season = season_of(d)
    path = DATA / f"schedule_{season}.csv"
    fresh = path.exists() and (time.time() - path.stat().st_mtime) < MAX_AGE_HOURS * 3600
    failed_recently = time.time() - _last_failure.get(season, 0) < RETRY_AFTER_FAILURE_MIN * 60
    if refresh or not (fresh or (failed_recently and path.exists())):
        try:
            DATA.mkdir(exist_ok=True)
            _download(season).to_csv(path, index=False)
        except Exception as e:
            _last_failure[season] = time.time()
            if not path.exists():
                raise RuntimeError(f"Couldn't download the {season} schedule ({e}). "
                                   "Use --no-schedule to enter the matchup yourself.") from e
            print(f"Warning: couldn't refresh the schedule ({e}); using the saved copy.", file=sys.stderr)
    return pd.read_csv(path, dtype={"GAME_ID": str})


def tipoff(row) -> datetime:
    return datetime.fromisoformat(row["TIPOFF_UTC"].replace("Z", "+00:00"))


def local_time(row) -> str:
    return tipoff(row).astimezone().strftime("%I:%M %p").lstrip("0")


def has_started(row) -> bool:
    return row["STATUS"] >= 2 or datetime.now(timezone.utc) >= tipoff(row)


def game_for(team: str, d: date):
    """The schedule row for this team's game on date d, or None."""
    s = load(d)
    g = s[(s["GAME_DATE"] == str(d)) & ((s["HOME"] == team) | (s["AWAY"] == team))]
    return None if g.empty else g.iloc[0]


def next_games(team: str, after: date, n: int = 1) -> pd.DataFrame:
    s = load(after)
    return s[(s["GAME_DATE"] >= str(after)) & ((s["HOME"] == team) | (s["AWAY"] == team))].head(n)


def missing_finals(have_ids: set, today: date | None = None, refresh: bool = False) -> pd.DataFrame:
    """Regular-season games from before today that should be finished (tipped off 4+ hours ago)
    but aren't in our data. Empty = data is up to date."""
    today = today or date.today()
    s = load(today, refresh=refresh)
    cutoff = datetime.now(timezone.utc) - pd.Timedelta(hours=4)
    tips = pd.to_datetime(s["TIPOFF_UTC"], utc=True)
    due = s[s["GAME_ID"].str.startswith("002") & (s["GAME_DATE"] < str(today)) & (tips < cutoff)
            & (s["POSTPONED"].astype(str) == "N")]
    return due[~due["GAME_ID"].isin(have_ids)]


def describe(row, team: str | None = None) -> str:
    if team:
        side = f"vs. {row['AWAY']} (home)" if row["HOME"] == team else f"at {row['HOME']} (away)"
        return f"{row['GAME_DATE']} {team} {side}, {local_time(row)}"
    return f"{row['AWAY']} at {row['HOME']}"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("date", nargs="?", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--team", help="show this team's next 5 games instead")
    args = ap.parse_args()
    d = date.fromisoformat(args.date) if args.date else date.today()
    if args.team:
        for _, r in next_games(args.team.upper(), d, 5).iterrows():
            print(describe(r, args.team.upper()))
        return
    s = load(d)
    day = s[s["GAME_DATE"] == str(d)]
    if day.empty:
        return print(f"No NBA games on {d}.")
    print(f"NBA games on {d} (times in your local time zone):")
    for _, r in day.iterrows():
        state = STATUS.get(r["STATUS"], "?") if r["STATUS"] != 2 else r["STATUS_TEXT"]
        print(f"  {local_time(r):>8}  {describe(r):<12}  {state}")


if __name__ == "__main__":
    main()
