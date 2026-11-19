"""Live scores for open entries: each pick's stat so far, and whether it has already won or lost.

Source: the NBA's live data feed (cdn.nba.com, what NBA.com's live box scores use; free, no login).
A game is only fetched once it has tipped off, and at most every CACHE_SECONDS, however often the
page asks; a page's games are fetched side by side. Box scores don't count dunks, so for dunk picks
the game's play-by-play is read too (made shots of type DUNK).

Each fetch is a fresh request that keeps no cookies. The feed's bot protection tracks a connection by
its cookies, and one connection kept all night (nba_api's shared session) got flagged and stopped
getting answers (Nov 18, 2026). If a check fails anyway, the game keeps the last numbers the feed sent,
its picks say so (feed_down), the page keeps checking every 15 seconds, and the server window says
why the feed stopped answering and when it answers again.

A pick is decided before the final buzzer as soon as the player passes the line: every stat only goes
up during a game (except fantasy score, which turnovers lower), so More has won and Less has lost.
"""
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
import requests

from .. import schedule as S
from . import ingame
from .payouts import outcome_chances, settle, stat_value

FEED_URL = "https://cdn.nba.com/static/json/liveData/{feed}/{feed}_{game_id}.json"   # boxscore, playbyplay
FEED_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://www.nba.com/",
                "Accept": "application/json"}
FEED_TIMEOUT = 8            # seconds to wait for the feed (the page gives up on the server after 25)
CACHE_SECONDS = 10          # under the page's 15-second refresh, so each refresh gets fresh numbers
LIVE, FINAL = 2, 3          # the feed's gameStatus (1 = not started)
CAN_GO_DOWN = {"Fantasy Score"}
YES_NO = {"Double Doubles", "Triple Doubles"}   # no "pace" for these: he has one or he doesn't
_START_FROM = ("proj", "sd", "usual_minutes")   # what the live chance takes from the latest re-check
# live feed field -> box score column (the names grading and the models use)
_COLUMNS = {"points": "PTS", "reboundsTotal": "REB", "assists": "AST", "steals": "STL", "blocks": "BLK",
            "turnovers": "TOV", "fieldGoalsAttempted": "FGA", "fieldGoalsMade": "FGM",
            "threePointersAttempted": "FG3A", "threePointersMade": "FG3M", "freeThrowsAttempted": "FTA",
            "freeThrowsMade": "FTM", "reboundsOffensive": "OREB", "reboundsDefensive": "DREB",
            "foulsPersonal": "PF"}


# ---------------------------------------------------------------- the feed
@dataclass(frozen=True)
class _Feed:
    """One game's box score or play-by-play, as of its latest check."""
    checked: float          # when the feed was last asked (time.time())
    data: dict | None       # the latest numbers it sent, kept through failed checks (None: none yet)
    error: str = ""         # why the latest check failed ("" = it answered)


_feeds: dict[tuple[str, str], _Feed] = {}   # (feed, game_id) -> its latest check


def _fetch(feed: str, game_id: str) -> _Feed:
    """A game's feed ("boxscore" or "playbyplay"), asked again once CACHE_SECONDS have passed."""
    last = _feeds.get((feed, game_id))
    if last and time.time() - last.checked < CACHE_SECONDS:
        return last
    try:   # requests.get, not a shared session: no cookies carried from one check to the next
        r = requests.get(FEED_URL.format(feed=feed, game_id=game_id), headers=FEED_HEADERS, timeout=FEED_TIMEOUT)
        r.raise_for_status()
        now = _Feed(time.time(), r.json()["game"])
    except Exception as e:   # no file yet (just after tip-off), blocked, or a network hiccup: try again next time
        now = _Feed(time.time(), last.data if last else None, f"{type(e).__name__}: {e}"[:300])
    if bool(now.error) != bool(last and last.error):   # in the server window: when it stops or starts answering
        print(f"[live] NBA.com's {feed} feed for game {game_id} "
              + (f"isn't answering: {now.error}" if now.error else "is answering again"), file=sys.stderr, flush=True)
    _feeds[(feed, game_id)] = now
    return now


def _minutes(iso: str) -> float:
    """'PT25M01.00S' -> 25.0"""
    try:
        return float(iso[2:iso.index("M")])
    except ValueError:
        return 0.0


