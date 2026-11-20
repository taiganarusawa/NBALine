"""The prediction engine: {player, stat, line} requests -> calibrated over/under probabilities.

For each request it
  1. finds the player and his team (from his most recent game),
  2. finds the game on the official NBA schedule (opponent, home/away, tip-off),
  3. reads the official injury report for that game (who's out, who's questionable),
  4. builds the model inputs exactly like training did, using only games before that date,
  5. runs the stat's model (points, rebounds, ...) and explains the biggest factors.

Used by both the command line (predict.py) and the web app (webapp.py), through analyze().
"""
import json
import pickle
import unicodedata
from datetime import date, datetime

import numpy as np
import pandas as pd
import xgboost as xgb

from . import features as F
from . import injuries as I
from . import lineups as L
from . import schedule as S
from .evaluate import TAUS
from .paths import POINTS_META, POINTS_MODEL, STATS_META, TEAM_LOGS, stat_model


# ---------------------------------------------------------------- finding players

def norm(s: str) -> str:
    """Lowercase and strip accents, so 'jokic' matches 'Jokić'."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


def match(names: pd.DataFrame, name: str) -> pd.DataFrame:
    key = names["PLAYER_NAME"].map(norm)
    hit = names[key == norm(name)]
    return hit if len(hit) else names[key.str.contains(norm(name), regex=False)]


def find_player(names: pd.DataFrame, name: str, cur: int) -> pd.Series:
    hit = match(names, name)
    if len(hit) > 1:
        recent = hit[hit["SEASON"] == cur]
        hit = recent if len(recent) >= 1 else hit
    if hit.empty:
        raise ValueError(f"No player matching '{name}' in the data.")
    if len(hit) > 1:
        raise ValueError(f"'{name}' matches several players: {', '.join(hit['PLAYER_NAME'])}. Be more specific.")
    return hit.iloc[0]


# ---------------------------------------------------------------- the game and who's out

def _match_schedule(r, team: str, game_date: pd.Timestamp, use_schedule: bool):
    """Opponent and home/away from the official schedule (checking any the user typed).
    Returns (opp, home, schedule_row or None)."""
    given_opp = (r.get("opp") or "").strip().upper() or None
    given_home = r.get("home")  # True / False / None (not given)
    if not use_schedule:
        if not given_opp or given_home is None:
            raise ValueError("--no-schedule needs the opponent and home/away (--opp and --home/--away).")
        return given_opp, given_home, None
    g = S.game_for(team, game_date.date())
    if g is None:
        nxt = S.next_games(team, game_date.date())
        hint = f" Next game: {S.describe(nxt.iloc[0], team)}." if len(nxt) else ""
        raise ValueError(f"{team} has no game on {game_date.date()}.{hint}")
    if str(g["POSTPONED"]) not in ("N", "nan", ""):
        raise ValueError(f"{team}'s game on {game_date.date()} is postponed.")
    home = g["HOME"] == team
    opp = g["AWAY"] if home else g["HOME"]
    if (given_opp and given_opp != opp) or (given_home is not None and given_home != home):
        where = "vs." if given_home else "at" if given_home is not None else "vs./at"
        raise ValueError(f"You entered {team} {where} {given_opp or opp}, "
                         f"but the schedule says {S.describe(g, team)}.")
    return opp, home, g


_REPORTS: dict = {}


def _key(name: str) -> str:
    return "".join(c for c in norm(name) if c.isalpha())


def _report_at(at):
    slot = at.replace(minute=at.minute - at.minute % 15, second=0, microsecond=0)
    if slot not in _REPORTS:
        _REPORTS[slot] = I.load(at)
    return _REPORTS[slot]


def _injury_info(game, team: str, opp: str, roster: pd.DataFrame, names: pd.DataFrame):
    """What the official injury report says about this game (latest report before tip-off).
    If a team shows 'not yet submitted' (common right after midnight, when a new day's report
    starts), use the most recent earlier report where that team had submitted for this game.
    Returns None if no report covers the game."""
    tip = S.tipoff(game).astimezone(I.ET)
    at = min(datetime.now(I.ET), tip - pd.Timedelta(minutes=1))
    gd = pd.Timestamp(game["GAME_DATE"]).strftime("%m/%d/%Y")
    mu = f"{game['AWAY']}@{game['HOME']}"
    found, pending, latest = {}, {team, opp}, None
    for hours_back in (0, 1, 2, 4, 8, 16, 24):
        rt, rep, not_submitted = _report_at(at - pd.Timedelta(hours=hours_back))
        if rt is None or rep.empty:
            break
        rows = rep[(rep["game_date"] == gd) & (rep["matchup"] == mu)]
        if rows.empty:
            break  # game isn't on this report (too far ahead, or reports stop listing it)
        latest = latest or rt
        # teams that haven't submitted for THIS game (a report also lists later games, which teams
        # often haven't submitted for yet; "*" = an old cached report that didn't say which game)
        waiting = {team for day, matchup, team in not_submitted if (day, matchup) in ((gd, mu), ("*", "*"))}
        for c in sorted(pending):
            if c not in waiting:
                found[c] = (rt, rows[rows["TEAM"] == c])
        pending -= set(found)
        if not pending:
            break
    if latest is None:
        return None
    keys = {_key(n): pid for n, pid in zip(roster["PLAYER_NAME"], roster["PLAYER_ID"])}
    every = {_key(n): pid for n, pid in zip(names["PLAYER_NAME"], names["PLAYER_ID"])}
    outs, listed, watch, notes = set(), {}, [], []
    for c, (rt, rows) in found.items():
        if rt != latest:
            notes.append(f"{c} from the {rt:%I:%M %p} ET report".replace(" 0", " "))
        for row in rows.itertuples():
            pid = keys.get(_key(row.player), every.get(_key(row.player)))
            if pid is not None:
                listed[pid] = (row.status, row.reason)
            if row.status in I.OUT_STATUSES and pid is not None:
                outs.add(pid)
            elif row.status in I.WATCH_STATUSES:
                watch.append(f"{row.player} ({row.TEAM}) {row.status}: {row.reason}")
    return dict(time=latest, outs=outs, listed=listed, watch=watch, covered=set(found),
                missing=sorted(pending), notes=notes)


# ---------------------------------------------------------------- model inputs

_RESOLVED = ("opp", "home", "game", "self_status", "inj")   # what _resolve adds to a request


def _resolve(r, names, team_ids, p, cur, game_date, use_schedule=True, use_injuries=True):
    """Look up the player, the game, and ruled-out players for one request (raises ValueError).
    Adds the _RESOLVED fields it finds to the request."""
    pl = find_player(names, r["player"], cur)
    pid, team_id, team = pl["PLAYER_ID"], pl["TEAM_ID"], pl["TEAM_ABBREVIATION"]
    opp, home, game = _match_schedule(r, team, game_date, use_schedule)
    r.update(opp=opp, home=home, game=game)
    if opp not in team_ids:
        raise ValueError(f"Unknown team '{opp}'. Options: {', '.join(sorted(team_ids.index))}")
    if p.loc[p["PLAYER_ID"] == pid, "GAME_DATE"].max() >= game_date:
        raise ValueError(f"{pl['PLAYER_NAME']} already has a game on/after {game_date.date()}. Use a later --date.")
    roster = names[names["TEAM_ID"].isin([team_id, team_ids[opp]])]  # outs can be on either team
    outs = set()
    for o in r.get("out") or []:
        m = match(roster, o)
        if m.empty:
            raise ValueError(f"Couldn't find '{o}' on {team} or {opp}.")
        outs.add(m["PLAYER_ID"].iloc[0])
    info = _injury_info(game, team, opp, roster, names) if (use_injuries and game is not None) else None
    if info:
        status, reason = info["listed"].get(pid, ("", ""))
        if status in I.OUT_STATUSES:
            raise ValueError(f"{pl['PLAYER_NAME']} is listed {status.upper()} on the official injury report "
                             f"({info['time']:%I:%M %p} ET): {reason}")
        if status in I.WATCH_STATUSES:
            r["self_status"] = f"{status}: {reason}"
        outs |= info["outs"]
    r["inj"] = info
    gid = "PRED_" + "_".join(sorted([team, opp]))  # one id per matchup, shared by both teams' players
    return gid, pid, team_id, team_ids[opp], pl, outs


def predict_requests(reqs: list[dict], game_date: pd.Timestamp, use_schedule: bool, use_injuries: bool,
                     errors: list):
    """Build model inputs for each request. Requests that can't be predicted (unknown player, no game
    that day, listed Out, ...) are added to `errors` as (request, message). Returns None if none can."""
    p, t = F.load_raw()
    # Only games before the one being predicted. For a past date this shows what the model would
    # have said before tip-off that day (that game and anything after it are left out).
    full, t = p[p["GAME_DATE"] < game_date], t[t["GAME_DATE"] < game_date]
    cur = full["SEASON"].max()
    # Team context and "who's out" only need recent seasons (it keeps this fast). The players being
    # predicted get their whole history added back below, so long-window inputs (last 40 games,
    # long-run averages) are built from the same games as in training.
    first = cur - 2
    p, t = full[full["SEASON"] >= first], t[t["SEASON"] >= first]
    names = p.drop_duplicates("PLAYER_ID", keep="last")
    team_ids = t.drop_duplicates("TEAM_ABBREVIATION", keep="last").set_index("TEAM_ABBREVIATION")["TEAM_ID"]

    blank = dict(GAME_DATE=game_date, SEASON=cur, SEASON_ID=int(f"2{cur}"))
    new_p, new_t, overrides, resolved, official = {}, {}, {}, [], set()
    lineup = _lineup(game_date)   # who's starting, once the teams' lineups are posted
    looked_up: dict = {}   # a pasted board has about 10 lines per player: look each player up once
    for r in reqs:
        who = (norm(r["player"]), r.get("opp"), r.get("home"), tuple(r.get("out") or ()))
        if who not in looked_up:
            try:
                item = _resolve(r, names, team_ids, p, cur, game_date, use_schedule, use_injuries)
                looked_up[who] = (item, {k: r[k] for k in _RESOLVED if k in r})
            except ValueError as e:
                looked_up[who] = str(e)
        if isinstance(looked_up[who], str):
            errors.append((r, looked_up[who]))
            continue
        item, found = looked_up[who]
        r.update(found)
        gid, pid, team_id, opp_id, pl, outs = item
        for tid in (team_id, opp_id):
            new_t[(gid, tid)] = {**blank, "GAME_ID": gid, "TEAM_ID": tid}
        vs = "vs." if r["home"] else "@"
        team = pl["TEAM_ABBREVIATION"]
        # (1 starting / 0 bench, "Expected" | "Confirmed", inactive), or None: his team's lineup isn't posted.
        # An inactive player isn't playing at all, so the model isn't told he's coming off the bench.
        role = lineup.get(int(pid))
        new_p[(gid, pid)] = {**blank, "GAME_ID": gid, "PLAYER_ID": pid, "PLAYER_NAME": pl["PLAYER_NAME"],
                             "TEAM_ID": team_id, "TEAM_ABBREVIATION": team, "MATCHUP": f"{team} {vs} {r['opp'].upper()}",
                             "STARTED": role[0] if role and not role[2] else np.nan}
        overrides.setdefault(gid, set()).update(outs)
        if r.get("inj"):  # official report covers these teams: no guessing from recent games
            official |= {(gid, team_ids[c]) for c in r["inj"]["covered"]}
        resolved.append(dict(r, pid=pid, name=pl["PLAYER_NAME"], team=team, team_id=team_id, gid=gid,
                             opp=r["opp"].upper(), role=role))
    if not resolved:
        return None

    older = full[(full["SEASON"] < first) & full["PLAYER_ID"].isin({pid for _, pid in new_p})]
    p = pd.concat([older, p, pd.DataFrame(new_p.values())], ignore_index=True)
    t = pd.concat([t, pd.DataFrame(new_t.values())], ignore_index=True)
    needed = F.history_keys({r.get("key", "PTS") for r in resolved} - {"PTS"})
    df, details = F.build_features(p, t, overrides, official, stats=needed or None,
                                   stat_players={pid for _, pid in new_p})
    # .copy() packs the ~200 columns (added one at a time while building) into one block, so pandas
    # doesn't warn that the table is "highly fragmented" when the next step adds the index columns
    rows = df[df["GAME_ID"].str.startswith("PRED")].copy().set_index(["GAME_ID", "PLAYER_ID"])
    X = rows.loc[[(r["gid"], r["pid"]) for r in resolved]].reset_index()
    return X, resolved, details, names, p


def _lineup(game_date: pd.Timestamp) -> dict:
    """That day's starting lineups from NBA.com ({player_id: (1 / 0, status)}), or none if it can't be
    reached: the model then goes by how often each player has started lately."""
    try:
        return L.for_day(game_date.date())
    except Exception as e:
        print(f"Couldn't read the starting lineups: {type(e).__name__}: {e}")
        return {}


# ---------------------------------------------------------------- freshness checks

def stale_warnings() -> list[str]:
    """Warnings if finished games are missing from the data or the model is old."""
    out = []
    try:
        t = pd.read_csv(TEAM_LOGS, usecols=["GAME_ID"], dtype=str)
        miss = S.missing_finals(set(t["GAME_ID"]))
        if len(miss):
            out.append(f"DATA IS OUT OF DATE. {len(miss)} finished game(s) aren't downloaded "
                       f"(most recent {miss['GAME_DATE'].max()}). Run:  python fetch_data.py")
    except Exception as e:
        out.append(f"Couldn't check data freshness ({e})")
    meta = json.loads(POINTS_META.read_text())
    age = (date.today() - date.fromisoformat(meta["trained_on"])).days
    if age > 10:
        out.append(f"The model was last trained {age} days ago. Run:  python train.py")
    return out


def warn_if_stale():
    for w in stale_warnings():
        print(f"WARNING: {w}\n")


_PIPE: dict = {}


# ---------------------------------------------------------------- models and explanations

def load_pipeline():
    """The trained model, loaded once and reloaded if train.py has replaced it."""
    path = POINTS_MODEL
    mtime = path.stat().st_mtime
    if _PIPE.get("mtime") != mtime:
        with open(path, "rb") as f:
            _PIPE.update(pipe=pickle.load(f), mtime=mtime,
                         meta=json.loads(POINTS_META.read_text()))
    return _PIPE["pipe"], _PIPE["meta"]


def explain(pipe, X: pd.DataFrame, mu_xgb: np.ndarray) -> list[list[tuple]]:
    """Each row's top reasons as (points, label, shown value), from SHAP values of the XGBoost part,
    worked out for all the rows at once. mu_xgb: the XGBoost part's prediction for each row."""
    if pipe.booster is None:
        return [[] for _ in range(len(X))]
    feats = pipe.cfg.features
    values = X[feats]
    contribs = pipe.booster.predict(xgb.DMatrix(values), pred_contribs=True)[:, :-1]   # last column: the bias
    return [_top_reasons(pipe, values.iloc[i], c, float(mu)) for i, (c, mu) in enumerate(zip(contribs, mu_xgb))]


