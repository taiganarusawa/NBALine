"""Why a graded pick hit or missed, in plain words, from the box scores.

For each graded pick, what was different about his night, most telling first:
  * how unusual the night was ("his most rebounds in 20 games");
  * minutes against his usual (his last 10 games before this one), and what changed them:
    foul trouble, a blowout, overtime, a close game;
  * the game's pace, when it was fast or slow for his team;
  * for a combined stat (Pts+Rebs+Asts, ...), the part that rose most and the part that fell most;
  * shooting, for stats made of points or shots: a hot or cold night against his usual percentage,
    more or fewer shots than usual, and his share of his team's shots;
  * where the line sat, when his last 10 games were clearly on one side of it: a low line hit with an
    ordinary night (Scottie Barnes scored 20, under his usual 23.6, and still cleared 15.5 easily);
  * when none of these pushed it the way it went, how his number compared with his usual ("A big night:
    5 offensive rebounds (usually 2.2)."), so every hit or miss says why.
Each of these pushed his number up or down, so it's sorted by the way the pick went: "because" (what
pushed it the way it went: why it hit or missed) and "despite" (what pushed it the other way: it worked
against a hit, or helped a miss but not enough). More minutes on a Less that still hit is luck, not a
reason it hit. Then how close it finished, what the model expected, and (unless the line was already a
reason) where the line sat in his last 10 games.
For each entry, picks that won or lost together: several on one player ride on his one night, though the
entry odds treat every pick as independent. (Players in the same game barely move together: see lineup.py.)

Only what the numbers show is said. An injury during the game or a coach resting him shows up as
"only 14 min", without a reason, because the box score doesn't say why.
"""
from collections import defaultdict

import pandas as pd

from . import lines
from .payouts import STATS

USUAL_GAMES = 10       # "usually" = his average over his last 10 games before this one
UNUSUAL_GAMES = 10     # "his most ... in N games" is said from N = 10 up
LOOK_BACK = 100        # games searched for "his most ... in N games"
BLOWOUT = 20           # a final margin this big: starters usually sit the end of the game
CLOSE = 1.0            # finishing this near the line is a close call
LOW_LINE = 0.7         # over the line in 70%+ of his last 10 games: a low line for him (30% or less: a high one)
PACE_GAP = 5           # possessions per 48 minutes away from his team's usual: a fast or slow game
SHARE_GAP = 0.05       # his share of the team's shots this far from his usual: a bigger or smaller role
SHOT_COLUMNS = {"PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA"}
PART_NAMES = {"PTS": "points", "REB": "rebounds", "AST": "assists", "BLK": "blocks", "STL": "steals", "TOV": "turnovers"}
# stats with a natural plural, for "his most rebounds" / "his fewest points" (others: "his highest Pts+Rebs")
STAT_WORDS = {"Points": "points", "Rebounds": "rebounds", "Assists": "assists", "Steals": "steals",
              "Blocked Shots": "blocks", "Turnovers": "turnovers", "3-PT Made": "threes",
              "3-PT Attempted": "three-point attempts", "FG Made": "made shots", "FG Attempted": "shot attempts",
              "Free Throws Made": "free throws", "Free Throws Attempted": "free-throw attempts",
              "Offensive Rebounds": "offensive rebounds", "Defensive Rebounds": "defensive rebounds",
              "Two Pointers Made": "two-pointers", "Two Pointers Attempted": "two-point attempts",
              "Personal Fouls": "fouls", "Dunks": "dunks"}


def add_reasons(entries: list[dict]) -> list[dict]:
    """Graded entries with `why` (a one-line summary), `together` (picks that won or lost together)
    and `why` on each pick (its reasons)."""
    box = BoxScores(lines.box_scores())
    for e in entries:
        if e["status"] == "open":
            continue
        for pick in e["picks"]:
            pick["why"] = pick_reasons(pick, box)
        e["why"] = entry_summary(e["picks"])
        e["together"] = picks_together(e["picks"])
    return entries


