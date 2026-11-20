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

The same honest chances give each stat's record on the lines Best lines would put in a lineup
(stat_records): how often lines it showed at the break-even or more were right, and whether that's
clearly winning, clearly losing, or too close or too few to tell.
"""
import numpy as np
import pandas as pd

from . import store
from .ingame import YES_NO

MIN_NIGHTS = 10      # graded nights before it can switch on
MIN_FIT_NIGHTS = 3   # earlier nights needed before a night is used in the test
ENOUGH_LINES = 20    # a stat with fewer graded lines than this is too new to tell anything (as on Results)

_cache: dict = {}    # the last results, with the graded lines they were worked out from


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


def honest_chances(lines: pd.DataFrame) -> pd.Series:
    """Each graded line's adjusted chance of More as it would have been that night: with the `keep`
    learned from the nights before it only. NaN on the first MIN_FIT_NIGHTS nights (nothing before them
    to learn from)."""
    p, y = lines["p_over"].to_numpy(), (lines["result"] == "over").to_numpy(float)
    when = lines["game_date"].to_numpy()
    out = np.full(len(lines), np.nan)
    for night in sorted(lines["game_date"].unique())[MIN_FIT_NIGHTS:]:
        before, today = when < night, when == night
        out[today] = adjust(p[today], fit_keep(p[before], y[before]))
    return pd.Series(out, index=lines.index)


def night_by_night_test(lines: pd.DataFrame, adjusted: pd.Series) -> dict | None:
    """Score `keep` the honest way: the honest_chances against the model's own, night by night (Brier
    score). None if no night can be tested yet."""
    y = (lines["result"] == "over").astype(float)
    t = pd.DataFrame({"night": lines["game_date"], "model": (lines["p_over"] - y) ** 2,
                      "adjusted": (adjusted - y) ** 2})[adjusted.notna()]
    if t.empty:
        return None
    nights = t.groupby("night")[["model", "adjusted"]].sum()
    return dict(nights=len(nights), lines=len(t), nights_better=int((nights["adjusted"] < nights["model"]).sum()),
                brier_model=float(t["model"].mean()), brier_adjusted=float(t["adjusted"].mean()))


def _graded() -> dict:
    """The graded lines, their honest chances and the adjustment's status, worked out again only when
    lines have been graded since the last time. Results worked out from them are kept here too."""
    with store.db() as con:
        key = tuple(con.execute("SELECT COUNT(*), MAX(id) FROM checks WHERE result IS NOT NULL").fetchone())
    if _cache.get("key") != key:
        lines = graded_lines()
        adjusted = honest_chances(lines)
        nights = int(lines["game_date"].nunique())
        test = night_by_night_test(lines, adjusted)
        keep = fit_keep(lines["p_over"].to_numpy(), (lines["result"] == "over").to_numpy(float)) if len(lines) else None
        on = nights >= MIN_NIGHTS and test is not None and test["brier_adjusted"] < test["brier_model"]
        _cache.clear()
        _cache.update(key=key, lines=lines, adjusted=adjusted, status=dict(
            on=on, keep=keep, nights=nights, lines=len(lines), min_nights=MIN_NIGHTS, test=test))
    return _cache


def status() -> dict:
    """Whether the adjustment is on, its `keep` (learned from every graded night), and its test."""
    return _graded()["status"]


def likely_range(rate: float, n: int) -> tuple[float, float]:
    """Where a hit rate over n lines probably really is (95%), as the Results page shows it."""
    margin = 1.96 * np.sqrt(max(rate * (1 - rate), 0.0025) / n)
    return max(rate - margin, 0.0), min(rate + margin, 1.0)


def stat_records(at_least: float) -> dict[str, dict]:
    """Each stat's record on lines like the ones in a Best lines lineup: graded standard lines the page
    showed at `at_least` or more for one side, at the chance it would have shown that night (honest and
    adjusted once the adjustment is on, the model's own before that). stat -> {lines, right, rate, low,
    high, verdict}, where verdict is "few" (under ENOUGH_LINES lines), "losing" (even the high end of
    its likely range is under at_least), "winning" (even the low end is at or above it) or "unclear"."""
    graded = _graded()
    key = ("records", at_least)
    if key not in graded:
        lines = graded["lines"]
        p = graded["adjusted"] if graded["status"]["on"] else lines["p_over"]
        right = np.where(p >= 0.5, lines["result"] == "over", lines["result"] == "under")
        shown = pd.DataFrame({"stat": lines["stat"], "right": right})[np.maximum(p, 1 - p) >= at_least]
        graded[key] = {stat: _record(int(d["right"].sum()), len(d), at_least) for stat, d in shown.groupby("stat")}
    return graded[key]


def _record(hits: int, n: int, at_least: float) -> dict:
    rate = hits / n
    low, high = likely_range(rate, n)
    verdict = ("few" if n < ENOUGH_LINES else "losing" if high < at_least
               else "winning" if low >= at_least else "unclear")
    return dict(lines=n, right=hits, rate=rate, low=low, high=high, verdict=verdict)


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