def _top_reasons(pipe, row: pd.Series, c: np.ndarray, mu_xgb: float) -> list[tuple]:
    """One row's 6 biggest inputs, from its SHAP values c. For a yes/no stat (double-double) the effect
    is in percentage points of chance instead of the stat's own units."""
    feats = pipe.cfg.features
    if pipe.cfg.objective in ("count:poisson", "reg:tweedie"):     # log link
        pts = mu_xgb * (1 - np.exp(-c))   # points this input adds vs. an average player
    elif pipe.cfg.objective == "binary:logistic":                   # log-odds
        odds = np.log(mu_xgb / (1 - mu_xgb))
        pts = 100 * (mu_xgb - 1 / (1 + np.exp(-(odds - c))))      # chance this input adds, in % points
    else:
        pts = c
    out = []
    for j in np.argsort(-np.abs(pts))[:6]:
        f, v = feats[j], row.iloc[j]
        if f in ("HOME", "B2B", "OPP_B2B", "STARTING") and not pd.isna(v):
            shown = "yes" if v else "no"
        else:
            shown = "n/a" if pd.isna(v) else f"{v:.2f}" if abs(v) < 2 else f"{v:.1f}"
        out.append((round(float(pts[j]), 1), F.feature_label(f), shown))
    return out


_STATS: dict = {}


