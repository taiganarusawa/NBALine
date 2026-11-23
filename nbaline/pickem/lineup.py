"""The lineups to play from a ranked board: picks that go well together in one entry, ready to copy into
PrizePicks. Three options, from the same rules for who can be in one:
  * a line from a well-tested stat, for a player who isn't inactive or questionable tonight (if he
    sits, the pick reverts and the entry pays less),
  * and one pick per player, since all of one player's lines rise and fall with his minutes: of the
    picks the page showed (Nov 10-22, 2026), when one of a player's picks hit, his other one hit 75%
    of the time, and when it missed, 34%.
Players in the same game barely moved together (55-57% either way, as for different games), so the
standard lineup takes picks from one game as they rank. It used to allow at most 2 per game: replaying
every graded night with and without that limit paid about the same ($30.20 and $29.80 on $13 of
6-pick Flexes, Nov 23, 2026).

Standard: a 6-pick Flex of standard lines, best chance first, each clearing the Flex break-even (54.2%
per pick for 6 picks at the standard payouts, 54.3% for 5) by the chance Best lines shows (adjusted to
the model's record against PrizePicks once that adjustment is on), and from a stat whose lines like
these haven't clearly lost against PrizePicks (its record on lines
shown at the break-even or more, calibration.stat_records: even the high end of its likely range under
the break-even). With only 5 such lines it's a 5-pick Flex, which has about the same break-even; with
fewer there's no lineup, since a weaker pick would pull the whole entry below break-even. It also comes
as a 5-pick Flex by choice: a smaller average return than the 6, but steadier (it profits more often,
and its losing stretches are shallower).

Safer (Goblins) and high risk (Demons): a 3-pick Power of the best Goblins or Demons the model gives at
least GOBLIN_AT_LEAST / DEMON_AT_LEAST, one per game, so the picks are close to independent and the
chance shown for all of them hitting is honest (More-only picks from one game haven't been tested apart
from standard ones, so this stays). With only 2 such lines it's a 2-pick Power. Goblins hit
often but pay less; Demons the model likes have hit more often than it said, and pay more. PrizePicks
publishes no formula for what they pay, so instead of a return these show the least PrizePicks must pay
for the entry to be worth playing at the model's chances (min_payout), to compare with what its app
shows. Their picks' chances are the model's own: the adjustment is for standard lines only, and the
model's Goblin and Demon chances have held up (calibration.line_type_record, shown with the lineup).
"""
from collections import Counter
from math import prod

from . import calibration, payouts

SIZES = (6, 5)          # a 6-pick Flex, or a 5-pick Flex when only 5 lines qualify
RECORD_ENTRY = ("flex", 6)   # stats' records are on lines shown at this entry's break-even or more
UNSURE = ("Questionable",)   # Out and Doubtful never reach the ranked list

POWER_SIZES = (3, 2)    # the Goblin and Demon lineups: a 3-pick Power, or 2-pick when only 2 qualify
# The least chance of More a pick needs, chosen from graded lines (by November 20, 2026): Goblins the
# model gave 75% or more hit 82% of 222, and Demons it gave 55% or more hit 72% of 67.
GOBLIN_AT_LEAST = 0.75
DEMON_AT_LEAST = 0.55


def expected_to_play(row: dict) -> bool:
    """A line from a well-tested stat with a chance from the model, for a player expected to play tonight."""
    status = (row.get("self_status") or "").split(":")[0]
    return (not row.get("yes_no") and bool(row.get("reliable")) and not (row.get("lineup") or {}).get("inactive")
            and status not in UNSURE and row.get("p_best") is not None)


def playable(row: dict) -> bool:
    """A standard line (More or Less) a lineup can use."""
    return row.get("sides", "both") == "both" and expected_to_play(row)


def pick_lineup(rows: list[dict], size: int, max_per_game: int | None = None) -> list[dict]:
    """Up to `size` rows, best chance first: one per player, and at most max_per_game per game (None: any)."""
    picks, players, games = [], set(), Counter()
    for r in sorted(rows, key=lambda r: -r["p_best"]):
        if r["player_id"] in players or (max_per_game is not None and games[r["game_id"]] >= max_per_game):
            continue
        picks.append(r)
        players.add(r["player_id"])
        games[r["game_id"]] += 1
        if len(picks) == size:
            break
    return picks


def fill(pool: list[dict], size: int, per_game: int) -> list[dict]:
    """pick_lineup with at most per_game picks from a game, loosened one game-pick at a time while that
    leaves it short (a small slate: one more pick from a game rather than one pick fewer)."""
    picks = pick_lineup(pool, size, per_game)
    while len(picks) < size:
        per_game += 1
        more = pick_lineup(pool, size, per_game)
        if len(more) == len(picks):
            break
        picks = more
    return picks


