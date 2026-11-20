"""PrizePicks payouts and entry math: what an entry pays, its odds of cashing, and its break-even.

How PrizePicks pays (from its help center, November 2026):
  * Power Play: every pick must hit. Flex Play: you can miss one (or two in 5-6 pick entries) for a
    smaller payout. DEFAULT_PAYOUTS are the standard multipliers; they change now and then and by state.
  * Goblins and Demons "carry altered payout rates": a Goblin (an easier line) lowers the lineup's
    multipliers and a Demon (a harder line) raises them, by an amount that depends on the projection.
    PrizePicks publishes no formula, and two lineups with one Goblin each can pay quite differently
    (19.2x and 16.6x for 6 of 6 on two of your entries), so the only exact numbers are the ones the
    app shows for your lineup.
  * A player who doesn't play, or a stat exactly on the line, "reverts" the pick: it's removed and the
    lineup drops a size (a 6-pick Flex becomes a 5-pick Flex), priced on the picks left, so a Goblin
    still in it still lowers the payout. That's the reverted table, by how many picks are left
    (PrizePicks shows it with the lineup: "What is a reverted payout?"). REVERTED_PAYOUTS is the
    standard one.
  * A Profit Boost (a promo) adds a percentage to the winnings above your entry fee. With 30%, 7x pays
    7 + 0.3 x 6 = 8.8x and 1.25x pays 1.325x. A tier paying 1x or less is boosted too, on the whole
    amount: 0.4x pays 0.52x (seen on PrizePicks: 7x / 1.25x / 0.4x showed as 8.8x / 1.325x / 0.52x),
    and 1x pays 1.3x. It boosts the reverted payouts too.

Each entry saves its own payouts, edited to match the PrizePicks app: the tables as PrizePicks shows
them before any boost, plus the boost on top:
    {"power": {...}, "flex": {...}, "reverted": {"flex": {...}, ...}, "boost": 0.3}
"""
from itertools import combinations

import numpy as np

DEFAULT_PAYOUTS = {
    "power": {"2": {"2": 3}, "3": {"3": 5}, "4": {"4": 10}, "5": {"5": 20}, "6": {"6": 37.5}},
    "flex": {"3": {"3": 2.25, "2": 1.25}, "4": {"4": 5, "3": 1.5},
             "5": {"5": 10, "4": 2, "3": 0.4}, "6": {"6": 25, "5": 2, "4": 0.4}},
}

# What a lineup pays when players revert: picks left -> picks that hit -> multiplier.
# Flex: from PrizePicks' reverted-payout table for a 6-pick Flex (November 2026). Power: the smaller
# Power payout. Either way a single pick left still pays 1.5x if it hits (a 2-pick Power with one
# pick reverted pays 1.5x, as PrizePicks shows it). All reverted: refunded.
REVERTED_PAYOUTS = {
    "flex": {"5": {"5": 10, "4": 2, "3": 0.4}, "4": {"4": 6, "3": 1.5}, "3": {"3": 3, "2": 1},
             "2": {"2": 3}, "1": {"1": 1.5}},
    "power": {"5": {"5": 20}, "4": {"4": 10}, "3": {"3": 5}, "2": {"2": 3}, "1": {"1": 1.5}},
}

# The entry you plan to play -> (label, kind, picks). Best lines ranks a board against its break-even.
ENTRY_TYPES = {
    "flex6": ("6-pick Flex", "flex", 6), "flex5": ("5-pick Flex", "flex", 5),
    "power6": ("6-pick Power", "power", 6), "power5": ("5-pick Power", "power", 5),
    "power4": ("4-pick Power", "power", 4), "power3": ("3-pick Power", "power", 3),
    "power2": ("2-pick Power", "power", 2),
}

# PrizePicks stat name -> how to compute it from a box score
STATS = {
    "Points": {"PTS": 1},
    "Rebounds": {"REB": 1},
    "Assists": {"AST": 1},
    "3-PT Made": {"FG3M": 1},
    "Pts+Rebs+Asts": {"PTS": 1, "REB": 1, "AST": 1},
    "Pts+Rebs": {"PTS": 1, "REB": 1},
    "Pts+Asts": {"PTS": 1, "AST": 1},
    "Rebs+Asts": {"REB": 1, "AST": 1},
    "Steals": {"STL": 1},
    "Blocked Shots": {"BLK": 1},
    "Blks+Stls": {"BLK": 1, "STL": 1},
    "Turnovers": {"TOV": 1},
    "Fantasy Score": {"PTS": 1, "REB": 1.2, "AST": 1.5, "BLK": 3, "STL": 3, "TOV": -1},
    "FG Attempted": {"FGA": 1},
    "FG Made": {"FGM": 1},
    "3-PT Attempted": {"FG3A": 1},
    "Free Throws Made": {"FTM": 1},
    "Free Throws Attempted": {"FTA": 1},
    "Offensive Rebounds": {"OREB": 1},
    "Defensive Rebounds": {"DREB": 1},
    "Two Pointers Made": {"FGM": 1, "FG3M": -1},
    "Two Pointers Attempted": {"FGA": 1, "FG3A": -1},
    "Personal Fouls": {"PF": 1},
    # columns added by features.add_prizepicks_columns (not in the box score itself)
    "Double Doubles": {"DD": 1},   # 1 if 10+ in two of points, rebounds, assists, steals, blocks
    "Triple Doubles": {"TD": 1},   # ... in three of them
    "Dunks": {"DUNKS": 1},         # made dunks, from the shot chart
}