def load_stat_model(key: str):
    """(pipeline, info) for a non-points stat, or (None, None) if it hasn't been trained."""
    path = stat_model(key)
    if not path.exists():
        return None, None
    if _STATS.get(key, {}).get("mtime") != path.stat().st_mtime:
        with open(path, "rb") as f:
            pipe = pickle.load(f)
        info = json.loads(STATS_META.read_text()).get(key, {}) if STATS_META.exists() else {}
        _STATS[key] = dict(pipe=pipe, info=info, mtime=path.stat().st_mtime)
    return _STATS[key]["pipe"], _STATS[key]["info"]


def modeled_stats() -> dict:
    """{stat name: well tested?} for every stat with a trained model (points always has one)."""
    out = {"Points": True}
    info = json.loads(STATS_META.read_text()) if STATS_META.exists() else {}
    for key, i in info.items():
        if stat_model(key).exists():
            out[i["stat"]] = bool(i["reliable"])
    return out


# ---------------------------------------------------------------- analysis (the public entry point)

def analyze(reqs: list[dict], game_date: pd.Timestamp, use_schedule=True, use_injuries=True) -> list[dict]:
    """Predict every request ({player, line, stat?}). Returns one dict per request, in the same
    order; a request that couldn't be predicted has an 'error' message instead of numbers."""
    for i, r in enumerate(reqs):
        r["_i"] = i
        r["stat"] = r.get("stat") or "Points"
        r["key"] = F.NAME_TO_KEY.get(r["stat"])
    bad = [r for r in reqs if r["key"] is None]
    reqs = [r for r in reqs if r["key"] is not None]
    errors: list = [(r, f"Unknown stat '{r['stat']}'") for r in bad]
    built = predict_requests(reqs, game_date, use_schedule, use_injuries, errors=errors) if reqs else None
    results = [dict(index=r["_i"], player=r["player"], stat=r["stat"], line=r.get("line"), error=msg)
               for r, msg in errors]
    if built is None:
        return sorted(results, key=lambda d: d["index"])
    X, resolved, details, names, p = built
    pts_pipe, meta = load_pipeline()
    name_of = names.set_index("PLAYER_ID")["PLAYER_NAME"]
    team_of = names.set_index("PLAYER_ID")["TEAM_ID"]
    preds = {}
    for key in {r["key"] for r in resolved}:
        idx = [i for i, r in enumerate(resolved) if r["key"] == key]
        pipe, info = (pts_pipe, {"reliable": True}) if key == "PTS" else load_stat_model(key)
        if pipe is None:
            continue
        Xk = X.iloc[idx]
        mu, Q = pipe.predict(Xk)
        _, pov, push = pipe.outcome_chances(Xk, [float(resolved[i]["line"]) for i in idx])
        mx = pipe.booster.predict(xgb.DMatrix(Xk[pipe.cfg.features])) if pipe.booster is not None else mu
        reasons = explain(pipe, Xk, mx)
        for j, i in enumerate(idx):
            preds[i] = dict(mu=float(mu[j]), Q=Q[j], p=float(pov[j]), push=float(push[j]),
                            reasons=reasons[j], reliable=bool(info.get("reliable", False)))
    # each player's last 8 games, for the recent results shown with every line
    played = p[p["PLAYER_ID"].isin({r["pid"] for r in resolved}) & p["PTS"].notna()]
    last8 = {pid: g for pid, g in played.sort_values("GAME_DATE").groupby("PLAYER_ID").tail(8).groupby("PLAYER_ID")}
    for i, r in enumerate(resolved):
        g, inj = r["game"], r.get("inj")
        gone = details.get(r["gid"], {})
        outs = {}
        for label, mine in ((r["team"], True), (r["opp"], False)):
            o = [f"{name_of[q]} ({fga:.0f} FGA/g)" for q, fga in gone.items()
                 if (team_of.get(q) == r["team_id"]) == mine]
            if o:
                outs[label] = o
        hist = last8.get(r["pid"], played.iloc[:0])
        vals = sum(w * hist[c] for c, w in F.STAT_KEYS[r["key"]].items())
        low_minutes = not X["MIN_L10"].iloc[i] >= F.MIN_TESTED_MINUTES  # bench player or no history: untested ground
        res = dict(
            index=r["_i"], request=r, player=r["name"], player_id=int(r["pid"]), team=r["team"], opp=r["opp"],
            home=bool(r["home"]), stat=r["stat"], key=r["key"], line=float(r["line"]),
            yes_no=r["key"] in F.YES_NO_STATS,
            game_date=str(game_date.date()),
            game_id=g["GAME_ID"] if g is not None else "", tipoff_utc=g["TIPOFF_UTC"] if g is not None else "",
            tip_local=S.local_time(g) if g is not None else "", started=bool(g is not None and S.has_started(g)),
            modeled=i in preds, reliable=i in preds and preds[i]["reliable"] and not low_minutes,
            low_minutes=bool(low_minutes),
            usual_minutes=None if pd.isna(m := X["MIN_EWM"].iloc[i]) else round(float(m), 1),   # for the live chance
            proj=None, q10=None, q50=None, q90=None, sd=None, p_over=None, p_push=None, reasons=[],
            injury_report=f"{inj['time']:%I:%M %p} ET".lstrip("0") if inj else None,
            injury_missing=inj["missing"] if inj else [], injury_notes=inj["notes"] if inj else [],
            self_status=r.get("self_status"), outs=outs, questionable=(inj or {}).get("watch", []),
            # tonight's role from the posted lineup, against how often he's started lately (share of last 10)
            lineup=dict(starting=bool(r["role"][0]), status=r["role"][1], inactive=r["role"][2]) if r.get("role") else None,
            start_rate=None if pd.isna(sr := X["START_RATE_L10"].iloc[i]) else round(float(sr), 2),
            recent=[(f"{d:%m/%d}", round(float(v), 1)) for d, v in zip(hist["GAME_DATE"], vals) if pd.notna(v)],
            model=meta["config"], data_through=meta["data_through"])
        if i in preds:
            q10, q50, q90 = np.interp([0.1, 0.5, 0.9], TAUS, preds[i]["Q"])
            res.update(proj=round(preds[i]["mu"], 1), q10=round(float(q10), 1), q50=round(float(q50), 1),
                       q90=round(float(q90), 1), sd=round(float(np.std(preds[i]["Q"])), 2),   # the 39 quantiles' spread
                       p_over=round(preds[i]["p"], 4), p_push=round(preds[i]["push"], 4), reasons=preds[i]["reasons"])
        results.append(res)
    return sorted(results, key=lambda d: d["index"])
