"""The model pipeline: a points model (mean) + an uncertainty model (distribution).

Training a pipeline on seasons [..., S-1]:
  1. "Inner" fit: train on seasons < S-1, watch error on season S-1 every boosting round
     (each round adds one tree, the boosting version of an epoch). Early stopping picks
     the round count where season S-1 error stops improving.
  2. The inner model's misses on season S-1 are honest, out-of-sample errors. They
     calibrate the uncertainty (how wide the distribution should be).
  3. Final fit: retrain on all seasons with the chosen round count.

Steps 1-2 only use complete past seasons, so during a season they come out the same every time. A
retrain reuses them from the model it replaces when they'd learn from exactly the same rows and
settings (see fingerprint), and only step 3 runs again: the same model in about half the time.
And a model whose final fit would learn from exactly the same rows needn't be retrained at all
(is_up_to_date).
"""
import functools
import hashlib
import json
import os
import pickle
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from .evaluate import TAUS, p_over

BASE_PARAMS = dict(learning_rate=0.03, max_depth=5, subsample=0.8, colsample_bytree=0.8,
                   min_child_weight=20, reg_lambda=1.0, tree_method="hist", nthread=-1, verbosity=0)


@functools.cache
def training_device() -> str:
    """Where XGBoost builds its trees: "cuda" (the NVIDIA GPU, about 3x faster per model on this
    laptop) when one is usable, otherwise "cpu". Set NBALINE_DEVICE=cpu to force the CPU.

    The GPU draws its random row and input samples differently, so its trees differ slightly from the
    CPU's (scored the same on unseen seasons: TRAINING.md section 7). Either way predictions run on the
    CPU (_on_cpu), so the web app never needs the GPU."""
    wanted = os.environ.get("NBALINE_DEVICE", "").lower()
    if wanted in ("cpu", "cuda"):
        return wanted
    # A one-tree test fit. Without a usable GPU (no NVIDIA card, or a driver too old for this XGBoost)
    # XGBoost quietly falls back to the CPU, so check where it actually ran.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            test = xgb.train(dict(device="cuda", tree_method="hist", verbosity=0),
                             xgb.DMatrix(np.zeros((4, 1)), label=np.arange(4.0)), num_boost_round=1)
        ran_on = json.loads(test.save_config())["learner"]["generic_param"]["device"]
        return "cuda" if ran_on.startswith("cuda") else "cpu"
    except xgb.core.XGBoostError:
        return "cpu"


def _on_cpu(booster: xgb.Booster) -> xgb.Booster:
    """Predict on the CPU, wherever the trees were built: the same trees give the same predictions,
    and the web app doesn't have to start the GPU (or have one) to use a model."""
    booster.set_param({"device": "cpu"})
    return booster


@dataclass
class Config:
    name: str
    features: list
    objective: str = "reg:squarederror"
    params: dict = field(default_factory=lambda: dict(BASE_PARAMS))
    rounds: int | None = 600          # fixed number of trees; None = early stopping decides
    max_rounds: int = 5000
    patience: int = 200               # early stopping: stop after this many rounds without improvement
    dist: str = "bins"                # bins | scaled | hetero | quantile | nbinom | both (hetero + nbinom)
                                      # | yes_no (a 1-or-0 stat: the mean IS the chance; binary:logistic)
    target: str = "PTS"               # column to predict (Y_REB, Y_PRA, ... for other stats)
    sig_floor: float = 1.0            # smallest spread the volatility model may predict
    min_season: int | None = None     # ignore seasons before this
    recency_halflife: float | None = None   # weight recent seasons more (in seasons)
    finetune: dict | None = None      # {"rounds": n, "lr": x}: extra trees fit only on latest season
    mean_from: str | None = None      # baseline mode: use this column as the projection (no model)
    model: str = "xgb"                # xgb | mlp (neural net) | ens (average of both)
    ens_w: float = 0.5                # weight on the neural net in 'ens'
    mlp: dict = field(default_factory=lambda: dict(
        hidden_layer_sizes=(128, 64), alpha=1e-3, learning_rate_init=1e-3, batch_size=512,
        max_iter=200, early_stopping=True, n_iter_no_change=8, validation_fraction=0.1, random_state=0))
    note: str = ""

    def to_json(self):
        return json.dumps(asdict(self), default=str)