class BoxScores:
    """The player box scores, each team's totals per game (added up from its players, the same rows
    picks are graded on), and each game's pace."""

    def __init__(self, players: pd.DataFrame):
        self.players = players
        totals = ["PTS", "FGA", "FG3A", "FTA", "OREB", "TOV", "MIN"]
        self.teams = (players.groupby(["GAME_ID", "TEAM_ABBREVIATION"], as_index=False)
                      .agg(GAME_DATE=("GAME_DATE", "first"), **{c: (c, "sum") for c in totals}))
        # possessions per 48 minutes (overtime doesn't make a game "fast"), averaged over both teams
        t = self.teams
        possessions = t["FGA"] + 0.44 * t["FTA"] - t["OREB"] + t["TOV"]
        self.pace = (possessions * 240 / t["MIN"]).groupby(t["GAME_ID"]).mean()

    def his_games(self, player_id) -> pd.DataFrame:
        his = self.players[self.players["PLAYER_ID"] == player_id]
        return his.assign(FG2M=his["FGM"] - his["FG3M"], FG2A=his["FGA"] - his["FG3A"])   # two-pointers

    def team_rows(self, game_ids, team: str) -> pd.DataFrame:
        """His team's box scores in these games."""
        t = self.teams
        return t[t["GAME_ID"].isin(set(game_ids)) & (t["TEAM_ABBREVIATION"] == team)]

    def usual_pace(self, team: str, before) -> float | None:
        """His team's average pace over its last 10 games before this date."""
        t = self.teams
        recent = t[(t["TEAM_ABBREVIATION"] == team) & (t["GAME_DATE"] < before)].sort_values("GAME_DATE").tail(USUAL_GAMES)
        return float(self.pace[recent["GAME_ID"]].mean()) if len(recent) else None


# ---------------------------------------------------------------- one entry
def entry_summary(picks: list[dict]) -> str:
    """'4 of 6 hit · missed on Flagg, Cunningham · 1 removed (push)'"""
    graded = [p for p in picks if p["result"] in ("hit", "miss")]
    parts = [f"{sum(p['result'] == 'hit' for p in graded)} of {len(graded)} hit"]
    missed = [_last_name(p) for p in picks if p["result"] == "miss"]
    if missed:
        parts.append("missed on " + ", ".join(dict.fromkeys(missed)))   # one name per player
    removed = [p for p in picks if p["result"] in ("void", "push")]
    if removed:
        why = {"push" if p["result"] == "push" else "didn’t play" for p in removed}
        parts.append(f"{len(removed)} removed ({', '.join(sorted(why))})")
    return " · ".join(parts)


def picks_together(picks: list[dict]) -> list[str]:
    """Picks that won or lost together: several on one player ('3 picks on Zubac all missed: one night
    decided all 3')."""
    graded = [p for p in picks if p["result"] in ("hit", "miss")]
    said = []
    by_player = defaultdict(list)
    for p in graded:
        by_player[p["player_id"]].append(p)
    for same in by_player.values():
        if len(same) < 2:
            continue
        hits, name, n = sum(p["result"] == "hit" for p in same), same[0]["player"], len(same)
        if hits in (0, n):
            every = "both" if n == 2 else f"all {n}"
            said.append(f"{n} picks on {name}, {every} {'hit' if hits else 'missed'}: one night decided {'both' if n == 2 else 'all of them'}.")
        else:
            said.append(f"{n} picks on {name}: {hits} hit, {n - hits} missed.")
    return said


# ---------------------------------------------------------------- one pick
Reason = tuple[str, int]   # (what was different, the way it pushed his number: 1 up, -1 down)


def pick_reasons(pick: dict, box: BoxScores) -> dict:
    """A graded pick's reasons: {"because": what pushed his number the way it went (why it hit or missed),
    "despite": what pushed it the other way, "context": how close it finished, what the model expected
    and his last 10 games}. Most telling first; all empty if its box score isn't downloaded."""
    if pick["result"] == "void":
        return dict(because=[], despite=[], context="He didn’t play, so PrizePicks removed the pick and the entry dropped a size.")
    if pick["result"] == "push":
        return dict(because=[], despite=[], context=f"He finished exactly on {_num(pick['line'])}, so PrizePicks removed the pick.")
    his = box.his_games(pick["player_id"])
    night = his[his["GAME_ID"] == str(pick["game_id"])]
    if night.empty:
        return dict(because=[], despite=[], context="")
    me = night.iloc[0]
    before = his[(his["GAME_DATE"] < me["GAME_DATE"]) & (his["MIN"] > 0)].sort_values("GAME_DATE")
    usual = before.tail(USUAL_GAMES)
    stat = pick["stat"]
    went = 1 if _value(me, stat) > pick["line"] else -1   # over or under the line
    line = _line(pick, usual)
    reasons = [r for r in (_unusual(stat, me, before), _minutes(me, usual, _final_score(box, me)), _pace(box, me),
                           *_parts(stat, me, usual), *_shooting(stat, me, usual, box), line) if r]
    because = [said for said, way in reasons if way == went]
    return dict(because=because or [r for r in [_night(pick, me, usual, went)] if r],
                despite=[said for said, way in reasons if way != went],
                context=_finish(pick, me, usual, recent=line is None))


