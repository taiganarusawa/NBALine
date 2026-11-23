"""ESPN's live box scores: the live view's backup for when NBA.com's live feed doesn't answer.

NBA.com's feed comes first (live.py). It has NBA.com's own player IDs and says who is inactive. On
Nov 22, 2026 its bot protection turned away every request from this computer, so ESPN's public
scoreboard API (site.api.espn.com, what ESPN.com's scoreboard uses; free, no login) stands in. A game's
ESPN summary is translated into the shape of NBA.com's feed, so live.py reads either one the same way:

- the game: NBA.com's game ID -> ESPN's, found on ESPN's scoreboard for that date by the two teams;
- the players: ESPN's names -> NBA.com's player IDs, matched against our box scores (the same name;
  else without "Jr." or "III"; else the same team, last name and first initial);
- who's out: ESPN marks everyone who hasn't checked in yet as "did not play", so only a player its
  injury report lists as Out counts as inactive. ESPN's `active` means on the court right now;
- dunks: made shots whose play type is a dunk ("Driving Dunk Shot", "Alley Oop Dunk Shot", ...).
"""
import requests

from .board import TEAM_ALIASES, last_name_and_initial, name_key, name_key_no_suffix

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary"
HEADERS = {"User-Agent": "Mozilla/5.0 (NBALine personal project)"}
TIMEOUT = 5          # seconds; with NBA.com's 8 first, still well under the page's 25
GAME_STATUS = {"pre": 1, "in": 2, "post": 3}   # ESPN's status -> NBA.com's gameStatus
# ESPN box score column -> NBA.com's field (made-attempted columns give two)
_FIELDS = {
    "points": ("points",), "rebounds": ("reboundsTotal",), "assists": ("assists",), "steals": ("steals",),
    "blocks": ("blocks",), "turnovers": ("turnovers",), "fouls": ("foulsPersonal",),
    "offensiveRebounds": ("reboundsOffensive",), "defensiveRebounds": ("reboundsDefensive",),
    "fieldGoalsMade-fieldGoalsAttempted": ("fieldGoalsMade", "fieldGoalsAttempted"),
    "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("threePointersMade", "threePointersAttempted"),
    "freeThrowsMade-freeThrowsAttempted": ("freeThrowsMade", "freeThrowsAttempted"),
}

_events: dict[str, str] = {}   # NBA.com game ID -> ESPN event ID
_players: dict = {}            # the name lookup, rebuilt when the box scores change (_player_lookup)


def game_feed(feed: str, game_id: str, day, home: str, away: str) -> dict:
    """A game's "boxscore" or "playbyplay" from ESPN, in the shape of NBA.com's live feed (the parts
    live.py reads). day, home and away come from the schedule, to find the game on ESPN."""
    summary = _get(SUMMARY_URL, event=_event_id(game_id, day, home, away))
    ids = _nba_ids(summary)
    return _box_score(summary, ids) if feed == "boxscore" else _dunks(summary, ids)


def _get(url: str, **params) -> dict:
    r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _team(abbreviation: str) -> str:
    """ESPN's team abbreviation as NBA.com's ("GS" -> "GSW", "UTAH" -> "UTA")."""
    return TEAM_ALIASES.get(abbreviation, abbreviation)


def _event_id(game_id: str, day, home: str, away: str) -> str:
    """ESPN's ID for an NBA.com game, from ESPN's scoreboard for that date (looked up once per game)."""
    if game_id not in _events:
        for event in _get(SCOREBOARD_URL, dates=f"{day:%Y%m%d}").get("events", []):
            teams = {_team(c["team"]["abbreviation"]) for c in event["competitions"][0]["competitors"]}
            if teams == {home, away}:
                _events[game_id] = event["id"]
                break
        else:
            raise LookupError(f"ESPN's scoreboard for {day} has no {away} at {home} game")
    return _events[game_id]


# ---------------------------------------------------------------- players
def _player_lookup() -> dict:
    """Every player in our box scores, by name key: {"name": {key: [(id, team)]}, "no_suffix": ...,
    "team_last": {(team, last name, first initial): [id]}}. Each player once, with his latest team."""
    from . import lines   # it keeps the box scores loaded
    box = lines.box_scores()
    if _players.get("of") is not box:
        latest = box.sort_values("GAME_DATE").drop_duplicates("PLAYER_ID", keep="last")
        name, no_suffix, team_last = {}, {}, {}
        for pid, player, team in zip(latest["PLAYER_ID"], latest["PLAYER_NAME"], latest["TEAM_ABBREVIATION"]):
            name.setdefault(name_key(player), []).append((int(pid), team))
            no_suffix.setdefault(name_key_no_suffix(player), []).append((int(pid), team))
            team_last.setdefault((team, *last_name_and_initial(player)), []).append(int(pid))
        _players.update(of=box, name=name, no_suffix=no_suffix, team_last=team_last)
    return _players