def fit_count_spread(y: np.ndarray, mu: np.ndarray) -> tuple[float, float]:
    """How spread out a count stat is around its projection, as a negative binomial:
    variance = mu + alpha * mu^2, where alpha itself depends on the projection:

        alpha(mu) = exp(a + b * ln(mu))        -> returns (a, b), fitted by maximum likelihood

    One alpha for everyone (b = 0) gave big projections too much spread and small ones too little:
    the best alpha for the top third of projections was 2-5x smaller than for the bottom third, in
    every stat. Fitted b is close to -1, i.e. the variance is roughly proportional to the mean."""
    from scipy.optimize import minimize
    from scipy.stats import nbinom
    yi, m = np.round(np.maximum(y, 0)), np.maximum(mu, 1e-3)

    def loss(theta):
        n = 1 / _alpha(theta, m)
        return -nbinom.logpmf(yi, n, n / (n + m)).mean()

    return tuple(float(v) for v in minimize(loss, [np.log(0.1), 0.0], method="Nelder-Mead").x)


def _alpha(curve, m: np.ndarray) -> np.ndarray:
    return np.clip(np.exp(curve[0] + curve[1] * np.log(m)), 1e-4, 5)


def fingerprint(cfg: Config, *parts: pd.DataFrame) -> str:
    """Identifies everything a fit learns from: the settings, every input and target value of the rows
    (in order), the library versions, the CPU's thread count and GPU or CPU (both change the trees
    slightly) and the code in this file. Two fits with the same fingerprint produce the same model."""
    import sklearn
    h = hashlib.sha256()
    h.update(cfg.to_json().encode())
    h.update(f"xgboost {xgb.__version__} sklearn {sklearn.__version__} cpus {os.cpu_count()} "
             f"device {training_device()}".encode())
    h.update(Path(__file__).read_bytes() + TAUS.tobytes())
    cols = list(dict.fromkeys([*cfg.features, cfg.target, "SEASON", "GAME_DATE"]))
    for part in parts:
        h.update(pd.util.hash_pandas_object(part[cols], index=False).to_numpy().tobytes())
    return h.hexdigest()


def is_up_to_date(previous: "Pipeline | None", cfg: Config, df: pd.DataFrame, inner: int | None = None) -> bool:
    """True if `previous` was fitted with these settings on exactly these rows: fitting again would
    give the same model, so it can be kept as it is (e.g. an update that found no new games)."""
    if getattr(previous, "data_key", None) is None:   # no saved model, or one saved before fingerprints
        return False
    return previous.data_key == fingerprint(cfg, *Pipeline(cfg)._split(df, inner)[1:])


def load_model(path: Path) -> "Pipeline | None":
    """A saved model, or None if there isn't one or it can't be read (then it's simply trained again)."""
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ModuleNotFoundError):
        return None


def _dmat(df, cfg, label=True, weight=True):
    w = None
    if weight and cfg.recency_halflife:
        w = 0.5 ** ((df["SEASON"].max() - df["SEASON"]) / cfg.recency_halflife)
    return xgb.DMatrix(df[cfg.features], label=df[cfg.target] if label else None, weight=w,
                       missing=np.nan)


