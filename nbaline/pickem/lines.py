"""Analyzing PrizePicks lines for the web app.

For each {player, stat, line} it returns the model's result (from predictor.analyze) plus:
  * the player's recent history against that line (his last 10 games before the game date);
  * for a game that's already over, the real number and which side of the line it landed on.
Results are cached for 20 minutes (5 while the player's starting lineup isn't confirmed, so a newly
posted one is picked up). Every pregame check is saved (store.log_checks) so it can be
graded after the games; checks of games already underway or finished are never saved. Once it has
earned it, the chance of More is adjusted to the model's record against PrizePicks (calibration.py).
"""
import time

import pandas as pd

from .. import features as F
from .. import lineups
from .. import predictor as P
from .. import schedule as S
from ..paths import PLAYER_LOGS
from . import calibration, store
from .payouts import entry_odds, stat_value

CACHE_SECONDS = 20 * 60
_results: dict = {}      # (date, player, stat, line) -> (time analyzed, result)
_box_scores: dict = {}   # the player logs, reloaded only when fetch_data.py writes new ones
_rechecked: dict = {}    # open entry pick id -> its latest re-check: {chance, proj, sd, usual_minutes}


def box_scores() -> pd.DataFrame:
    """Every player box score, reloaded only when the file on disk changes."""
    mtime = PLAYER_LOGS.stat().st_mtime
    if _box_scores.get("mtime") != mtime:
        p, _ = F.load_raw()
        _box_scores.update(df=p, mtime=mtime)
    return _box_scores["df"]


def clear_cache():
    """Forget cached analyses (after new data or a retrained model)."""
    _results.clear()


def current_rosters() -> pd.DataFrame:
    """Each player's most recent game this season (which team he's on now)."""
    p = box_scores()
    return p[p["SEASON"] == p["SEASON"].max()].sort_values("GAME_DATE").drop_duplicates("PLAYER_ID", keep="last")


def games_on(day: pd.Timestamp) -> pd.DataFrame:
    s = S.load(day.date())
    return s[s["GAME_DATE"] == str(day.date())]


def teams_on(day: pd.Timestamp) -> dict[str, str]:
    """{player name: team} for everyone on a team that plays on this date."""
    games = games_on(day)
    teams = set(games[["HOME", "AWAY"]].values.ravel())
    cur = current_rosters()
    cur = cur[cur["TEAM_ABBREVIATION"].isin(teams)]
    return dict(zip(cur["PLAYER_NAME"], cur["TEAM_ABBREVIATION"]))


def players_on(day: pd.Timestamp) -> list[dict]:
    """Everyone playing on this date with team, opponent and tip-off (for the name autocomplete)."""
    cur, out = current_rosters(), []
    for g in games_on(day).to_dict("records"):
        for team, opp, home in ((g["HOME"], g["AWAY"], True), (g["AWAY"], g["HOME"], False)):
            for r in cur[cur["TEAM_ABBREVIATION"] == team].itertuples():
                out.append(dict(name=r.PLAYER_NAME, team=team, opp=opp, home=home, tip=S.local_time(g)))
    return sorted(out, key=lambda x: (x["team"], x["name"]))


def last_games(player_ids: set, before: pd.Timestamp, n: int = 10) -> dict[int, list[dict]]:
    """Each player's last n box scores before `before`, oldest first (one pass over the logs)."""
    p = box_scores()
    g = p[p["PLAYER_ID"].isin(player_ids) & p["PTS"].notna() & (p["GAME_DATE"] < before)]
    g = g.sort_values("GAME_DATE").groupby("PLAYER_ID").tail(n)
    return {pid: d.to_dict("records") for pid, d in g.groupby("PLAYER_ID")}


def history(games: list[dict], stat: str, line: float) -> dict:
    """From his last 10 games (last_games): average, and how many went over this line."""
    games = [(f"{r['GAME_DATE']:%m/%d}", stat_value(r, stat)) for r in games]
    games = [(d, v) for d, v in games if v == v]  # skip games without the number yet (dunks: shot chart pending)
    dates, vals = [d for d, _ in games], [v for _, v in games]
    return dict(avg10=round(sum(vals) / len(vals), 1) if vals else None,
                over10=sum(v > line for v in vals), n10=len(vals),
                recent=[(d, round(v, 1)) for d, v in zip(dates, vals)][-8:])


def final_result(analysis: dict, stat: str, line: float, day: pd.Timestamp) -> dict:
    """For a game that's over: the player's real number and which side of the line it landed on."""
    if not analysis.get("started"):
        return {}
    p = box_scores()
    game = p[(p["GAME_DATE"] == day) & (p["GAME_ID"].astype(str) == str(analysis.get("game_id")))]
    if game.empty:
        return {}  # still being played (or not downloaded yet)
    me = game[game["PLAYER_ID"] == analysis["player_id"]]
    if me.empty:
        return dict(final=True, actual=None, outcome="dnp")
    actual = stat_value(me.iloc[0].to_dict(), stat)
    if actual != actual:
        return {}  # NaN: this number isn't downloaded yet (dunks come from the shot chart)
    return dict(final=True, actual=round(actual, 1),
                outcome="push" if actual == line else "over" if actual > line else "under")


