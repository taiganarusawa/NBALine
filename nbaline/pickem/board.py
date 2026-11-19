"""Reading a pasted PrizePicks board: turn whatever you copied into {player, stat, line} rows.

Two formats are understood:
  * the whole PrizePicks page (Ctrl+A, Ctrl+C): one "card" per projection, found by its game line
    ("vs MIL Tue 4:30pm"), with the team, More/Less buttons and pick counts around it;
  * lines typed or copied one per line: "Stephen Curry 28.5 Points", "Curry, Rebounds, 5.5".
Anything that can't be used safely (unknown or ambiguous names, half/quarter lines, stats with no
model, games on another day) is returned separately with the reason, never guessed.
"""
import re

_SYN = {
    "Points": ["points", "pts"],
    "Rebounds": ["rebounds", "rebs", "reb", "boards"],
    "Assists": ["assists", "asts", "ast"],
    "3-PT Made": ["3-ptmade", "3ptmade", "3-pointersmade", "3pointersmade", "threesmade", "3ptsmade", "3-ptsmade",
                  "3-pointmade", "3pointmade", "3-pointers", "3pointers", "threes", "3ptm", "3-ptm", "3pm", "3-pt", "3pt"],
    "Pts+Rebs+Asts": ["pts+rebs+asts", "points+rebounds+assists", "pra", "p+r+a"],
    "Pts+Rebs": ["pts+rebs", "points+rebounds", "p+r"],
    "Pts+Asts": ["pts+asts", "points+assists", "p+a"],
    "Rebs+Asts": ["rebs+asts", "rebounds+assists", "r+a"],
    "Steals": ["steals", "stl", "stls"],
    "Blocked Shots": ["blockedshots", "blocks", "blk", "blks"],
    "Blks+Stls": ["blks+stls", "blocks+steals", "stocks"],
    "Turnovers": ["turnovers", "tov", "to"],
    "Fantasy Score": ["fantasyscore", "fantasy", "fantasypoints"],
    "FG Attempted": ["fgattempted", "fieldgoalsattempted", "fieldgoalattempts", "fgattempts", "fgatt", "fga"],
    "FG Made": ["fgmade", "fieldgoalsmade", "fgm"],
    "3-PT Attempted": ["3-ptattempted", "3ptattempted", "3-pointersattempted", "3pointersattempted", "3-pointattempts",
                       "3ptattempts", "threesattempted", "3-ptatt", "3ptatt", "3pta", "3-pta"],
    "Free Throws Made": ["freethrowsmade", "ftmade", "ftm"],
    "Free Throws Attempted": ["freethrowsattempted", "freethrowattempts", "ftattempted", "ftatt", "fta"],
    "Offensive Rebounds": ["offensiverebounds", "offrebounds", "offreb", "oreb"],
    "Defensive Rebounds": ["defensiverebounds", "defrebounds", "defreb", "dreb"],
    "Two Pointers Made": ["twopointersmade", "2-pointersmade", "2pointersmade", "2-ptmade", "2ptmade", "2ptm", "2pm"],
    "Two Pointers Attempted": ["twopointersattempted", "2-pointersattempted", "2pointersattempted", "2-ptattempted",
                               "2ptattempted", "2-ptatt", "2ptatt", "2pta", "2pa"],   # PrizePicks: "2-PT Att"
    "Personal Fouls": ["personalfouls", "fouls", "pf"],
    "Double Doubles": ["doubledoubles", "doubledouble", "double-doubles", "double-double", "dbl-dbl", "dbldbl"],
    "Triple Doubles": ["tripledoubles", "tripledouble", "triple-doubles", "triple-double", "trp-dbl", "trpdbl"],
    "Dunks": ["dunks", "dunk"],
}
_SYN_LOOKUP = sorted(((syn, name) for name, syns in _SYN.items() for syn in syns), key=lambda x: -len(x[0]))
# lines for part of a game (1st half, 1Q, ...): skip rather than misread them as full-game lines
_PART = re.compile(r"\b(1st|2nd|3rd|4th|1h|2h|1q|2q|3q|4q|half|quarter|q1|q2|q3|q4)\b", re.I)
_NUM = re.compile(r"(?<![\d:.])(\d{1,3}(?:\.\d)?)(?![\d:%a-z\-.]|\s*(?:am|pm))", re.I)  # not "3-PT", "7:00", "8.5K"


def _norm(s: str) -> str:
    import unicodedata
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9+\-]", "", s)


def _find_stat(text: str) -> str | None:
    t = _norm(text)
    tokens = {_norm(w) for w in re.split(r"[\s,|/]+", text)}
    for syn, name in _SYN_LOOKUP:
        if (len(syn) > 3 and syn in t) or syn in tokens:  # short ones ("to", "reb") only as whole words
            return name
    return None


