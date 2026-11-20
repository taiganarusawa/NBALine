"""The lineup to play from a ranked board: picks that go well together in one entry, ready to copy into
PrizePicks.

The standard lineup is a 6-pick Flex of standard lines, best chance first, where each pick
  * clears the Flex break-even (54.2% per pick for 6 picks at the standard payouts, 54.3% for 5), by
    the chance Best lines shows (adjusted to the model's record against PrizePicks once that
    adjustment is on),
  * is from a well-tested stat, for a player who isn't inactive or questionable tonight (if he sits,
    the pick reverts and the entry pays less),
  * is from a stat whose lines like these haven't clearly lost against PrizePicks (its record on lines
    shown at the break-even or more, calibration.stat_records: even the high end of its likely range
    under the break-even),
  * is the only pick for that player, since all of one player's lines rise and fall with his minutes,
  * and is one of at most MAX_PER_GAME picks from the same game (players in one game move together a
    little: pace, blowouts). On a small slate that can leave the lineup short: then one more per game
    is allowed, as far as it takes to fill it.
With only 5 such lines it's a 5-pick Flex, which has about the same break-even. With fewer there's
no lineup: a weaker pick would pull the whole entry below break-even.

Other lineups (safer ones with Goblins, high-risk ones with Demons) can be added next to this one.
"""
from collections import Counter

from . import payouts

SIZES = (6, 5)          # a 6-pick Flex, or a 5-pick Flex when only 5 lines qualify
RECORD_ENTRY = ("flex", 6)   # stats' records are on lines shown at this entry's break-even or more
MAX_PER_GAME = 2
UNSURE = ("Questionable",)   # Out and Doubtful never reach the ranked list


def playable(row: dict) -> bool:
    """A standard line from a well-tested stat, for a player expected to play tonight."""
    status = (row.get("self_status") or "").split(":")[0]
    return (row.get("sides", "both") == "both" and not row.get("yes_no") and bool(row.get("reliable"))
            and not (row.get("lineup") or {}).get("inactive") and status not in UNSURE
            and row.get("p_best") is not None)


def pick_lineup(rows: list[dict], size: int, max_per_game: int) -> list[dict]:
    """Up to `size` rows, best chance first: one per player, at most max_per_game per game."""
    picks, players, games = [], set(), Counter()
    for r in sorted(rows, key=lambda r: -r["p_best"]):
        if r["player_id"] in players or games[r["game_id"]] >= max_per_game:
            continue
        picks.append(r)
        players.add(r["player_id"])
        games[r["game_id"]] += 1
        if len(picks) == size:
            break
    return picks


def fill(pool: list[dict], size: int) -> list[dict]:
    """pick_lineup with MAX_PER_GAME, loosened one game-pick at a time while that leaves it short
    (a small slate: one more pick from a game rather than one pick fewer)."""
    per_game = MAX_PER_GAME
    picks = pick_lineup(pool, size, per_game)
    while len(picks) < size:
        per_game += 1
        more = pick_lineup(pool, size, per_game)
        if len(more) == len(picks):
            break
        picks = more
    return picks


def standard_lineup(ranked: list[dict], records: dict[str, dict]) -> dict:
    """The standard lineup for a board's ranked standard lines (ranking.rank_board's "ranked"), with
    each stat's record on lines like these (calibration.stat_records).
        size:       6 or 5 (a 6- or 5-pick Flex), or None when too few lines qualify
        picks:      the lineup's lines, best first (when size is None: the few that clear 6 picks' break-even)
        candidates: how many lines clear that entry's break-even; players: how many players they cover
        losing:     stats left out for a losing record, with how many of tonight's lines that was
        break_even, avg_chance, and at the standard payouts: ev (return per $1), p_profit, p_all"""
    losing = {stat for stat, r in records.items() if r["verdict"] == "losing"}
    usable = [r for r in ranked if playable(r)]
    left_out = Counter(r["stat"] for r in usable
                       if r["stat"] in losing and r["p_best"] >= payouts.break_even("flex", SIZES[0]))
    usable = [r for r in usable if r["stat"] not in losing]
    for size in SIZES:
        break_even = payouts.break_even("flex", size)
        pool = [r for r in usable if r["p_best"] >= break_even]
        picks = fill(pool, size)
        if len(picks) == size:
            break
    else:   # too few for any of them: show what clears the 6-pick break-even
        size, break_even = None, payouts.break_even("flex", SIZES[0])
        pool = [r for r in usable if r["p_best"] >= break_even]
        picks = fill(pool, SIZES[0])
    out = dict(key="standard", title="Standard lines", kind="flex", size=size, picks=picks,
               candidates=len(pool), players=len({r["player_id"] for r in pool}), losing=dict(left_out),
               break_even=break_even, avg_chance=sum(r["p_best"] for r in picks) / len(picks) if picks else None)
    if size:
        odds = payouts.entry_odds([r["p_best"] for r in picks], "flex")
        out.update(ev=odds["ev"], p_profit=odds["p_profit"], p_all=odds["p_all"])
    return out


def lineups(ranked: list[dict], records: dict[str, dict]) -> list[dict]:
    """Every lineup the Best lines page offers for this board."""
    return [standard_lineup(ranked, records)]