# fields copied from the predictor's result into what the web app receives
_GAME_FIELDS = ("player_id", "team", "opp", "home", "game_date", "game_id", "tip_local", "started",
                "injury_report", "injury_missing", "injury_notes", "self_status", "outs", "questionable",
                "lineup", "start_rate")
_MODEL_FIELDS = ("proj", "q10", "q50", "q90", "sd", "usual_minutes", "p_over", "p_push", "reasons")   # sd, usual_minutes: the live chance


def _keep_for(item: dict) -> float:
    """How long a cached result stays good: CACHE_SECONDS, but only a few minutes while the game hasn't
    started and his lineup isn't confirmed yet, so a newly posted (or changed) lineup is picked up."""
    settled = item.get("error") or item.get("started") or (item.get("lineup") or {}).get("status") == "Confirmed"
    return CACHE_SECONDS if settled else lineups.TODAY_EVERY


def analyze_lines(rows: list[dict], day: pd.Timestamp) -> list[dict]:
    """Model results for each {player, stat, line[, line_type]}, in the same order. Once the model has
    a long enough record against PrizePicks, its chance of More is adjusted to that record (see
    calibration.py); the saved checks always keep the model's own chance."""
    return calibration.adjust_lines(_model_results(rows, day), [r.get("line_type") for r in rows])


def _model_results(rows: list[dict], day: pd.Timestamp) -> list[dict]:
    """The model's own results (cached), saving each pregame check for grading."""
    out, todo = [None] * len(rows), []
    for i, r in enumerate(rows):
        key = (str(day.date()), P.norm(r["player"]), r["stat"], float(r["line"]))
        hit = _results.get(key)
        if hit and time.time() - hit[0] < _keep_for(hit[1]):
            out[i] = hit[1]
        else:
            todo.append((i, key, r))
    if not todo:
        return out

    requests = [dict(player=r["player"], line=float(r["line"]), stat=r["stat"], opp=None, home=None, out=[])
                for _, _, r in todo]
    to_save = []
    analyzed = P.analyze(requests, day)
    recent = last_games({a["player_id"] for a in analyzed if not a.get("error")}, day)
    for (i, key, r), a in zip(todo, analyzed):
        item = dict(player=a["player"], stat=r["stat"], line=float(r["line"]), error=a.get("error"))
        if not a.get("error"):
            item.update({k: a[k] for k in _GAME_FIELDS}, modeled=a["modeled"], reliable=a["reliable"],
                        yes_no=a["yes_no"], low_minutes=a["low_minutes"])
            if a["modeled"]:
                item.update({k: a[k] for k in _MODEL_FIELDS})
            item["history"] = history(recent.get(a["player_id"], []), r["stat"], float(r["line"]))
            item.update(final_result(a, r["stat"], float(r["line"]), day))
            if not a["started"]:  # only real pregame checks count toward the model's record
                to_save.append(dict(item, p_over=item.get("p_over"), proj=item.get("proj"),
                                    line_type=r.get("line_type")))
        _results[key] = (time.time(), item)
        out[i] = item
    if to_save:
        store.log_checks(to_save)
    return out


def recheck_open_entries(entries: list[dict]) -> dict:
    """For entries not graded yet: each pick's chance of hitting with the latest data, model and
    injury report, and the entry's expected return with those chances. The chances saved with the
    entry are never changed; this is only for comparing against them.
    Returns {"picks": {pick_id: chance or None}, "entries": {entry_id: expected return or None}}."""
    open_entries = [e for e in entries if e["status"] == "open"]
    picks_by_day: dict = {}
    for e in open_entries:
        for p in e["picks"]:
            picks_by_day.setdefault(p["game_date"], []).append(p)

    chance = {}
    for day, picks in picks_by_day.items():
        rows = [dict(player=p["player"], stat=p["stat"], line=p["line"], line_type=p.get("line_type")) for p in picks]
        for p, r in zip(picks, analyze_lines(rows, pd.Timestamp(day))):
            p_over = None if r.get("error") else r.get("p_over")
            chance[p["id"]] = None if p_over is None else p_over if p["side"] == "more" else 1 - p_over
            if chance[p["id"]] is not None:   # kept for the entry's chances during the games (live.py)
                _rechecked[p["id"]] = dict(chance=chance[p["id"]], push=r.get("p_push"), proj=r.get("proj"),
                                           sd=r.get("sd"), usual_minutes=r.get("usual_minutes"))

    expected = {}
    for e in open_entries:
        probs = [chance.get(p["id"]) for p in e["picks"]]
        has_table = str(len(probs)) in e["payouts"].get(e["kind"], {})
        expected[e["id"]] = (entry_odds(probs, e["kind"], e["payouts"])["ev"]
                             if has_table and all(x is not None for x in probs) else None)
    return {"picks": chance, "entries": expected}


def rechecked() -> dict:
    """The latest re-check of each open entry's picks (this server, since it started):
    {pick_id: {"chance": its chance of hitting, "push": of landing exactly on the line, "proj", "sd",
    "usual_minutes"}}."""
    return dict(_rechecked)
