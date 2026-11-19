"""Download NBA regular-season game logs (every player, every team) from stats.nba.com,
plus each season's shot chart for counting dunks (box scores don't have them), who started
each game since 2023-24 (NBA.com's daily lineups, nbaline/lineups.py), and each game's player
tracking: potential assists, rebound chances, drives, touches (nbaline/tracking.py).

Usage:
    python fetch_data.py              # last 10 seasons (incl. the current one)
    python fetch_data.py --seasons 3  # fewer seasons = faster

Past seasons are cached in data/raw/ and only downloaded once.
The current season is re-downloaded every run so you get the latest games.
"""
import argparse
import time
from datetime import date
import pandas as pd
from nba_api.stats.endpoints import leaguegamelog, shotchartdetail

from nbaline import lineups, tracking
from nbaline.paths import DUNKS, PLAYER_LOGS, RAW, TEAM_LOGS


def current_season_start(today: date | None = None) -> int:
    today = today or date.today()
    # NBA seasons start in October, so Jan-Sep belong to the season that began last year.
    return today.year if today.month >= 10 else today.year - 1


def season_str(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"  # e.g. 2025 -> "2025-26"


def with_retries(fetch, what: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            return fetch()
        except Exception as e:  # network hiccups are common with stats.nba.com
            print(f"    retry {attempt + 1}/3 after error: {e}")
            time.sleep(5)
    raise RuntimeError(f"Could not download {what}")


def download(season: str, kind: str) -> pd.DataFrame:
    """kind = 'P' for player logs, 'T' for team logs."""
    return with_retries(lambda: leaguegamelog.LeagueGameLog(
        season=season, player_or_team_abbreviation=kind, timeout=60).get_data_frames()[0],
        f"{kind} logs for {season}")


def download_dunks(season: str, game_dates: pd.Series) -> pd.DataFrame:
    """Made dunks per player per game, from the season's shot chart: every shot has a type, like
    "Alley Oop Dunk Shot". Everyone who took a shot gets a row, so 0-dunk games are kept too.
    The shot chart stops at about 100,000 shots per request (half a season), so it comes a month
    at a time, for each month that had games."""
    months = sorted({d[:7] for d in game_dates.astype(str)})  # "2025-11", ...
    parts = []
    for month in months:
        first = pd.Timestamp(month + "-01")
        last = first + pd.offsets.MonthEnd(0)
        parts.append(with_retries(lambda: shotchartdetail.ShotChartDetail(
            team_id=0, player_id=0, season_nullable=season, season_type_all_star="Regular Season",
            context_measure_simple="FGA", date_from_nullable=f"{first:%m/%d/%Y}",
            date_to_nullable=f"{last:%m/%d/%Y}", timeout=120).get_data_frames()[0], f"shots for {month}"))
        time.sleep(1)
    shots = pd.concat(parts)
    dunk = shots["ACTION_TYPE"].str.contains("Dunk", case=False)
    shots["DUNKS"] = (dunk & (shots["SHOT_MADE_FLAG"] == 1)).astype(int)
    return shots.groupby(["GAME_ID", "PLAYER_ID"], as_index=False)["DUNKS"].sum()


def season_file(path, start: int, cur: int, fetch, label: str, required: bool = True) -> pd.DataFrame:
    """One season's data: from the cache, or downloaded (the current season always is).
    A download that fails for an optional file (dunks) falls back to the last saved copy."""
    if path.exists() and start != cur:
        df = pd.read_csv(path, dtype={"GAME_ID": str})
        print(f"  {label}: cached ({len(df):,} rows)")
        return df
    print(f"  {label}: downloading...")
    try:
        df = fetch()
    except RuntimeError:
        if required or not path.exists():
            raise
        print(f"    failed: keeping the copy from {date.fromtimestamp(path.stat().st_mtime)}")
        return pd.read_csv(path, dtype={"GAME_ID": str})
    df.to_csv(path, index=False)
    print(f"    {len(df):,} rows")
    time.sleep(1.5)  # be polite to the API
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", type=int, default=10, help="how many seasons back to fetch")
    args = ap.parse_args()

    RAW.mkdir(parents=True, exist_ok=True)
    cur = current_season_start()
    starts = list(range(cur - args.seasons + 1, cur + 1))

    players, teams, dunks = [], [], []
    for start in starts:
        s = season_str(start)
        players.append(season_file(RAW / f"player_{s}.csv", start, cur, lambda: download(s, "P"), f"{s} P"))
        teams.append(season_file(RAW / f"team_{s}.csv", start, cur, lambda: download(s, "T"), f"{s} T"))
        dunks.append(season_file(RAW / f"dunks_{s}.csv", start, cur,
                                 lambda: download_dunks(s, players[-1]["GAME_DATE"]), f"{s} dunks", required=False))

    players, teams, dunks = pd.concat(players), pd.concat(teams), pd.concat(dunks)
    # The feed includes games that are still being played (partial box scores, no W/L yet).
    # Treating a halftime box score as a finished game would corrupt features and training.
    live = set(teams.loc[teams["WL"].isna(), "GAME_ID"].astype(str))
    if live:
        players = players[~players["GAME_ID"].astype(str).isin(live)]
        teams = teams[~teams["GAME_ID"].astype(str).isin(live)]
        print(f"\nSkipped {len(live)} game(s) still in progress (no final result yet)")
    players, teams = check_team_totals(players, teams)
    dunks = dunks[dunks["GAME_ID"].astype(str).isin(set(teams["GAME_ID"].astype(str)))]  # finished games only
    changed = [path.name for df, path in ((players, PLAYER_LOGS), (teams, TEAM_LOGS), (dunks, DUNKS))
               if save_if_changed(df, path)]
    print(f"\nSaved data/player_logs.csv, data/team_logs.csv and data/dunks.csv "
          f"({season_str(starts[0])} to {season_str(cur)}): "
          + (f"{', '.join(changed)} changed" if changed else "no new data"))
    # who started each new game (NBA.com's daily lineups): optional, like dunks; the next run catches up
    try:
        print(f"Saved data/starters.csv: {lineups.update()} new game day(s)")
    except Exception as e:
        print(f"Couldn't download the starting lineups ({type(e).__name__}: {e}); keeping the saved ones")
    # player tracking for each new game day (potential assists, rebound chances, touches, ...): optional too
    try:
        print(f"Saved data/tracking.csv: {tracking.update()} new game day(s)")
    except Exception as e:
        print(f"Couldn't download player tracking ({type(e).__name__}: {e}); keeping what's saved")


# Box score columns whose team total is the sum of its players' (shooting % and +/- follow from them).
# Not turnovers: a team's include team turnovers (shot clock, 8 seconds) that no player is charged with.
COUNTED = ["FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "OREB", "DREB", "REB", "AST", "STL", "BLK", "PF", "PTS"]
FULL_GAME = 235   # player minutes a team adds up to in a finished game: 240 (more in overtime), less a little rounding


def check_team_totals(players: pd.DataFrame, teams: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every team box score must add up to its players'. A download made as games finish can catch
    one side before the other: on 2026-11-11 UTA-ORL's team rows said 52-35 while its player rows
    were the whole game, and HOU-GSW's player rows were a few points short of its final team rows.
    Box scores only grow during a game, so the side with more is the more complete one:
      * players ahead (and their minutes show the whole game): the team row is rebuilt from them;
      * players behind: the game is left out of this download, and comes complete with a later one."""
    key = ["GAME_ID", "TEAM_ID"]
    sums = players.assign(GAME_ID=players["GAME_ID"].astype(str)).groupby(key)[COUNTED + ["TOV", "MIN"]].sum()
    t = teams.assign(GAME_ID=teams["GAME_ID"].astype(str)).set_index(key)
    have = t.index.intersection(sums.index)
    wrong = have[(t.loc[have, COUNTED] != sums.loc[have, COUNTED]).any(axis=1)]
    if wrong.empty:
        return players, teams

    players_ahead = (sums.loc[wrong, COUNTED] >= t.loc[wrong, COUNTED]).all(axis=1) & (sums.loc[wrong, "MIN"] >= FULL_GAME)
    full = list(wrong[players_ahead.to_numpy()])
    partial = sorted({game for game, _ in wrong} - {game for game, _ in full})
    full = [k for k in full if k[0] not in partial]   # a game is either rebuilt or left out, both teams alike
    for k in full:
        t.loc[k, COUNTED] = sums.loc[k, COUNTED].to_numpy()
        t.loc[k, "TOV"] = max(t.loc[k, "TOV"], sums.loc[k, "TOV"])        # team turnovers are at least the players'
        overtimes = max(round((sums.loc[k, "MIN"] - 240) / 25), 0)   # each overtime adds 25 team minutes
        t.loc[k, "MIN"] = 240 + 25 * overtimes
    for made, tried, pct in (("FGM", "FGA", "FG_PCT"), ("FG3M", "FG3A", "FG3_PCT"), ("FTM", "FTA", "FT_PCT")):
        rows = [k for k in full if t.loc[k, tried] > 0]
        t.loc[rows, pct] = (t.loc[rows, made] / t.loc[rows, tried]).round(3)
    for game in {game for game, _ in full}:   # the final score decides W/L and +/- for both teams
        both = t.loc[game]
        for team in both.index:
            margin = both.loc[team, "PTS"] - both.drop(team)["PTS"].sum()
            t.loc[(game, team), ["PLUS_MINUS", "WL"]] = [margin, "W" if margin > 0 else "L"]
    teams = t.reset_index()[teams.columns]
    if full:
        print(f"\nRebuilt {len(full)} team box score(s) from their players' (they didn't add up): "
              + ", ".join(f"{teams.loc[(teams['GAME_ID'] == g) & (teams['TEAM_ID'] == tm), 'TEAM_ABBREVIATION'].iloc[0]} {g}"
                          for g, tm in full))
    if partial:
        players = players[~players["GAME_ID"].astype(str).isin(partial)]
        teams = teams[~teams["GAME_ID"].isin(partial)]
        print(f"\nSkipped {len(partial)} game(s) whose player box scores weren't final yet "
              f"(they'll come with a later download): {', '.join(partial)}")
    return players, teams


def save_if_changed(df: pd.DataFrame, path) -> bool:
    """Save a CSV, but leave the file alone if nothing in it changed: the model inputs are rebuilt
    (about a minute) whenever these files are newer than the saved inputs."""
    text = df.to_csv(index=False).encode("utf-8")
    if path.exists() and path.read_bytes() == text:
        return False
    path.write_bytes(text)
    return True


if __name__ == "__main__":
    main()