# What Ctrl+A on the PrizePicks board gives, one card per projection:
#   * 8.3K                  <- how many people picked it (optional)
#   Jayson TatumGoblin      <- the name from the player photo, ending in "Goblin" or "Demon" on those cards
#   BOS - F-G               <- team - position: starts a card
#   Jayson Tatum
#   @ PHI Tue 5:00pm
#   26.5
#   Points
#   LessMore                <- "More" alone = More-only line (Goblin/Demon, different payout)
_BULLET = re.compile(r"^[*•·]\s*")
_HDR = re.compile(r"^([A-Z]{2,4})\s*-\s*([GFC](?:\s*-\s*[GFC])*)$")
_KIND = re.compile(r"(Goblin|Demon)$")
_POP = re.compile(r"^\d+(?:\.\d+)?\s*[KM]$", re.I)
_GAME = re.compile(r"^((?i:vs\.?)|@)\s*([A-Z]{2,4})\b(.*)$")
_PURE = re.compile(r"^\d{1,3}(?:\.\d+)?$")
_DAY = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b")
_BTN = re.compile(r"^(?:less|more)(?:\s*(?:less|more))?$", re.I)
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TEAM_ALIASES = {"GS": "GSW", "NO": "NOP", "NOR": "NOP", "SA": "SAS", "NY": "NYK", "PHO": "PHX", "BRK": "BKN",
                "UTAH": "UTA", "WSH": "WAS", "CHO": "CHA", "NJ": "BKN"}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv"}


def _clean_lines(text: str) -> list[str]:
    return [_BULLET.sub("", l.strip()).strip() for l in text.splitlines() if l.strip()]


def board_days(text: str) -> set[str]:
    """Weekdays of the games on a copied PrizePicks page ({"Tue"}), empty if it doesn't show them."""
    out = set()
    for l in _clean_lines(text):
        g = _GAME.match(l)
        if g and (d := _DAY.search(g.group(3))):
            out.add(d.group(1))
    return out


def _cards(text: str) -> list[dict]:
    """Split a copied PrizePicks page into cards. Every card has a game line ("vs MIL Tue 4:30pm")
    right under the player's name, so cards are found from those; the team line above the name
    ("NYK - G") is used when it's there (some sections, like Trending, may leave it out)."""
    lines = _clean_lines(text)
    games = [i for i, l in enumerate(lines) if _GAME.match(l)]
    cards = []
    for k, gi in enumerate(games):
        name = lines[gi - 1] if gi >= 1 else None
        if name and (_HDR.match(name) or _POP.match(name) or _PURE.match(name) or _BTN.match(name)):
            name = None
        team = kind = None
        if name and gi >= 2 and (h := _HDR.match(lines[gi - 2])):
            team = TEAM_ALIASES.get(h.group(1), h.group(1))
            if gi >= 3 and (tag := _KIND.search(lines[gi - 3])):   # "Jayson TatumGoblin" above the team line
                kind = tag.group(1).lower()
        g = _GAME.match(lines[gi])
        c = dict(team=team, name=name, kind=kind, home=g.group(1) != "@", opp=TEAM_ALIASES.get(g.group(2), g.group(2)),
                 day=(d := _DAY.search(g.group(3))) and d.group(1), line=None, stat_text=None, sides=set())
        end = games[k + 1] - 1 if k + 1 < len(games) else len(lines)  # stop before the next card's name
        for l in lines[gi + 1: end]:
            if _POP.match(l) or _HDR.match(l):  # pick counts ("8.5K"), the next card's team line
                continue
            if _PURE.match(l) and c["stat_text"] is None:
                c["line"] = float(l)
            elif _BTN.match(l):
                c["sides"] |= {w for w in ("less", "more") if w in l.lower()}
            elif c["line"] is not None and c["stat_text"] is None:
                c["stat_text"] = l
        c["sides"] = "both" if len(c["sides"]) != 1 else c["sides"].pop()  # no buttons copied: assume both
        cards.append(c)
    return cards


def _key(n: str) -> str:
    return re.sub(r"[^a-z]", "", _norm(n))


def _key_nosfx(n: str) -> str:
    return _key(" ".join(w for w in n.split() if w.lower().rstrip(".") not in _SUFFIX))


