"""Scoring: how well do predictions line up with what actually happened?

Every model outputs a full *distribution* of points (as 39 quantiles: 2.5%, 5%, ... 97.5%),
not just one number. That lets us score it four ways:

  MAE / RMSE  - how far the single projection was from the real score (points)
  CRPS        - main score. Grades the whole distribution: it rewards being close AND being
                appropriately confident. Measured in points; lower is better. Works for every
                possible line at once, so it doesn't depend on which line a book posts.
  COV80       - should be 80%: how often the real score landed inside the 10th-90th percentile range
  Brier / LogLoss / ECE / ACC
              - grade the over/under probability on a specific line (lower is better, except ACC).
                ECE = average gap between "said 60%" and "happened X%" (calibration).
"""
import numpy as np
import pandas as pd

TAUS = np.round(np.linspace(0.025, 0.975, 39), 3)
BREAKEVEN = 110 / 210  # 52.4% at -110


def crps(Q: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Approximate CRPS from quantiles (2 x average pinball loss). Per row."""
    diff = y[:, None] - Q
    return 2 * np.maximum(TAUS * diff, (TAUS - 1) * diff).mean(axis=1)


def cdf_at(Q: np.ndarray, x: np.ndarray) -> np.ndarray:
    """P(points <= x) for each row, interpolating between the quantiles."""
    n, K = Q.shape
    idx = (Q < x[:, None]).sum(1)
    lo, hi = np.clip(idx - 1, 0, K - 1), np.clip(idx, 0, K - 1)
    r = np.arange(n)
    qlo, qhi = Q[r, lo], Q[r, hi]
    w = np.where(qhi > qlo, (x - qlo) / np.where(qhi > qlo, qhi - qlo, 1), 0.5)
    F = TAUS[lo] + np.clip(w, 0, 1) * (TAUS[hi] - TAUS[lo])
    F = np.where(idx == 0, TAUS[0] / 2, F)
    return np.where(idx == K, 1 - (1 - TAUS[-1]) / 2, F)


def p_over(Q: np.ndarray, line: np.ndarray) -> np.ndarray:
    return 1 - cdf_at(Q, line)


def line_scores(p: np.ndarray, over: np.ndarray, prefix: str) -> dict:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    bins = np.clip((p * 10).astype(int), 0, 9)
    ece = sum(abs(p[bins == b].mean() - over[bins == b].mean()) * (bins == b).mean()
              for b in range(10) if (bins == b).any())
    pick = p > 0.5
    conf = np.abs(p - 0.5) >= 0.08  # model at least 58% sure
    correct = np.where(pick, over == 1, over == 0)
    return {
        f"{prefix}_BRIER": np.mean((p - over) ** 2),
        f"{prefix}_LOGLOSS": -np.mean(over * np.log(p) + (1 - over) * np.log(1 - p)),
        f"{prefix}_ECE": ece,
        f"{prefix}_ACC": correct.mean(),
        f"{prefix}_ACC58": correct[conf].mean() if conf.any() else np.nan,
        f"{prefix}_N58": int(conf.sum()),
    }


def score(df: pd.DataFrame, mu: np.ndarray, Q: np.ndarray) -> dict:
    """All metrics for one test set. df needs PTS, PTS_L10, PTS_EWM."""
    y = df["PTS"].to_numpy(float)
    out = {
        "N": len(y),
        "MAE": np.mean(np.abs(y - mu)),
        "RMSE": np.sqrt(np.mean((y - mu) ** 2)),
        "BIAS": np.mean(mu - y),
        "CRPS": crps(Q, y).mean(),
        "COV80": np.mean((y >= Q[:, 3]) & (y <= Q[:, 35])),   # 10th..90th pct
        "COV50": np.mean((y >= Q[:, 9]) & (y <= Q[:, 29])),   # 25th..75th pct
    }
    # Synthetic lines (we have no real sportsbook history yet):
    #   L10 line : last-10 average rounded to .5 (easy, naive line)
    #   EWM line : recent-weighted average (the single strongest predictor, so a much tougher line)
    for name, col in (("L10", "PTS_L10"), ("EWM", "PTS_EWM")):
        line = np.floor(df[col].to_numpy(float)) + 0.5
        out.update(line_scores(p_over(Q, line), (y > line).astype(float), name))
    return out


def calibration_table(p: np.ndarray, over: np.ndarray) -> pd.DataFrame:
    cuts = [0, .3, .4, .45, .5, .55, .6, .7, 1]
    b = pd.cut(p, cuts)
    return pd.DataFrame({"predicted": p, "actual": over, "b": b}).groupby("b", observed=True).agg(
        predicted=("predicted", "mean"), actual=("actual", "mean"), n=("actual", "size"))