def _clock_left(iso: str) -> float:
    """'PT05M30.00S' -> 5.5 minutes left in the period."""
    try:
        return float(iso[2:iso.index("M")]) + float(iso[iso.index("M") + 1:-1]) / 60
    except ValueError:
        return 0.0


def _share_played(game: dict) -> float | None:
    """How much of the game has been played, 0 to 1 (0.5 at halftime, 1 at the final buzzer).
    Quarters are 12 minutes, overtimes 5; in overtime the game "ends" with the current period."""
    if game["gameStatus"] == FINAL:
        return 1.0
    period = int(game.get("period") or 0)
    if game["gameStatus"] != LIVE or period < 1:
        return None
    length = 12 if period <= 4 else 5
    before = 12 * min(period - 1, 4) + 5 * max(period - 5, 0)
    total = 48 + 5 * max(period - 4, 0)
    return min((before + length - _clock_left(game.get("gameClock") or "")) / total, 1.0)


def _pace(value: float, line: float, share: float | None, stat: str) -> dict:
    """PrizePicks-style pace: where he finishes if he keeps this rate for the rest of the game, as a
    share of the line (80% = on pace for 4 on a line of 5). At the final buzzer it's simply value / line.
    None in the first minute (no rate yet) and for yes/no stats (double-doubles)."""
    if share is None or share < 1 / 48 or line <= 0 or stat in YES_NO:
        return {}
    projected = value / share
    return dict(projected=round(projected, 1), pace=round(max(projected, 0) / line, 3))


def _clock(game: dict) -> str:
    """'Q3 5:32', 'Halftime', 'Final', ..."""
    text = game["gameStatusText"].strip()
    if game["gameStatus"] != LIVE:
        return text
    secs = game.get("gameClock") or ""
    if not secs.startswith("PT") or secs in ("PT00M00.00S", "PT00M00S"):
        return text                             # "Half", "End of 3rd Qtr"
    m, s = int(secs[2:secs.index("M")]), int(float(secs[secs.index("M") + 1:-1]))
    period = game["period"]
    name = f"Q{period}" if period <= 4 else ("OT" if period == 5 else f"OT{period - 4}")
    return f"{name} {m}:{s:02d}"


def _player_rows(game: dict) -> dict:
    """{player_id: box score row} with the same column names as the downloaded box scores."""
    rows = {}
    for team in (game["homeTeam"], game["awayTeam"]):
        for pl in team["players"]:
            st = pl["statistics"]
            row = {col: float(st.get(field, 0) or 0) for field, col in _COLUMNS.items()}
            tens = sum(row[c] >= 10 for c in ("PTS", "REB", "AST", "STL", "BLK"))
            row.update(DD=float(tens >= 2), TD=float(tens >= 3), MIN=_minutes(st.get("minutes", "")),
                       played=pl.get("played") == "1", active=pl.get("status") == "ACTIVE",
                       on_court=pl.get("oncourt") == "1", why_out=pl.get("notPlayingReason") or "")
            rows[int(pl["personId"])] = row
    return rows


def _dunks(game_id: str) -> dict:
    """{player_id: made dunks so far}"""
    pbp = _fetch("playbyplay", game_id).data
    out = {}
    for a in (pbp or {}).get("actions", []):
        if a.get("subType") == "DUNK" and a.get("shotResult") == "Made":
            out[int(a["personId"])] = out.get(int(a["personId"]), 0) + 1
    return out


# ---------------------------------------------------------------- one pick
def judge(side: str, line: float, value: float, final: bool, can_go_down: bool) -> str:
    """'hit' / 'miss' / 'push' once decided, else 'live'."""
    if final:
        if value == line:
            return "push"
        return "hit" if (value > line) == (side == "more") else "miss"
    if value > line and not can_go_down:     # past the line already: More won, Less lost
        return "hit" if side == "more" else "miss"
    return "live"


def _still_needed(side: str, line: float, value: float, whole_numbers: bool) -> str:
    if side == "more":
        need = (math.floor(line) + 1 - value) if whole_numbers else (line - value)
        return f"needs {need:g}" if whole_numbers else f"{need:.1f} to go"
    if value == line:
        return "on the line"
    room = (math.ceil(line) - 1 - value) if whole_numbers else (line - value)
    if not whole_numbers:
        return f"{room:.1f} under"
    return "can't take another" if room == 0 else f"room for {room:g}"