class Pipeline:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.curve = self.mlp_curve = None
        self.best_rounds = cfg.rounds
        self.inner_fit = None        # what steps 1-2 found, saved with the model for the next retrain
        self.reused_inner_fit = False
        self.data_key = None         # fingerprint of everything the final fit learned from

    # ------------------------------------------------------------ mean model
    def _params(self):
        p = dict(self.cfg.params, objective=self.cfg.objective, device=training_device())
        if self.cfg.objective == "reg:tweedie":
            p.setdefault("tweedie_variance_power", 1.3)
        return p

    def _train(self, df, rounds, valid=None):
        evals, res = [], {}
        dtr = _dmat(df, self.cfg)
        if valid is not None:
            evals = [(dtr, "train"), (_dmat(valid, self.cfg, weight=False), "valid")]
        params = self._params()
        if valid is not None:
            params["eval_metric"] = "logloss" if self.cfg.dist == "yes_no" else "mae"
        b = xgb.train(params, dtr, num_boost_round=rounds, evals=evals, evals_result=res,
                      early_stopping_rounds=self.cfg.patience if valid is not None else None,
                      verbose_eval=False)
        if self.cfg.finetune and valid is None:
            ft = self.cfg.finetune
            recent = df[df["SEASON"] == df["SEASON"].max()]
            b = xgb.train(dict(params, learning_rate=ft["lr"]), _dmat(recent, self.cfg),
                          num_boost_round=ft["rounds"], xgb_model=b)
        return _on_cpu(b), res

    def _fit_mlp(self, df):
        """Neural net: trained in epochs (full passes over the data) until a held-out 10%
        stops improving for 8 epochs in a row."""
        from sklearn.impute import SimpleImputer
        from sklearn.neural_network import MLPRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), MLPRegressor(**self.cfg.mlp))
        m.fit(df[self.cfg.features], df[self.cfg.target])
        return m

    def _mean(self, df, xgb_model=None, mlp_model=None, rng=(0, 0)):
        cfg = self.cfg
        if cfg.mean_from:
            fb = cfg.mean_from.rsplit("_", 1)[0] + "_L10"  # e.g. REB_EWM falls back to REB_L10
            return df[cfg.mean_from].fillna(df[fb] if fb in df else 0).to_numpy(float)
        parts = {}
        if cfg.model in ("xgb", "ens"):
            parts["xgb"] = xgb_model.predict(_dmat(df, cfg, label=False, weight=False), iteration_range=rng)
        if cfg.model in ("mlp", "ens"):
            parts["mlp"] = np.maximum(mlp_model.predict(df[cfg.features]), 0)
        if cfg.model == "ens":
            return (1 - cfg.ens_w) * parts["xgb"] + cfg.ens_w * parts["mlp"]
        return parts[cfg.model]

    # ---------------------------------------------------------------- fit
    def _split(self, df: pd.DataFrame, inner: int | None):
        """The rows a fit learns from: all of them, then the seasons before `inner`, `inner` itself
        and the seasons after it (the current one, for a final model)."""
        cfg = self.cfg
        df = df[df[cfg.target].notna()]  # e.g. dunks for the newest games, before their shot chart is in
        if cfg.min_season:
            df = df[df["SEASON"] >= cfg.min_season]
        inner = inner or df["SEASON"].max()
        return df, df[df["SEASON"] < inner], df[df["SEASON"] == inner], df[df["SEASON"] > inner]

    def fit(self, df: pd.DataFrame, inner: int | None = None, previous: "Pipeline | None" = None):
        """inner = season used for early stopping + uncertainty calibration (default: the latest).
        For the final model we pass the last COMPLETE season, so a half-finished current
        season isn't used for calibration (its games still go into the final fit).
        previous = the saved model this one replaces: its steps 1-2 are reused if they learned from
        exactly the same rows and settings."""
        cfg = self.cfg
        df, tr_in, va_in, later = self._split(df, inner)
        key = fingerprint(cfg, tr_in, va_in)
        saved = getattr(previous, "inner_fit", None)
        self.reused_inner_fit = bool(saved and saved["key"] == key)
        self.inner_fit = saved if self.reused_inner_fit else self._inner_fit(tr_in, va_in, key)
        self.best_rounds, self.curve, self.mlp_curve = (
            self.inner_fit[k] for k in ("best_rounds", "curve", "mlp_curve"))

        # 3. final fit on every season
        self.booster = self.mlp_model = None
        if not cfg.mean_from and cfg.model in ("xgb", "ens"):
            rounds = cfg.rounds
            if rounds is None:   # a bit more data than the inner fit had -> a few more trees
                rounds = int(self.best_rounds * min(len(df) / max(len(tr_in), 1), 1.2))
            self.booster, _ = self._train(df, rounds)
        if not cfg.mean_from and cfg.model in ("mlp", "ens"):
            self.mlp_model = self._fit_mlp(df)
        self._fit_dist(va_in, self.inner_fit["mu"], df)
        self.data_key = fingerprint(cfg, tr_in, va_in, later)
        return self

    def _inner_fit(self, tr_in: pd.DataFrame, va_in: pd.DataFrame, key: str) -> dict:
        """Steps 1-2: fit on the seasons before the inner season and predict it. Returns the round
        count early stopping chose, the learning curves and those out-of-sample predictions (they
        calibrate the uncertainty), tagged with the fingerprint of what they learned from."""
        cfg = self.cfg
        found = dict(key=key, best_rounds=cfg.rounds, curve=None, mlp_curve=None)
        b_in = m_in = None
        rng = (0, 0)  # (0, 0) = use all trees
        if not cfg.mean_from and cfg.model in ("xgb", "ens"):
            if cfg.rounds is None:  # early stopping on the inner season
                b_in, found["curve"] = self._train(tr_in, cfg.max_rounds, valid=va_in)
                found["best_rounds"] = b_in.best_iteration + 1
                rng = (0, found["best_rounds"])
            else:
                b_in, _ = self._train(tr_in, cfg.rounds)
        if not cfg.mean_from and cfg.model in ("mlp", "ens"):
            m_in = self._fit_mlp(tr_in)
            found["mlp_curve"] = dict(loss=m_in[-1].loss_curve_, val_r2=m_in[-1].validation_scores_)
        found["mu"] = self._mean(va_in, b_in, m_in, rng)
        return found

    # ---------------------------------------------------------- uncertainty
    def _fit_dist(self, va, mu, df_all):
        cfg = self.cfg
        y = va[cfg.target].to_numpy(float)
        resid = y - mu
        if cfg.dist == "bins":       # error spread by projection size (12 groups)
            self.edges = np.quantile(mu, np.linspace(0, 1, 13)[1:-1])
            b = np.digitize(mu, self.edges)
            self.rq = np.array([np.quantile(resid[b == i], TAUS) for i in range(12)])
        elif cfg.dist == "scaled":   # one error shape, width grows with sqrt(projection)
            self.zq = np.quantile(resid / np.sqrt(np.maximum(mu, 1)), TAUS)
        elif cfg.dist == "quantile":  # one model that directly predicts all 39 quantiles
            qp = dict(self._params(), objective="reg:quantileerror", quantile_alpha=TAUS,
                      learning_rate=0.08)
            self.qmodel = _on_cpu(xgb.train(qp, _dmat(df_all, cfg), num_boost_round=300))
        if cfg.dist in ("hetero", "both"):   # a 2nd model predicts how volatile THIS player-game is
            X = va[cfg.features].assign(MU=mu)
            half = (va["GAME_DATE"].dt.day % 2 == 0).to_numpy()   # cross-fit so z is out-of-sample
            sig = np.empty(len(va))
            sp = dict(max_depth=3, learning_rate=0.05, min_child_weight=50, subsample=0.8,
                      objective="reg:absoluteerror", verbosity=0, device=training_device())
            for a in (half, ~half):
                m = _on_cpu(xgb.train(sp, xgb.DMatrix(X[~a], label=np.abs(resid[~a])), 300))
                sig[a] = m.predict(xgb.DMatrix(X[a]))
            sig = np.maximum(sig, cfg.sig_floor)
            self.zq = np.quantile(resid / sig, TAUS)
            self.sig_model = _on_cpu(xgb.train(sp, xgb.DMatrix(X, label=np.abs(resid)), 300))
        if cfg.dist in ("nbinom", "both"):   # count distribution whose spread follows the projection
            self.spread = fit_count_spread(y, mu)
        # yes_no needs nothing here: a logistic model's output already is the chance
        if cfg.dist not in ("bins", "scaled", "quantile", "hetero", "nbinom", "both", "yes_no"):
            raise ValueError(cfg.dist)

    def _which(self, dist):
        d = dist or self.cfg.dist
        return "hetero" if d == "both" else d

    def _count_dist(self, mu):
        """Negative-binomial (n, p) for each projection."""
        m = np.maximum(mu, 1e-3)
        if getattr(self, "spread", None) is not None:
            n = 1 / _alpha(self.spread, m)
        else:  # a model saved before the spread followed the projection: one alpha for everyone
            n = np.full(len(m), 1 / self.alpha)
        return n, n / (n + m)

    # --------------------------------------------------------------- predict
    def predict(self, df: pd.DataFrame, dist: str | None = None):
        """Returns (projection, quantile matrix [n x 39])."""
        cfg, d = self.cfg, self._which(dist)
        mu = self._mean(df, self.booster, self.mlp_model)
        if d == "bins":
            Q = mu[:, None] + self.rq[np.digitize(mu, self.edges)]
        elif d == "scaled":
            Q = mu[:, None] + np.sqrt(np.maximum(mu, 1))[:, None] * self.zq
        elif d == "hetero":
            sig = np.maximum(self.sig_model.predict(xgb.DMatrix(df[cfg.features].assign(MU=mu))), cfg.sig_floor)
            Q = mu[:, None] + sig[:, None] * self.zq
        elif d == "nbinom":
            from scipy.stats import nbinom
            n, pr = self._count_dist(mu)
            Q = nbinom.ppf(TAUS[None, :], n[:, None], pr[:, None]).astype(float)
        elif d == "yes_no":   # 1 with chance mu: every quantile above (1 - mu) is 1
            Q = (TAUS[None, :] > 1 - mu[:, None]).astype(float)
        else:
            Q = self.qmodel.predict(_dmat(df, cfg, label=False, weight=False))
        floor = None if cfg.target == "Y_FS" else 0  # fantasy score can go negative
        Q = np.sort(Q if floor is None else np.maximum(Q, floor), axis=1)
        return mu, Q

    def prob_over(self, df: pd.DataFrame, lines, dist: str | None = None):
        """(projection, chance of More) for each row. See outcome_chances."""
        mu, more, _ = self.outcome_chances(df, lines, dist)
        return mu, more

    def outcome_chances(self, df: pd.DataFrame, lines, dist: str | None = None):
        """(projection, chance of More, chance of a push) for each row.

        On a whole-number line a stat that only takes whole values (everything but fantasy score) can
        land exactly on it: a push, and PrizePicks removes the pick. The chance of More is then counted
        among the outcomes that aren't a push, so More + Less = 100% and both compare directly with the
        break-even. (Counting a push as a Less win made Less look 5-7 points better than it is on
        typical whole-number lines.) On a .5 line there are no pushes and nothing changes."""
        d = self._which(dist)
        lines = np.asarray(lines, float)
        whole = (lines == np.round(lines)) & (self.cfg.target != "Y_FS")  # fantasy score has decimals
        mu = None
        if d == "nbinom":     # exact chance of each whole number
            from scipy.stats import nbinom
            mu = self._mean(df, self.booster, self.mlp_model)
            n, pr = self._count_dist(mu)
            more = nbinom.sf(np.floor(lines), n, pr)            # X > line
            less = nbinom.cdf(np.ceil(lines) - 1, n, pr)        # X < line
        elif d == "yes_no":   # 1 with chance mu, else 0
            mu = self._mean(df, self.booster, self.mlp_model)
            more = np.where(lines < 0, 1.0, np.where(lines < 1, mu, 0.0))
            less = np.where(lines > 1, 1.0, np.where(lines > 0, 1 - mu, 0.0))
        else:                 # a smooth curve: for a whole-number stat, the value k covers k-0.5 .. k+0.5
            mu, Q = self.predict(df, d)
            half = np.where(whole, 0.5, 0.0)
            more = p_over(Q, lines + half)
            less = 1 - p_over(Q, lines - half)
        push = np.clip(1 - more - less, 0, 1)
        return mu, more / np.maximum(more + less, 1e-9), push