def _value(rows, stat: str):
    """A PrizePicks stat from box score rows (a row or a whole table)."""
    return sum(w * rows[c] for c, w in STATS[stat].items())


def _unusual(stat: str, me: pd.Series, before: pd.DataFrame) -> Reason | None:
    """'His most rebounds in 20 games.' when no game in his last 10+ was as high (or as low)."""
    values = _value(before, stat).iloc[::-1].head(LOOK_BACK).tolist()   # newest first
    value = float(_value(me, stat))
    for most, beaten in ((True, lambda v: v >= value), (False, lambda v: v <= value)):
        games = next((i for i, v in enumerate(values) if beaten(v)), len(values))   # his games since one like it
        if games >= UNUSUAL_GAMES:
            word = STAT_WORDS.get(stat)
            what = f"{'most' if most else 'fewest'} {word}" if word else f"{'highest' if most else 'lowest'} {stat}"
            return f"His {what} in {games}{'+' if games == LOOK_BACK else ''} games.", 1 if most else -1
    return None


def _final_score(box: BoxScores, me: pd.Series) -> dict | None:
    """His team's final margin and how many overtimes (each adds 25 team minutes to 240)."""
    game = box.teams[box.teams["GAME_ID"] == me["GAME_ID"]]
    mine = game[game["TEAM_ABBREVIATION"] == me["TEAM_ABBREVIATION"]]
    theirs = game[game["TEAM_ABBREVIATION"] != me["TEAM_ABBREVIATION"]]
    if mine.empty or theirs.empty:
        return None
    mine, theirs = mine.iloc[0], theirs.iloc[0]
    return dict(team=me["TEAM_ABBREVIATION"], margin=int(mine["PTS"] - theirs["PTS"]),
                overtimes=max(round((float(mine["MIN"]) - 240) / 25), 0))   # player minutes add up to 240 a game


def _minutes(me: pd.Series, usual: pd.DataFrame, game: dict | None) -> Reason | None:
    """'Only 22 min (usually 33): 5 fouls, DAL lost by 29.' Nothing when he played about his usual."""
    if usual.empty:
        return None
    played, avg = float(me["MIN"]), float(usual["MIN"].mean())
    if abs(played - avg) < max(4, 0.12 * avg):
        return None
    causes = []
    if played < avg:
        fouls = int(me["PF"])
        if fouls >= 6:
            causes.append("fouled out")
        elif fouls == 5:
            causes.append("5 fouls")
        if game and abs(game["margin"]) >= BLOWOUT:
            causes.append(f"{game['team']} {'won' if game['margin'] > 0 else 'lost'} by {abs(game['margin'])}")
    elif game and game["overtimes"]:
        causes.append("overtime" if game["overtimes"] == 1 else f"{game['overtimes']} overtimes")
    elif game and abs(game["margin"]) <= 5:
        causes.append("a close game")
    said = f"{'Only' if played < avg else 'Played'} {played:.0f} min (usually {avg:.0f})"
    return said + (f": {', '.join(causes)}." if causes else "."), 1 if played > avg else -1


def _pace(box: BoxScores, me: pd.Series) -> Reason | None:
    """'A fast game: 106 possessions per 48 min (DAL usually 99).' (more possessions, more of every stat)"""
    usual = box.usual_pace(me["TEAM_ABBREVIATION"], me["GAME_DATE"])
    if usual is None or me["GAME_ID"] not in box.pace:
        return None
    pace = float(box.pace[me["GAME_ID"]])
    fast = pace - usual >= PACE_GAP
    if not (fast or usual - pace >= PACE_GAP):
        return None
    return (f"A {'fast' if fast else 'slow'} game: {pace:.0f} possessions per 48 min "
            f"({me['TEAM_ABBREVIATION']} usually {usual:.0f})."), 1 if fast else -1


