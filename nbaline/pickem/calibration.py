"""Adjusting the model's chances to how they've done against real PrizePicks lines.

Graded lines show the model is too sure of itself against PrizePicks: its 60-70% leans have hit well
under 60%. PrizePicks lines already price in injuries, minutes news and matchups, so much of the edge
the model sees is already in the line. The fix is one number, learned from every graded standard line:
how much of the model's lean to keep,

    adjusted chance of More = 50% + keep x (model's chance - 50%)

so with keep = 0.4, a 70% lean becomes 58%. It only ever makes the model less sure (keep is at most 1),
it's the same for More and Less (a More/Less shift mostly learns whether the last few nights ran hot
or cold), and Goblins, Demons and yes/no props are left alone, since they aren't meant to be 50/50.

It switches itself on only when it has earned it:
  * at least MIN_NIGHTS nights of graded lines (lines on the same night move together, so a night is
    closer to one data point than to hundreds), and
  * an honest test: for each night, `keep` is learned from the nights before it only, then scored on
    that night. Over all the tested nights, the adjusted chances must beat the model's own (Brier score).
Until then the page shows the model's chances unchanged. The saved checks always keep the model's own
chance, so the adjustment is learned from the model and never from itself.
"""
import numpy as np
import pandas as pd

from . import store
from .ingame import YES_NO

MIN_NIGHTS = 10      # graded nights before it can switch on
MIN_FIT_NIGHTS = 3   # earlier nights needed before a night is used in the test

_cache: dict = {}    # the last status, with the graded lines it was worked out from


def fit_keep(p_over: np.ndarray, went_over: np.ndarray) -> float:
    """The `keep` with the lowest Brier score on these lines, between 0 and 1. Brier is a squared error,
    so it has an exact answer: keep = sum(lean x (outcome - 50%)) / sum(lean^2), lean = chance - 50%."""
    lean = p_over - 0.5
    spread = float((lean ** 2).sum())
    return float(np.clip((lean * (went_over - 0.5)).sum() / spread, 0, 1)) if spread else 1.0


def adjust(p_over: float, keep: float) -> float:
    return 0.5 + keep * (p_over - 0.5)


def graded_lines() -> pd.DataFrame:
    """Every graded standard 50/50 line, as scored on Results: each player/stat once a night, at the
    last line seen before tip-off, with the model's own chance (and pushes left out)."""
    with store.db() as con:
        ck = pd.read_sql("SELECT * FROM checks WHERE result IN ('over', 'under') AND p_over IS NOT NULL", con)
    ck = ck[~ck["line_type"].isin(store.MORE_ONLY_TYPES) & ~ck["stat"].isin(YES_NO) & (ck["started"] == 0)]
    return store._last_seen(ck)


def night_by_night_test(lines: pd.DataFrame) -> dict | None:
    """Score `keep` the honest way: each night with MIN_FIT_NIGHTS earlier nights is scored with the
    `keep` learned from those earlier nights only. None if no night can be tested yet."""
    nights = sorted(lines["game_date"].unique())
    p, y = lines["p_over"].to_numpy(), (lines["result"] == "over").to_numpy(float)
    when = lines["game_date"].to_numpy()
    model_err = adjusted_err = 0.0
    tested = n = better = 0
    for night in nights[MIN_FIT_NIGHTS:]:
        before, today = when < night, when == night
        keep = fit_keep(p[before], y[before])
        model = float(((p[today] - y[today]) ** 2).sum())
        adjusted = float(((adjust(p[today], keep) - y[today]) ** 2).sum())
        model_err, adjusted_err = model_err + model, adjusted_err + adjusted
        tested, n, better = tested + 1, n + int(today.sum()), better + (adjusted < model)
    if not tested:
        return None
    return dict(nights=tested, lines=n, nights_better=better,
                brier_model=model_err / n, brier_adjusted=adjusted_err / n)


def status() -> dict:
    """Whether the adjustment is on, its `keep` (learned from every graded night), and its test.
    Worked out again only when lines have been graded since the last time."""
    with store.db() as con:
        key = tuple(con.execute("SELECT COUNT(*), MAX(id) FROM checks WHERE result IS NOT NULL").fetchone())
    if _cache.get("key") == key:
        return _cache["status"]
    lines = graded_lines()
    nights = int(lines["game_date"].nunique())
    test = night_by_night_test(lines) if nights > MIN_FIT_NIGHTS else None
    keep = fit_keep(lines["p_over"].to_numpy(), (lines["result"] == "over").to_numpy(float)) if len(lines) else None
    on = nights >= MIN_NIGHTS and test is not None and test["brier_adjusted"] < test["brier_model"]
    result = dict(on=on, keep=keep, nights=nights, lines=len(lines), min_nights=MIN_NIGHTS, test=test)
    _cache.update(key=key, status=result)
    return result


def adjust_lines(items: list[dict], line_types: list[str | None]) -> list[dict]:
    """Analyzed lines with the chance of More adjusted, when the adjustment is on. Only standard 50/50
    lines change; each changed one keeps the model's own chance as `p_over_model`."""
    s = status()
    if not s["on"]:
        return items
    out = []
    for item, line_type in zip(items, line_types):
        p = item.get("p_over")
        if p is None or line_type in store.MORE_ONLY_TYPES or item.get("yes_no"):
            out.append(item)
        else:
            out.append(dict(item, p_over=round(adjust(p, s["keep"]), 4), p_over_model=p))
    return out