def _parse_cards(cards: list[dict], player_names: list[str], teams: dict, day: str | None):
    def last_initial(n: str) -> tuple[str, str]:
        w = [x for x in n.split() if x.lower().rstrip(".") not in _SUFFIX] or n.split()
        return _key(w[-1]), _key(w[0])[:1]

    full = {_key(n): n for n in player_names}
    nosfx: dict = {}
    by_team_last: dict = {}
    for n in player_names:
        nosfx.setdefault(_key_nosfx(n), []).append(n)
        by_team_last.setdefault((teams.get(n), *last_initial(n)), []).append(n)

    def match(name: str, team: str):
        if _key(name) in full:
            return full[_key(name)]
        for cands in (nosfx.get(_key_nosfx(name), []),  # "Robert Williams" vs "Robert Williams III"
                      by_team_last.get((team, *last_initial(name)), [])):  # "Nic" vs "Nicolas" Claxton, same team
            if len(cands) == 1:
                return cands[0]
        return None

    found, unread, seen = [], [], set()
    for c in cards:
        line = f"{c['line']:g}" if c["line"] is not None else "?"
        team = f" ({c['team']})" if c["team"] else ""
        desc = f"{c['name'] or '?'}{team} {line} {c['stat_text'] or ''}".strip()
        if day and c["day"] and c["day"] != day:
            unread.append(f"{desc}: the game is on {c['day']} (change the date to rank it)")
            continue
        if c["line"] is None or not c["stat_text"] or not c["name"]:
            unread.append(f"{desc}: no line or stat found")
            continue
        st = None if _PART.search(c["stat_text"]) else _find_stat(c["stat_text"])
        if st is None:
            part = _PART.search(c["stat_text"])
            unread.append(f"{desc}: " + ("only full-game lines are modeled, not halves or quarters" if part
                                         else f"no model for {c['stat_text']} yet"))
            continue
        who = match(c["name"], c["team"])
        if who is None:
            unread.append(f"{desc}: not found among the players in that day's games")
            continue
        if (who, st, c["line"]) in seen:
            continue
        seen.add((who, st, c["line"]))
        found.append(dict(player=who, stat=st, line=c["line"], team=c["team"], opp=c["opp"], home=c["home"],
                          sides=c["sides"], kind=c["kind"]))
    return found, unread


def parse_board(text: str, player_names: list[str], teams: dict | None = None,
                day: str | None = None) -> tuple[list[dict], list[str]]:
    """Read pasted PrizePicks lines. Works with a whole copied PrizePicks page (Ctrl+A, Ctrl+C:
    cards with team, name, game, line, stat and the More/Less buttons), with one-line formats
    ("Stephen Curry 28.5 Points", "Curry, Rebounds, 5.5") and with other multi-line copies.
    `teams` maps each name to his team; `day` ("Tue") sets aside cards for games on other days.
    Returns (lines found, text that couldn't be used, with the reason)."""
    cards = _cards(text)
    if cards:
        return _parse_cards(cards, player_names, teams or {}, day)
    return _parse_lines(text, player_names)


def _parse_lines(text: str, player_names: list[str]) -> tuple[list[dict], list[str]]:
    names = {re.sub(r"[^a-z]", "", _norm(n)): n for n in player_names}
    last: dict = {}
    for n in player_names:  # last names that belong to exactly one player tonight ("Tatum")
        parts = [w for w in n.split() if w.lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv")]
        last.setdefault(re.sub(r"[^a-z]", "", _norm(parts[-1])), []).append(n)
    for ln, ns in last.items():
        if len(ln) >= 4 and len(ns) == 1:
            names.setdefault(ln, ns[0])
    shared = {ln for ln, ns in last.items() if len(ln) >= 4 and len(ns) > 1}  # e.g. two Greens
    by_len = sorted(names, key=len, reverse=True)

    def player_in(line: str):
        k = re.sub(r"[^a-z]", "", _norm(line))
        return next((names[n] for n in by_len if n and n in k), None)

    found, unread, seen = [], [], set()
    cur, num, stat, cur_text = None, None, None, ""

    def emit(player, line, st):
        key = (player, st, line)
        if key not in seen:
            seen.add(key)
            found.append(dict(player=player, stat=st, line=line))

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        skip = bool(_PART.search(line))
        who = player_in(line)
        nums = _NUM.findall(line)
        st = _find_stat(line) if not skip else None
        if who and nums and st:                       # everything on one line
            emit(who, float(nums[-1]), st)
            cur, num, stat = None, None, None
            continue
        if who:                                       # a new player card starts
            if cur and (num is not None or stat):
                unread.append(cur_text)
            cur, num, stat, cur_text = who, None, None, line
            continue
        words = {re.sub(r"[^a-z]", "", _norm(w)) for w in line.split()}
        if words & shared or (cur is None and nums and st):  # can't tell which player this is
            unread.append(line)
            cur, num, stat = None, None, None
            continue
        if cur is None:
            continue
        cur_text += " | " + line
        if skip:
            num, stat = None, None
            continue
        if nums and re.fullmatch(r"\s*\d{1,3}(\.\d)?\s*\S*\s*", line) or (nums and st):
            num = float(nums[-1])
        if st:
            stat = st
        if num is not None and stat:
            emit(cur, num, stat)
            num, stat = None, None                    # same player may have more lines
    return found, unread