def _pick_now(p: dict, game: dict | None, rows: dict, dunks: dict | None, tip: dict | None = None,
              feed_down: bool = False) -> dict:
    """feed_down: the feed didn't answer the latest check, so `game` is the last it sent (or None)."""
    if game is None and feed_down:   # tipped off, but the feed hasn't sent the game: in play, no numbers yet
        return dict(state="live", text="waiting for NBA.com's live feed", feed_down=True)
    if game is None:   # not started: when it tips off, if the schedule says ("starts 7:30 PM")
        return dict(state="pending", text=f"starts {tip['tip']}" if tip else "not started", **(tip or {}))
    started, final = game["gameStatus"] >= LIVE, game["gameStatus"] == FINAL
    out = dict(clock=_clock(game), game_live=game["gameStatus"] == LIVE, game_final=final)
    if feed_down:
        out["feed_down"] = True
    if started:   # {"UTA": 98, "MIA": 102}
        out["score"] = {t["teamTricode"]: int(t.get("score") or 0) for t in (game["homeTeam"], game["awayTeam"])}
    row = rows.get(int(p["player_id"]))
    if row is None or (started and not row["active"]) or (final and not row["played"]):
        why = row["why_out"] if row else ""
        return dict(out, state="void", text=f"not playing{f' ({why})' if why else ''}")
    if p["stat"] == "Dunks":
        row = dict(row, DUNKS=float((dunks or {}).get(int(p["player_id"]), 0)))
    value = round(stat_value(row, p["stat"]), 1)
    state = judge(p["side"], p["line"], value, final, p["stat"] in CAN_GO_DOWN)
    text = {"hit": "✓ hit", "miss": "✗ lost", "push": "push"}.get(state) or \
        _still_needed(p["side"], p["line"], value, p["stat"] not in CAN_GO_DOWN)
    share = _share_played(game)
    now = dict(out, state=state, value=value, minutes=row["MIN"], text=text,
               on_court=out["game_live"] and row["on_court"], **_pace(value, p["line"], share, p["stat"]))
    # the model's chance from here, when the line came with its pre-game projection (see ingame.py)
    chance = state == "live" and ingame.live_chance(p["stat"], p["line"], p.get("proj"), p.get("sd"),
                                                    p.get("usual_minutes"), value, row["MIN"], share)
    if chance:
        now.update(live_more=round(chance["more"], 4), live_push=round(chance["push"], 4), live_expected=chance["expected"])
    return now


# ---------------------------------------------------------------- all open entries
def _game_states(picks: list[dict]) -> tuple[dict, dict, set]:
    """({game_id: its live box score, the latest the feed sent; None if it hasn't tipped off or the feed
         hasn't sent it yet},
        {game_id: when a game that hasn't tipped off starts: {"tip": "7:30 PM", "tip_utc": ...}},
        {game_id: tipped off, but the feed didn't answer the latest check}).
    Only games from today or earlier that have reached tip-off time are fetched."""
    now, today = datetime.now(timezone.utc), date.today()
    tipped, tips = [], {}
    for day, ids in pd.DataFrame(picks).groupby("game_date")["game_id"]:
        day = pd.Timestamp(day).date()
        schedule = {str(r["GAME_ID"]): r for r in S.load(day).to_dict("records")}
        for g in set(ids):
            row = schedule.get(str(g))
            if day <= today and (row is None or now >= S.tipoff(row)):
                tipped.append(g)
            elif row is not None:   # another day's game also says which day
                time_shown = S.local_time(row) if day == today else f"{day:%a} {S.local_time(row)}"
                tips[g] = dict(tip=time_shown, tip_utc=row["TIPOFF_UTC"])
    with ThreadPoolExecutor(max_workers=8) as pool:   # side by side: one slow game doesn't hold up the rest
        feeds = dict(zip(tipped, pool.map(lambda g: _fetch("boxscore", str(g)), tipped)))
    return {g: f.data for g, f in feeds.items()}, tips, {g for g, f in feeds.items() if f.error}


