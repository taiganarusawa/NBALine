"""Ranking a pasted board: which side of each line to take, and how far it clears the break-even.

Lines are sorted into four groups:
  * ranked:     standard lines (More or Less), best model chance first;
  * more_only:  Goblin/Demon lines (More only). They pay differently, so they get their own list;
  * live:       lines whose game has started: the page follows them live, with the model's chance from here;
  * other:      lines that can't be ranked, each with the reason (player out, no model, ...).
"""
from datetime import date

import pandas as pd

from .board import WEEKDAYS, board_days


def board_date(text: str, chosen: pd.Timestamp, today: date | None = None) -> tuple[pd.Timestamp, str | None]:
    """A copied PrizePicks page shows each game's weekday ("Tue 7:00pm"). If the chosen date isn't one
    of them, switch to the next date (from today) that is. Returns (date, note for the user or None)."""
    days = board_days(text)
    if not days or WEEKDAYS[chosen.weekday()] in days:
        return chosen, None
    start = pd.Timestamp(today or date.today())
    for k in range(7):
        d = start + pd.Timedelta(days=k)
        if WEEKDAYS[d.weekday()] in days:
            return d, f"The board is for {WEEKDAYS[d.weekday()]} games, so the date was set to {d:%a %b %d}."
    return chosen, None


def label_line_types(found: list[dict]) -> list[dict]:
    """Mark each More-only card as a Goblin or a Demon: by PrizePicks' own tag on the copied card, or
    else by the same player's standard line (below it = Goblin, above = Demon). "more_only" when
    neither tells."""
    standard = {(f["player"], f["stat"]): f["line"] for f in found if f.get("sides", "both") == "both"}
    for f in found:
        if f.get("sides", "both") != "both":
            std = standard.get((f["player"], f["stat"]))
            f["line_type"] = f.get("kind") or ("more_only" if std is None or std == f["line"]
                                               else "goblin" if f["line"] < std else "demon")
    return found


def not_ranked_reason(card: dict, result: dict, known_teams: set) -> str | None:
    """Why a line can't be ranked (or followed live, once its game has started), or None if it can."""
    if result.get("error"):
        return result["error"]
    if (result.get("self_status") or "").startswith("Out"):
        return f"listed {result['self_status'].split(':')[0]} on the injury report"
    if not result.get("modeled"):
        return "no model for this stat yet"
    team, opp = card.get("team"), card.get("opp")
    if team and team != result["team"] and team in known_teams:
        return f"PrizePicks has him on {team}, but his last game was for {result['team']} (recent trade?)"
    if opp and opp != result["opp"] and opp in known_teams:
        return f"PrizePicks shows the game vs {opp}, but the schedule has {result['team']} vs {result['opp']}"
    return None


def rank_board(found: list[dict], results: list[dict], break_even: float, known_teams: set) -> dict:
    """Combine each pasted card with its model result and sort into ranked / more_only / live / other."""
    rows = []
    for card, result in zip(found, results):
        row, reason = dict(result), not_ranked_reason(card, result, known_teams)
        sides = card.get("sides", "both")
        if result.get("modeled") and not result.get("error"):
            p_over = result["p_over"]
            side = sides if sides in ("more", "less") else ("more" if p_over >= 0.5 else "less")
            p_best = p_over if side == "more" else 1 - p_over
            row.update(side=side, p_best=round(p_best, 4), edge=round(p_best - break_even, 4))
        if sides != "both":  # Goblin/Demon: when the board doesn't say which, guess from his recent average
            avg = (result.get("history") or {}).get("avg10")
            row.update(line_type=card["line_type"],
                       line_hint=None if avg is None else "goblin" if card["line"] < avg else "demon")
        live = reason is None and bool(result.get("started"))
        row.update(rankable=reason is None and not live, live=live, reason=reason, sides=sides)
        rows.append(row)
    best_first = lambda rs: sorted(rs, key=lambda r: -r["p_best"])
    return dict(ranked=best_first([r for r in rows if r["rankable"] and r["sides"] == "both"]),
                more_only=best_first([r for r in rows if r["rankable"] and r["sides"] != "both"]),
                live=[r for r in rows if r["live"]],
                other=[r for r in rows if r["reason"]])