def stat_value(row, stat: str) -> float:
    """A box score row's value for a PrizePicks stat, e.g. Pts+Rebs+Asts = PTS + REB + AST."""
    return float(sum(w * float(row[c]) for c, w in STATS[stat].items()))


# ---------------------------------------------------------------- entry math
MAX_BOOST = 5.0           # a 500% boost: anything bigger is a typo
MAX_MULTIPLIER = 10_000   # Demons can reach a few thousand x


def boosted(m: float, boost: float | None) -> float:
    """A multiplier with a Profit Boost (0.3 = 30%). Above 1x it's on the part above the entry fee
    (7x -> 8.8x); at 1x or less, with no winnings above the fee, it's on the whole amount (0.4x -> 0.52x)."""
    if not boost:
        return m
    return round(m + boost * (m - 1), 6) if m > 1 else round(m * (1 + boost), 6)


def multiplier(payouts: dict, kind: str, n: int, hits: int) -> float:
    """What `hits` of `n` picks pays, with the entry's boost."""
    return boosted(float(payouts.get(kind, {}).get(str(n), {}).get(str(hits), 0)), payouts.get("boost"))


def checked(payouts) -> dict:
    """An entry's payouts as the page sent them, checked: tables of multipliers (0 to MAX_MULTIPLIER)
    and a boost from 0 to MAX_BOOST (0: no boost). Without reverted tables, the standard ones.
    Raises ValueError saying what's wrong."""
    def number(x, high: float, wrong: str) -> float:
        try:
            x = float(x)
        except (TypeError, ValueError):
            raise ValueError(wrong) from None
        if not 0 <= x <= high:   # also catches NaN
            raise ValueError(wrong)
        return x

    garbled = "The payouts didn't come through right. Reload the page and try again."
    each = f"Each payout is a multiplier from 0 to {MAX_MULTIPLIER:,}x: copy the ones PrizePicks shows."

    def tables(t) -> dict:   # picks -> hits -> multiplier
        if not isinstance(t, dict) or not all(isinstance(row, dict) for row in t.values()):
            raise ValueError(garbled)
        return {str(n): {str(hits): number(m, MAX_MULTIPLIER, each) for hits, m in row.items()} for n, row in t.items()}

    if not isinstance(payouts, dict):
        raise ValueError("No payouts were sent.")
    reverted = payouts.get("reverted") or REVERTED_PAYOUTS
    if not isinstance(reverted, dict):
        raise ValueError(garbled)
    out = {kind: tables(payouts.get(kind, {})) for kind in ("power", "flex")}
    out["reverted"] = {kind: tables(reverted.get(kind, {})) for kind in ("power", "flex")}
    boost = number(payouts.get("boost") or 0, MAX_BOOST, f"A profit boost is a percentage from 0 to {MAX_BOOST:.0%}.")
    if boost:
        out["boost"] = boost
    return out


def hit_distribution(ps: list[float]) -> np.ndarray:
    """P(exactly k picks hit), k = 0..n, assuming picks are independent."""
    dist = np.array([1.0])
    for p in ps:
        dist = np.convolve(dist, [1 - p, p])
    return dist


def entry_odds(ps: list[float], kind: str, payouts: dict | None = None) -> dict:
    """Expected return per $1, chance of any payout, chance of profit."""
    payouts = payouts or DEFAULT_PAYOUTS
    n, dist = len(ps), hit_distribution(ps)
    mults = np.array([multiplier(payouts, kind, n, k) for k in range(n + 1)])
    return dict(ev=float((dist * mults).sum()), p_cash=float(dist[mults > 0].sum()),
                p_profit=float(dist[mults > 1].sum()), p_all=float(dist[-1]))


REVERTED = ("push", "void")
SHOW_PUSH_TIER = 0.001    # an amount only a push can lead to is listed from this chance (0.1%) up


def ending_chances(chances: list[float], pushes: list[float]) -> np.ndarray:
    """P(k picks hit and j push), as an array [k, j], for picks that each hit with chance c if they don't
    push, and push (land exactly on the line, so they revert) with chance q, independently."""
    dist = np.ones((1, 1))
    for c, q in zip(chances, pushes):
        nxt = np.zeros((dist.shape[0] + 1, dist.shape[1] + 1))
        nxt[:-1, :-1] += dist * (1 - q) * (1 - c)   # misses
        nxt[1:, :-1] += dist * (1 - q) * c          # hits
        nxt[:-1, 1:] += dist * q                    # pushes
        dist = nxt
    return dist