def _parts(stat: str, me: pd.Series, usual: pd.DataFrame) -> list[Reason]:
    """For a combined stat, the part that raised it most and the part that lowered it most, when either
    moved it by 3 or more: '9 assists (usually 5.3).' Turnovers lower a Fantasy Score, so more of them
    pushes it down."""
    parts = [c for c in STATS[stat] if c in PART_NAMES]
    if len(parts) < 2 or usual.empty:
        return []
    moved = {c: STATS[stat][c] * (float(me[c]) - float(usual[c].mean())) for c in parts}   # in the stat's units
    said = []
    for way, c in ((1, max(moved, key=moved.get)), (-1, min(moved, key=moved.get))):
        if way * moved[c] >= 3:
            said.append((f"{int(me[c])} {PART_NAMES[c]} (usually {usual[c].mean():.1f}).", way))
    return said


# The shots behind each kind of stat: (made, tried, what to call them, fewest tries before his
# percentage says anything, how far from his usual percentage counts as hot or cold, how many more or
# fewer tries than usual count as a change).
SHOTS = {
    "field goals": ("FGM", "FGA", "shots", 5, 0.10, 4),
    "two-pointers": ("FG2M", "FG2A", "two-pointers", 4, 0.10, 3),
    "threes": ("FG3M", "FG3A", "threes", 3, 0.12, 2),
    "free throws": ("FTM", "FTA", "free throws", 4, 0.15, 3),
}


def _shots_for(columns: set) -> str:
    if columns in ({"FGM", "FG3M"}, {"FGA", "FG3A"}):
        return "two-pointers"   # Two Pointers Made / Attempted = field goals minus threes
    if not columns & {"PTS", "FGM", "FGA"}:
        if columns & {"FG3M", "FG3A"}:
            return "threes"
        if columns & {"FTM", "FTA"}:
            return "free throws"
    return "field goals"


def _shooting(stat: str, me: pd.Series, usual: pd.DataFrame, box: BoxScores) -> list[Reason]:
    """Hot or cold shooting, more or fewer shots than usual, and his share of the team's shots,
    for stats made of points or shots."""
    columns = set(STATS[stat])
    if not columns & SHOT_COLUMNS or usual.empty:
        return []
    kind = _shots_for(columns)
    made, tried, what, min_tries, hot, more = SHOTS[kind]
    counts_makes = not columns <= {"FGA", "FG3A", "FTA"}   # "FG Attempted" only cares how many he took
    said = [_accuracy(me, usual, made, tried, what, min_tries, hot) if counts_makes else None,
            _volume(me, usual, tried, what, more)]
    if kind in ("field goals", "threes"):
        said.append(_share(me, usual, box, "FGA" if kind == "field goals" else "FG3A", what))
    free_throws = float(me["FTM"]) - float(usual["FTM"].mean())
    if "PTS" in columns and abs(free_throws) >= 5:
        said.append((f"Made {int(me['FTM'])} free throws (usually {usual['FTM'].mean():.1f}).", 1 if free_throws > 0 else -1))
    return [s for s in said if s]


def _accuracy(me, usual, made: str, tried: str, what: str, min_tries: int, gap: float) -> Reason | None:
    """'Shot 12/20 (60%; usually 45%).' when he shot well above or below his usual percentage."""
    tries, usual_tries = float(me[tried]), float(usual[tried].sum())
    if tries < min_tries or usual_tries == 0:
        return None
    rate, usual_rate = float(me[made]) / tries, float(usual[made].sum()) / usual_tries
    if abs(rate - usual_rate) < gap:
        return None
    shot = f"Shot {int(me[made])}/{int(tries)}" if what == "shots" else f"Made {int(me[made])} of {int(tries)} {what}"
    return f"{shot} ({rate:.0%}; usually {usual_rate:.0%}).", 1 if rate > usual_rate else -1


def _volume(me, usual, tried: str, what: str, min_gap: float) -> Reason | None:
    """'Took only 9 shots (usually 17).' when he took far more or fewer than usual."""
    tries, avg = float(me[tried]), float(usual[tried].mean())
    if abs(tries - avg) < max(min_gap, 0.3 * avg):
        return None
    return f"Took {'only ' if tries < avg else ''}{int(tries)} {what} (usually {avg:.1f}).", 1 if tries > avg else -1