def _summary(key: str, option: str, kind: str, size: int | None, picks: list[dict], pool: list[dict],
             at_least: float) -> dict:
    """What every lineup reports: the entry, its picks, how many lines qualified, and their average chance.
    option: which of the page's choices it is ("standard", "goblin" or "demon"); key: this lineup."""
    return dict(key=key, option=option, kind=kind, size=size, picks=picks, at_least=at_least,
                candidates=len(pool), players=len({r["player_id"] for r in pool}),
                avg_chance=sum(r["p_best"] for r in picks) / len(picks) if picks else None)


def standard_lineup(ranked: list[dict], records: dict[str, dict], sizes: tuple[int, ...] = SIZES) -> dict:
    """The standard lineup for a board's ranked standard lines (ranking.rank_board's "ranked"), with
    each stat's record on lines like these (calibration.stat_records): a Flex of the first of `sizes`
    there are enough lines for (key "flex6" for 6 or 5 picks, "flex5" for 5 only).
        size:       picks in the Flex, or None when too few lines qualify
        picks:      the lineup's lines, best first (when size is None: the few that clear the largest
                    size's break-even)
        candidates: how many lines clear that entry's break-even (at_least); players: how many players they cover
        losing:     stats left out for a losing record, with how many of tonight's lines that was
        avg_chance, and at the standard payouts: ev (return per $1), p_profit, p_all"""
    losing = {stat for stat, r in records.items() if r["verdict"] == "losing"}
    usable = [r for r in ranked if playable(r)]
    left_out = Counter(r["stat"] for r in usable
                       if r["stat"] in losing and r["p_best"] >= payouts.break_even("flex", sizes[0]))
    usable = [r for r in usable if r["stat"] not in losing]
    for size in sizes:
        break_even = payouts.break_even("flex", size)
        pool = [r for r in usable if r["p_best"] >= break_even]
        picks = pick_lineup(pool, size)
        if len(picks) == size:
            break
    else:   # too few for any of them: show what clears the largest size's break-even
        size, break_even = None, payouts.break_even("flex", sizes[0])
        pool = [r for r in usable if r["p_best"] >= break_even]
        picks = pick_lineup(pool, sizes[0])
    out = _summary(f"flex{sizes[0]}", "standard", "flex", size, picks, pool, break_even)
    out.update(sizes=list(sizes), priced=True, losing=dict(left_out))
    if size:
        odds = payouts.entry_odds([r["p_best"] for r in picks], "flex")
        out.update(ev=odds["ev"], p_profit=odds["p_profit"], p_all=odds["p_all"])
    return out


def power_lineup(more_only: list[dict], line_type: str, at_least: float) -> dict:
    """A Power of one kind of More-only line (ranking.rank_board's "more_only"): "goblin" or "demon",
    as PrizePicks tags it (or as the player's standard line on the board shows), never a guess.
        size:       3 or 2 (picks in the Power), or None when fewer than 2 lines qualify
        picks:      the lineup's lines, best first (when size is None: the one that qualifies, if any)
        candidates: how many lines have at least `at_least`; players: how many players they cover
        p_all:      the model's chance every pick hits; min_payout: the least the Power must pay for
                    that to be worth it (1 / p_all)
        record:     how lines like these have done (calibration.line_type_record)"""
    pool = [r for r in more_only if r.get("line_type") == line_type and expected_to_play(r) and r["p_best"] >= at_least]
    for size in POWER_SIZES:
        picks = fill(pool, size, per_game=1)
        if len(picks) == size:
            break
    else:
        size, picks = None, fill(pool, POWER_SIZES[0], per_game=1)
    out = _summary(line_type, line_type, "power", size, picks, pool, at_least)
    out.update(sizes=list(POWER_SIZES), priced=False, record=calibration.line_type_record(line_type, at_least))
    if size:
        p_all = prod(r["p_best"] for r in picks)
        out.update(p_all=p_all, min_payout=1 / p_all)
    return out


def lineups(ranked: list[dict], more_only: list[dict], records: dict[str, dict]) -> list[dict]:
    """Every lineup the Best lines page offers for this board: standard (a 6- or 5-pick Flex), safer
    (Goblins) and high risk (Demons)."""
    return [standard_lineup(ranked, records), standard_lineup(ranked, records, SIZES[1:]),
            power_lineup(more_only, "goblin", GOBLIN_AT_LEAST), power_lineup(more_only, "demon", DEMON_AT_LEAST)]