def outcome_chances(results: list[str | None], chances: list[float | None], kind: str, stake: float,
                    payouts: dict, pushes: list[float] | None = None) -> dict | None:
    """What an entry can still pay and how likely each amount is, part-way through: picks already
    decided count as they ended ('hit', 'miss', or reverted: 'push' / 'void'), and each pick still to
    be decided (result None) pushes with its push chance (0 when not given: a .5 line can't push) and
    otherwise hits with its chance, independently. A push reverts the pick, so the lineup is paid on
    fewer picks. Picks still to come are assumed to play.
        tiers: what it can pay, best first: {"hits", "of", "pays", "chance", "pushes": how many more
               picks push to get there}. With no more pushes, every number of hits that pays is listed,
               a tier a miss has already ruled out with chance 0; an amount only more pushes lead to
               ("4 of 4" after one more push) from SHOW_PUSH_TIER up. Then a refund, if the picks left
               can be too few to pay on ({"refund": True}), and last "nothing" (hits None).
        expected (the average payout), p_profit (pays more than the stake), p_cash (pays anything)
    None if a pick still to be decided has no chance (no model for its stat)."""
    pushes = pushes or [0.0] * len(results)
    todo = [(c, q or 0.0) for r, c, q in zip(results, chances, pushes) if r is None]
    if any(c is None for c, _ in todo):
        return None
    n, hits, reverted = len(results), results.count("hit"), sum(r in REVERTED for r in results)
    dist = ending_chances([c for c, _ in todo], [q for _, q in todo])   # [k more hits, j more pushes]
    tiers, nothing, refunded = [], 0.0, 0.0
    expected = p_profit = p_cash = 0.0
    for j in range(dist.shape[1]):                    # j more of the picks to come push
        left = n - reverted - j                       # picks the lineup is paid on
        for h in range(left, -1, -1):                 # h of them hit, from all of them down
            k = h - hits
            chance = float(dist[k, j]) if 0 <= k < dist.shape[0] else 0.0
            status, pay = settle(["hit"] * h + ["miss"] * (left - h) + ["push"] * (reverted + j), kind, stake, payouts)
            expected += chance * pay
            p_profit += chance * (pay > stake)
            p_cash += chance * (pay > 0)
            if status == "refund":
                refunded += chance
            elif pay <= 0:
                nothing += chance
            elif j == 0 or chance >= SHOW_PUSH_TIER:
                tiers.append(dict(hits=h, of=left, pays=pay, chance=chance, pushes=j))
    tiers.sort(key=lambda t: (-t["pays"], t["pushes"]))
    if refunded >= SHOW_PUSH_TIER:
        tiers.append(dict(hits=None, of=0, pays=stake, chance=refunded, pushes=None, refund=True))
    tiers.append(dict(hits=None, of=n - reverted, pays=0.0, chance=nothing, pushes=0))
    return dict(tiers=tiers, expected=round(expected, 2), p_profit=p_profit, p_cash=p_cash)


def break_even(kind: str, n: int, payouts: dict | None = None) -> float | None:
    """Per-pick win rate needed to break even (if every pick had the same chance)."""
    payouts = payouts or DEFAULT_PAYOUTS
    if str(n) not in payouts.get(kind, {}):
        return None
    lo, hi = 0.0, 1.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if entry_odds([mid] * n, kind, payouts)["ev"] < 1 else (lo, mid)
    return round(hi, 4)


def settle(results: list[str], kind: str, stake: float, payouts: dict) -> tuple[str, float]:
    """results: 'hit' / 'miss' / 'push' / 'void' for every pick. Returns (status, payout).
    With every pick decided, the entry's own table pays. With some reverted (push or void), its
    reverted payouts for the picks left do (the entry's own, saved with it, or REVERTED_PAYOUTS).
    Either way with the entry's profit boost. All reverted, or no reverted payout for that many
    picks: refunded."""
    live = [r for r in results if r in ("hit", "miss")]
    left, hits = len(live), live.count("hit")
    if left == len(results):
        table = payouts.get(kind, {}).get(str(left))
    else:
        table = (payouts.get("reverted") or REVERTED_PAYOUTS).get(kind, {}).get(str(left))
    if not left or table is None:
        return "refund", stake
    m = boosted(float(table.get(str(hits), 0)), payouts.get("boost"))
    pay = round(stake * m + 1e-9, 2)   # to the cent, half a cent up ($1.325 -> $1.33, not float's $1.32)
    return paid_status(pay, stake), pay


def paid_status(pay: float, stake: float) -> str:
    """An entry's result from what it paid: won (more than you played), partial (some of it back) or lost."""
    return "won" if pay > stake else "partial" if pay > 0 else "lost"