def picks_now(picks: list[dict]) -> dict:
    """Live state of each pick: {id: {state, text, value, minutes, clock, game_live, on_court, pace, ...}}.
    A pick needs id, player_id, game_id, game_date, stat, line and side ("more" / "less")."""
    picks = [p for p in picks if p.get("game_id")]
    if not picks:
        return {}
    games, tips, down = _game_states(picks)
    rows = {g: _player_rows(b) for g, b in games.items() if b}
    need_dunks = {p["game_id"] for p in picks if p["stat"] == "Dunks" and games.get(p["game_id"])}
    dunks = {g: _dunks(g) for g in need_dunks}
    return {p["id"]: _pick_now(p, games.get(p["game_id"]), rows.get(p["game_id"], {}), dunks.get(p["game_id"]),
                               tips.get(p["game_id"]), p["game_id"] in down)
            for p in picks}


def lines_live(lines: list[dict]) -> dict:
    """Check lines and Best lines: the same live state for lines you checked or pasted (side = the
    model's pick), plus the model's chance from here (live_more) for lines sent with their pre-game
    proj, sd and usual_minutes. {"picks": {id: {...}}, "live": one is still being played,
    "feed_down": NBA.com's feed didn't answer for one}"""
    now = picks_now(lines)
    return dict(picks=now, live=any(v["state"] in ("live", "pending") or v.get("game_live") for v in now.values()),
                feed_down=any(v.get("feed_down") for v in now.values()))


def open_entries_live(entries: list[dict], latest: dict | None = None) -> dict:
    """Live state of every pick in an open entry, what each entry can still pay, and how likely each
    amount is now (odds: payouts.outcome_chances).
    latest: each pick's latest pre-game re-check, {pick_id: {chance, proj, sd, usual_minutes}}
    (lines.rechecked()); a pick without one uses the chance and projection saved with the entry.
    {"picks": {pick_id: {...}}, "entries": {entry_id: {...}},
     "live": a pick is still being played, "pending": a pick's game hasn't started,
     "feed_down": NBA.com's feed didn't answer for a pick's game, so it shows the last numbers it sent}"""
    latest = latest or {}
    open_entries = [e for e in entries if e["status"] == "open"]
    # the live chance starts from the latest pre-game projection, else the one saved with the pick
    picks = [dict(p, **{k: v for k, v in latest.get(p["id"], {}).items() if k in _START_FROM and v is not None})
             for e in open_entries for p in e["picks"]]
    out_picks = picks_now(picks)
    if not out_picks:
        return dict(picks={}, entries={}, live=False, pending=False, feed_down=False)
    out_entries = {}
    decided = {"hit", "miss", "push", "void"}
    for e in open_entries:
        states = [out_picks.get(p["id"], {}).get("state", "pending") for p in e["picks"]]
        best = [s if s in decided else "hit" for s in states]     # everything left hits
        worst = [s if s in decided else "miss" for s in states]   # everything left misses
        chances, pushes = zip(*[_chance_now(p, out_picks.get(p["id"], {}), latest.get(p["id"])) for p in e["picks"]])
        out_entries[e["id"]] = dict(
            hit=states.count("hit"), lost=states.count("miss"), live=states.count("live"),
            pending=states.count("pending"), other=states.count("push") + states.count("void"),
            best=settle(best, e["kind"], e["stake"], e["payouts"])[1],
            locked=settle(worst, e["kind"], e["stake"], e["payouts"])[1],
            done=all(s in decided for s in states),
            odds=outcome_chances([s if s in decided else None for s in states], list(chances),
                                 e["kind"], e["stake"], e["payouts"], list(pushes)))
    states = [v["state"] for v in out_picks.values()]
    return dict(picks=out_picks, entries=out_entries, live="live" in states, pending="pending" in states,
                feed_down=any(v.get("feed_down") for v in out_picks.values()))


def _chance_now(pick: dict, now: dict, latest: dict | None) -> tuple[float | None, float]:
    """A pick's chance right now, as (hits if it doesn't push, pushes: lands exactly on the line and
    reverts): during its game the live chances (ingame.py), before it the latest re-check, else the
    chances saved with the entry. No push chance known: 0."""
    if now.get("live_more") is not None:
        hit = now["live_more"] if pick["side"] == "more" else 1 - now["live_more"]
        return hit, now.get("live_push") or 0.0
    if latest and latest.get("chance") is not None:
        return latest["chance"], latest.get("push") or 0.0
    return pick.get("model_p"), pick.get("p_push") or 0.0