def _match(player: str, team: str) -> int | None:
    """NBA.com's ID for a player ESPN names, on `team` tonight. Only a match that fits one player counts;
    when a name fits several (players from different years), the one on this team."""
    look = _player_lookup()
    for found in (look["name"].get(name_key(player), []), look["no_suffix"].get(name_key_no_suffix(player), [])):
        if len(found) > 1:
            found = [f for f in found if f[1] == team]
        if len(found) == 1:
            return found[0][0]
    found = look["team_last"].get((team, *last_name_and_initial(player)), [])   # "Nic" vs "Nicolas Claxton"
    return found[0] if len(found) == 1 else None


def _nba_ids(summary: dict) -> dict[str, int]:
    """{ESPN athlete ID: NBA.com player ID} for everyone in the game's box score we could match."""
    ids = {}
    for team in summary.get("boxscore", {}).get("players", []):
        for block in team["statistics"]:
            for a in block["athletes"]:
                pid = _match(a["athlete"]["displayName"], _team(team["team"]["abbreviation"]))
                if pid is not None:
                    ids[a["athlete"]["id"]] = pid
    return ids


# ---------------------------------------------------------------- translating to NBA.com's shape
def _box_score(summary: dict, ids: dict[str, int]) -> dict:
    """The game in NBA.com's live box score shape: status, clock, and each team's score and players."""
    game = summary["header"]["competitions"][0]
    status = game["status"]
    ruled_out = {i["athlete"]["id"] for t in summary.get("injuries", []) for i in t.get("injuries", [])
                 if i.get("status") == "Out"}
    teams = {c["team"]["id"]: dict(side=c["homeAway"], teamTricode=_team(c["team"]["abbreviation"]),
                                   score=int(c.get("score") or 0), players=[]) for c in game["competitors"]}
    for team in summary.get("boxscore", {}).get("players", []):
        for block in team["statistics"]:
            for a in block["athletes"]:
                if a["athlete"]["id"] in ids:
                    teams[team["team"]["id"]]["players"].append(
                        _player(a, block["keys"], ids[a["athlete"]["id"]], a["athlete"]["id"] in ruled_out))
    side = {t.pop("side"): t for t in teams.values()}
    return dict(source="ESPN", gameStatus=GAME_STATUS[status["type"]["state"]],
                gameStatusText=status["type"]["shortDetail"], period=int(status.get("period") or 0),
                gameClock=_clock(status.get("displayClock")), homeTeam=side["home"], awayTeam=side["away"])


def _player(a: dict, keys: list[str], pid: int, ruled_out: bool) -> dict:
    """One player in NBA.com's shape. ESPN's "did not play" only means he hasn't checked in yet."""
    shown = dict(zip(keys, a.get("stats") or []))
    stats = {}
    for column, fields in _FIELDS.items():
        values = str(shown.get(column, "")).split("-") if len(fields) == 2 else [shown.get(column)]
        stats.update(zip(fields, map(_number, values)))
    stats["minutes"] = f"PT{int(_number(shown.get('minutes'))):02d}M00.00S"
    out = ruled_out and a.get("didNotPlay")
    reason = (a.get("reason") or "").lower()    # "coach's decision", "right great toe sprain", ...
    if out and reason in ("", "coach's decision"):
        reason = "out"
    return dict(personId=pid, statistics=stats, played="0" if a.get("didNotPlay") else "1",
                status="INACTIVE" if out else "ACTIVE", oncourt="1" if a.get("active") else "0",
                notPlayingReason=reason if a.get("didNotPlay") else "")


def _number(shown) -> float:
    """'7' -> 7.0; '--', '' or None -> 0."""
    try:
        return float(shown)
    except (TypeError, ValueError):
        return 0.0


def _clock(shown: str | None) -> str:
    """ESPN's game clock as NBA.com writes it: '5:37' -> 'PT05M37.00S', '45.3' -> 'PT00M45.30S'."""
    if not shown:
        return ""
    minutes, _, seconds = shown.rpartition(":")
    return f"PT{int(minutes or 0):02d}M{float(seconds):05.2f}S"


def _dunks(summary: dict, ids: dict[str, int]) -> dict:
    """Made dunks as NBA.com's play-by-play actions (all live.py reads from the play-by-play)."""
    actions = []
    for play in summary.get("plays", []):
        kind = (play.get("type") or {}).get("text", "").lower()
        if play.get("scoringPlay") and play.get("shootingPlay") and "dunk" in kind and play.get("participants"):
            shooter = play["participants"][0]["athlete"]["id"]
            if shooter in ids:
                actions.append(dict(subType="DUNK", shotResult="Made", personId=ids[shooter]))
    return dict(actions=actions)