def _share(me, usual, box: BoxScores, tried: str, what: str) -> Reason | None:
    """'That was 28% of DAL's shots (usually 20%).' when his role in the offense grew or shrank."""
    team = me["TEAM_ABBREVIATION"]
    tonight = box.team_rows([me["GAME_ID"]], team)
    before = box.team_rows(usual["GAME_ID"], team)
    if tonight.empty or before.empty or float(tonight[tried].iloc[0]) == 0:
        return None
    mine = usual[usual["GAME_ID"].isin(set(before["GAME_ID"]))]   # his games for the same team
    share = float(me[tried]) / float(tonight[tried].iloc[0])
    usual_share = float(mine[tried].sum()) / float(before[tried].sum())
    if abs(share - usual_share) < SHARE_GAP:
        return None
    return f"That was {share:.0%} of {team}'s {what} (usually {usual_share:.0%}).", 1 if share > usual_share else -1


def _line(pick: dict, usual: pd.DataFrame) -> Reason | None:
    """'The line was low for him: 23.6 average in his last 10 games, over 15.5 in 9 of them.' when his
    recent games were clearly on one side of the line (a low line pushes toward over, a high one under)."""
    if len(usual) < 5:
        return None
    recent = _value(usual, pick["stat"])
    avg, over, n, line = float(recent.mean()), int((recent > pick["line"]).sum()), len(usual), _num(pick["line"])
    if over >= LOW_LINE * n and avg > pick["line"]:
        return f"The line was low for him: {avg:.1f} average in his last {n} games, over {line} in {over} of them.", 1
    if over <= (1 - LOW_LINE) * n and avg < pick["line"]:
        how_often = f"never over {line}" if over == 0 else f"over {line} in only {over}"
        return f"The line was high for him: {avg:.1f} average in his last {n} games, {how_often}.", -1
    return None


def _night(pick: dict, me: pd.Series, usual: pd.DataFrame, went: int) -> str | None:
    """When nothing else pushed it the way it went: how his number compared with his usual.
    'A big night: 5 offensive rebounds (usually 2.2).' or 'An ordinary night for him (7 rebounds;
    usually 7.1) went over 6.' (or 'Even a quiet night ...' when the line sat below even that)."""
    if usual.empty:
        return None
    value, avg = float(_value(me, pick["stat"])), float(_value(usual, pick["stat"]).mean())
    what, moved = f"{_num(value)} {STAT_WORDS.get(pick['stat'], pick['stat'])}", 1 if value > avg else -1
    ordinary = abs(value - avg) < max(1, 0.15 * avg)
    if not ordinary and moved == went:
        return f"A {'big' if moved > 0 else 'quiet'} night: {what} (usually {avg:.1f})."
    night = "An ordinary" if ordinary else f"Even a {'big' if moved > 0 else 'quiet'}"
    return f"{night} night for him ({what}; usually {avg:.1f}) {'went over' if went > 0 else 'stayed under'} {_num(pick['line'])}."


def _finish(pick: dict, me: pd.Series, usual: pd.DataFrame, recent: bool = True) -> str:
    """'Close: under by 0.5. The model expected 6.9. Last 10 games: 7.3 average, over 7.5 in 4.'
    recent: say where the line sat in his last 10 games (False when _line already said it)."""
    gap = float(_value(me, pick["stat"])) - pick["line"]
    said = [f"Close: {'over' if gap > 0 else 'under'} by {_num(abs(gap))}."] if abs(gap) <= CLOSE else []
    if pick.get("proj") is not None:
        said.append(f"The model expected {pick['proj']:.1f}.")
    if recent and len(usual):
        recent = _value(usual, pick["stat"])
        said.append(f"Last {len(usual)} games: {recent.mean():.1f} average, over {_num(pick['line'])} in {int((recent > pick['line']).sum())}.")
    return " ".join(said)


def _num(x) -> str:
    """7.0 -> '7', 7.5 -> '7.5'"""
    return f"{float(x):g}"


def _last_name(pick: dict) -> str:
    """'Cooper Flagg' -> 'Flagg', 'Jaren Jackson Jr.' -> 'Jackson Jr.'"""
    words = pick["player"].split()
    return " ".join(words[-2:]) if len(words) > 2 and words[-1].rstrip(".") in ("Jr", "Sr", "II", "III", "IV") else words[-1]
