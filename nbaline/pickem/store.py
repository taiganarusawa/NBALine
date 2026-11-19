"""Saving and grading: your checked lines, pasted boards and entries, in a local SQLite database.

After the games, grade_all() fills in every pick's and every checked line's real result from the
box scores and settles each entry the PrizePicks way. summary() turns that into the Results tab:
your profit, your hit rate, and how the model's probabilities did against PrizePicks' lines.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from .. import features as F
from ..paths import PICKEM_DB as DB, PLAYER_LOGS
from .payouts import entry_odds, paid_status, settle, stat_value


# ---------------------------------------------------------------- storage
SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
  id INTEGER PRIMARY KEY, created_at TEXT, game_date TEXT, kind TEXT, stake REAL,
  payouts TEXT, ev REAL, p_profit REAL, status TEXT DEFAULT 'open', payout REAL, graded_at TEXT, note TEXT,
  protected INTEGER DEFAULT 0, paid_set REAL);
CREATE TABLE IF NOT EXISTS picks (
  id INTEGER PRIMARY KEY, entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
  player_id INTEGER, player TEXT, team TEXT, opp TEXT, game_date TEXT, game_id TEXT, started INTEGER,
  stat TEXT, line REAL, side TEXT, model_p REAL, proj REAL, actual REAL, result TEXT, line_type TEXT,
  sd REAL, usual_minutes REAL, p_push REAL);
CREATE TABLE IF NOT EXISTS checks (
  id INTEGER PRIMARY KEY, created_at TEXT, game_date TEXT, game_id TEXT, started INTEGER,
  player_id INTEGER, player TEXT, team TEXT, opp TEXT, stat TEXT, line REAL,
  proj REAL, p_over REAL, actual REAL, result TEXT, line_type TEXT);
CREATE TABLE IF NOT EXISTS boards (
  id INTEGER PRIMARY KEY, created_at TEXT, game_date TEXT, text TEXT, lines INTEGER, unread INTEGER);
"""
# line_type: empty = a standard line (More or Less). PrizePicks also has More-only lines:
# "goblin" (easier line, pays less), "demon" (harder line, pays more), or "more_only" when the
# pasted board didn't show which. They aren't meant to be 50/50, so they're graded separately.
MORE_ONLY_TYPES = ("goblin", "demon", "more_only")
# protected: a PrizePicks protected play. If it loses outright (pays nothing), it's left out of your
# profit and ROI; anything it pays back counts as usual.
# payout: what a graded entry paid, the one counted in your profit. The app works it out from the
# entry's payout table, unless paid_set holds what PrizePicks really paid (typed in on the Results tab,
# since PrizePicks' payouts change): then that's the payout, and re-grading keeps it.

# columns added after the first databases were made: (table, column, type)
ADDED_COLUMNS = [("picks", "line_type", "TEXT"), ("checks", "line_type", "TEXT"), ("entries", "protected", "INTEGER DEFAULT 0"),
                 ("entries", "paid_set", "REAL"), ("picks", "sd", "REAL"), ("picks", "usual_minutes", "REAL"),
                 ("picks", "p_push", "REAL")]
# picks.sd and usual_minutes: the model's spread and his usual minutes when saved, which the live
# chance during the game starts from (with proj; see ingame.py). p_push: the model's chance he lands
# exactly on a whole-number line (a push: the pick reverts); model_p leaves pushes out.


@contextmanager
def db():
    """Open the database, commit on success, and always close it (Windows locks open files)."""
    DB.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.executescript(SCHEMA)
        for table, column, kind in ADDED_COLUMNS:   # databases made before these columns existed
            if column not in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        yield con
        con.commit()
    finally:
        con.close()


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log_checks(rows: list[dict]):
    """Every line the model analyzed, so its accuracy vs. PrizePicks can be measured on all of them."""
    with db() as con:
        for r in rows:
            con.execute("INSERT INTO checks (created_at, game_date, game_id, started, player_id, player, team, opp,"
                        " stat, line, proj, p_over, line_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (now(), r["game_date"], r["game_id"], int(r["started"]), r["player_id"], r["player"],
                         r["team"], r["opp"], r["stat"], r["line"], r.get("proj"), r.get("p_over"),
                         r.get("line_type")))


def save_board(game_date: str, text: str, lines: int, unread: int):
    """Keep the pasted board text exactly as pasted (skipping an identical re-paste), so it can be
    re-read later: lines the app couldn't use today, line movement, and PrizePicks lines as model input."""
    with db() as con:
        if not con.execute("SELECT 1 FROM boards WHERE game_date = ? AND text = ?", (game_date, text)).fetchone():
            con.execute("INSERT INTO boards (created_at, game_date, text, lines, unread) VALUES (?,?,?,?,?)",
                        (now(), game_date, text, lines, unread))


def save_entry(game_date: str, kind: str, stake: float, picks: list[dict], payouts: dict, note: str = "",
               protected: bool = False) -> int:
    probs = [p["model_p"] for p in picks]
    odds = entry_odds(probs, kind, payouts) if all(p is not None for p in probs) else None
    with db() as con:
        cur = con.execute("INSERT INTO entries (created_at, game_date, kind, stake, payouts, ev, p_profit, note, protected)"
                          " VALUES (?,?,?,?,?,?,?,?,?)",
                          (now(), game_date, kind, stake, json.dumps(payouts),
                           odds["ev"] if odds else None, odds["p_profit"] if odds else None, note, int(protected)))
        eid = cur.lastrowid
        for p in picks:
            con.execute("INSERT INTO picks (entry_id, player_id, player, team, opp, game_date, game_id, started,"
                        " stat, line, side, model_p, proj, line_type, sd, usual_minutes, p_push)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (eid, p["player_id"], p["player"], p["team"], p["opp"], p["game_date"], p["game_id"],
                         int(p["started"]), p["stat"], p["line"], p["side"], p["model_p"], p.get("proj"),
                         p.get("line_type"), p.get("sd"), p.get("usual_minutes"), p.get("p_push")))
    return eid


def set_protected(eid: int, protected: bool):
    """Mark an entry as a protected play (or not), e.g. one saved before you ticked the box."""
    with db() as con:
        con.execute("UPDATE entries SET protected = ? WHERE id = ?", (int(protected), eid))


def set_payouts(eid: int, payouts: dict):
    """Change an open entry's payouts (its tables and profit boost; payouts.checked), e.g. to what
    PrizePicks shows once a pick reverts. The model's expected return when saved follows them."""
    with db() as con:
        e = con.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()
        if e is None or e["status"] != "open":
            raise ValueError("Only an open entry's payouts can be changed. For a graded one, edit what it paid.")
        probs = [r["model_p"] for r in con.execute("SELECT model_p FROM picks WHERE entry_id = ? ORDER BY id", (eid,))]
        odds = entry_odds(probs, e["kind"], payouts) if all(p is not None for p in probs) else None
        con.execute("UPDATE entries SET payouts = ?, ev = ?, p_profit = ? WHERE id = ?",
                    (json.dumps(payouts), odds["ev"] if odds else e["ev"], odds["p_profit"] if odds else e["p_profit"], eid))


def set_paid(eid: int, amount: float | None):
    """What PrizePicks really paid for a graded entry, when it isn't what the app worked out (PrizePicks'
    payouts change). None goes back to the app's own amount. Won, partial or lost follows the amount."""
    with db() as con:
        e = con.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone()
        if e is None or e["status"] == "open":
            raise ValueError("Only a graded entry's payout can be changed.")
        con.execute("UPDATE entries SET paid_set = ? WHERE id = ?", (None if amount is None else round(amount, 2), eid))
        _settle(con, con.execute("SELECT * FROM entries WHERE id = ?", (eid,)).fetchone())


def delete_entry(eid: int):
    with db() as con:
        con.execute("DELETE FROM picks WHERE entry_id = ?", (eid,))
        con.execute("DELETE FROM entries WHERE id = ?", (eid,))


def list_entries() -> list[dict]:
    with db() as con:
        entries = [dict(r) for r in con.execute("SELECT * FROM entries ORDER BY game_date DESC, id DESC")]
        for e in entries:
            e["payouts"] = json.loads(e["payouts"])
            e["picks"] = [dict(r) for r in con.execute("SELECT * FROM picks WHERE entry_id = ? ORDER BY id", (e["id"],))]
            if e["paid_set"] is not None:   # you typed in what PrizePicks paid: what the app had worked out, beside it
                e["calculated"] = settle([p["result"] for p in e["picks"]], e["kind"], e["stake"], e["payouts"])[1]
    return entries


# ---------------------------------------------------------------- grading
def _box_lookup(dates: set):
    """Box scores for just the dates that still need grading (fast)."""
    p, t = F.load_raw()
    p = p[p["GAME_DATE"].dt.strftime("%Y-%m-%d").isin(dates)]
    box = {(int(r.PLAYER_ID), r.GAME_DATE.strftime("%Y-%m-%d")): r for r in p.itertuples()}
    finished = set(t["GAME_ID"].astype(str))
    return box, finished


def _grade_one(box, finished, player_id, game_date, game_id, stat, line, side=None):
    """Returns (actual, result) or (None, None) if the game isn't final yet."""
    row = box.get((int(player_id), game_date))
    if row is None:
        return (None, "void") if game_id in finished else (None, None)  # final + no box score = didn't play
    actual = stat_value(row._asdict(), stat)
    if actual != actual:
        return None, None  # NaN: not downloaded yet (dunks come from the shot chart, a separate download)
    if actual == line:
        return actual, "push"
    over = actual > line
    if side is None:
        return actual, "over" if over else "under"
    return actual, "hit" if (over == (side == "more")) else "miss"


RECHECK_DAYS = 3        # grades this recent are checked again whenever new box scores arrive
_rechecked_for = None   # the box scores' version (file time) last checked again, in this server


def _recheck_recent(con) -> int:
    """Grades from the last few days, checked again against the latest box scores. A download made
    as games finish can catch a few stats before they're final; the next download has them, and
    then any grade that changed is corrected, and an entry whose picks changed is settled again.
    Returns how many grades were corrected."""
    cutoff = (date.today() - timedelta(days=RECHECK_DAYS)).isoformat()
    graded = {table: con.execute(f"SELECT * FROM {table} WHERE result IS NOT NULL AND game_date >= ?", (cutoff,)).fetchall()
              for table in ("picks", "checks")}
    if not any(graded.values()):
        return 0
    box, finished = _box_lookup({r["game_date"] for rows in graded.values() for r in rows})
    corrected, entries = 0, set()
    for table, rows in graded.items():
        for r in rows:
            actual, result = _grade_one(box, finished, r["player_id"], r["game_date"], r["game_id"], r["stat"], r["line"],
                                        r["side"] if table == "picks" else None)
            if result is None or (actual, result) == (r["actual"], r["result"]):
                continue   # unchanged (or the game is held back until it's complete: keep the grade until then)
            con.execute(f"UPDATE {table} SET actual = ?, result = ? WHERE id = ?", (actual, result, r["id"]))
            corrected += 1
            if table == "picks":
                entries.add(r["entry_id"])
    for e in con.execute("SELECT * FROM entries WHERE status != 'open'").fetchall():
        if e["id"] in entries:
            _settle(con, e)
    return corrected


def _pick_results(con, eid: int) -> list:
    return [r["result"] for r in con.execute("SELECT result FROM picks WHERE entry_id = ?", (eid,))]


def _settle(con, e, results: list | None = None):
    """Settle one entry from its picks' results and save it: the PrizePicks way, from its payout table,
    or with what PrizePicks really paid, if you typed it in (paid_set)."""
    status, pay = settle(results or _pick_results(con, e["id"]), e["kind"], e["stake"], json.loads(e["payouts"]))
    if e["paid_set"] is not None and e["paid_set"] != pay:
        status, pay = paid_status(e["paid_set"], e["stake"]), e["paid_set"]
    con.execute("UPDATE entries SET status = ?, payout = ?, graded_at = ? WHERE id = ?", (status, pay, now(), e["id"]))


def grade_all() -> dict:
    global _rechecked_for
    counts = dict(picks=0, entries=0, corrected=0)
    with db() as con:
        version = PLAYER_LOGS.stat().st_mtime
        if version != _rechecked_for:   # new box scores since the last look: check recent grades again
            counts["corrected"] = _recheck_recent(con)
            _rechecked_for = version
        dates = {r[0] for r in con.execute("SELECT game_date FROM picks WHERE result IS NULL "
                                           "UNION SELECT game_date FROM checks WHERE result IS NULL")}
        if not dates and not con.execute("SELECT 1 FROM entries WHERE status = 'open'").fetchone():
            return counts  # nothing waiting to be graded
        box, finished = _box_lookup(dates)
        for pk in con.execute("SELECT * FROM picks WHERE result IS NULL").fetchall():
            actual, result = _grade_one(box, finished, pk["player_id"], pk["game_date"], pk["game_id"],
                                        pk["stat"], pk["line"], pk["side"])
            if result:
                con.execute("UPDATE picks SET actual = ?, result = ? WHERE id = ?", (actual, result, pk["id"]))
                counts["picks"] += 1
        for ck in con.execute("SELECT * FROM checks WHERE result IS NULL").fetchall():
            actual, result = _grade_one(box, finished, ck["player_id"], ck["game_date"], ck["game_id"],
                                        ck["stat"], ck["line"])
            if result:
                con.execute("UPDATE checks SET actual = ?, result = ? WHERE id = ?", (actual, result, ck["id"]))
        for e in con.execute("SELECT * FROM entries WHERE status = 'open'").fetchall():
            res = _pick_results(con, e["id"])
            if res and all(res):
                _settle(con, e, res)
                counts["entries"] += 1
    return counts


def summary() -> dict:
    """Your results, plus how well the model's probabilities did against PrizePicks' lines."""
    with db() as con:
        ent = pd.read_sql("SELECT * FROM entries", con)
        pk = pd.read_sql("SELECT * FROM picks", con)
        ck = pd.read_sql("SELECT * FROM checks", con)
        boards = con.execute("SELECT COUNT(*) FROM boards").fetchone()[0]
    out = {}
    done = ent[ent["status"] != "open"]
    # a protected play that lost outright isn't money lost: it stays in the record, but not in profit or ROI
    protected_loss = (done["protected"].fillna(0) == 1) & (done["payout"].fillna(0) <= 0)
    counted = done[~protected_loss]
    out["entries"] = dict(total=len(ent), open=int((ent["status"] == "open").sum()),
                          won=int((done["status"] == "won").sum()), partial=int((done["status"] == "partial").sum()),
                          lost=int((done["status"] == "lost").sum()), refund=int((done["status"] == "refund").sum()),
                          protected_losses=int(protected_loss.sum()),
                          staked=float(counted["stake"].sum()), returned=float(counted["payout"].sum()))
    out["entries"]["profit"] = out["entries"]["returned"] - out["entries"]["staked"]
    out["entries"]["roi"] = out["entries"]["profit"] / out["entries"]["staked"] if out["entries"]["staked"] else None
    g = pk[pk["result"].isin(["hit", "miss"])]
    out["picks"] = dict(graded=len(g), hits=int((g["result"] == "hit").sum()),
                        hit_rate=float((g["result"] == "hit").mean()) if len(g) else None)

    # More-only lines (Goblins/Demons) on their own: they aren't meant to be 50/50
    ids = set(pk.loc[pk["line_type"].isin(MORE_ONLY_TYPES), "entry_id"])
    sd = done[done["id"].isin(ids)]
    money = counted[counted["id"].isin(ids)]   # protected losses left out, as above
    staked, returned = float(money["stake"].sum()), float(money["payout"].sum())
    out["entries_more_only"] = dict(graded=len(sd), open=int(((ent["status"] == "open") & ent["id"].isin(ids)).sum()),
                                    won=int((sd["status"] == "won").sum()), staked=staked,
                                    profit=returned - staked, roi=(returned - staked) / staked if staked else None)

    # Every PrizePicks line you pasted or checked is saved and graded once its game is over.
    c = _last_seen(ck[ck["result"].isin(["over", "under"]) & ck["p_over"].notna()])
    out["saved"] = _saved_lines(ck, c, boards)
    out["more_only"] = {kind: dict(lines=_how_lines_went(c[c["line_type"] == kind]),
                                   picks=_how_picks_went(g[g["line_type"] == kind]))
                        for kind in MORE_ONLY_TYPES}
    c = c[~c["line_type"].isin(MORE_ONLY_TYPES)]  # the 50/50 comparison is for standard lines only
    pre = c[c["started"] == 0]
    model = dict(graded=len(c), pregame=len(pre))
    if len(c):
        y = (c["result"] == "over").astype(float)
        model["brier_model"] = float(((c["p_over"] - y) ** 2).mean())
        model["brier_coinflip"] = 0.25  # PrizePicks lines are meant to be 50/50
        sure = np.maximum(c["p_over"], 1 - c["p_over"]).round(4)   # its chance for the side it favoured
        right = pd.Series(np.where(c["p_over"] > 0.5, y == 1, y == 0), index=c.index)
        lean = sure >= LEAN_AT
        model["lean_n"] = int(lean.sum())
        model["lean_hit_rate"] = float(right[lean].mean()) if lean.any() else None
        pts = c[c["stat"] == "Points"]
        model["mae"] = float((pts["actual"] - pts["proj"]).abs().mean()) if len(pts) else None
        model["by_stat"] = {st: dict(n=len(g), nights=int(g["game_date"].nunique()), hit_rate=float(right[g.index].mean()))
                            for st, g in c.groupby("stat")}
        model["by_sure"] = _by_sure(sure, right)
    out["model"] = model
    return out


def _saved_lines(checks: pd.DataFrame, counted: pd.DataFrame, boards: int) -> dict:
    """Every saved line (player, day, stat and line), and where each one went: graded and counted, or
    why not: its game isn't over yet, the player didn't play, it landed exactly on the line (a push),
    no model for the stat, or the same player and stat was seen again later that day at another line
    (only the last line before tip-off counts). The parts add up to `lines`."""
    lines = checks.drop_duplicates(["player_id", "game_date", "stat", "line"])
    done = lines[lines["result"].notna()]
    decided = done[done["result"].isin(["over", "under"])]
    return dict(lines=len(lines), days=int(checks["game_date"].nunique()), boards=boards,
                waiting=int(lines.loc[lines["result"].isna(), "game_date"].nunique()),   # days
                waiting_lines=int(lines["result"].isna().sum()),
                void=int((done["result"] == "void").sum()), push=int((done["result"] == "push").sum()),
                no_model=int(decided["p_over"].isna().sum()),
                moved=int(decided["p_over"].notna().sum()) - len(counted),
                graded=len(counted))


def _last_seen(checks: pd.DataFrame) -> pd.DataFrame:
    """Saved lines as they're scored: each player/stat/day once, at the last line seen before tip-off
    (PrizePicks moves lines, and a re-paste isn't a new line). Goblins and Demons sit beside the
    standard line, so they're kept per line."""
    c = checks.sort_values(["started", "id"], ascending=[False, True])  # pregame checks last, newest last
    special = c["line_type"].isin(MORE_ONLY_TYPES)
    return pd.concat([c[~special].drop_duplicates(["player_id", "game_date", "stat"], keep="last"),
                      c[special].drop_duplicates(["player_id", "game_date", "stat", "line"], keep="last")])


def long_shots(game_date: str | None = None) -> dict:
    """The lines that hit on one day (default: the latest graded one), least likely first by the model's
    chance before tip-off: which bets would have paid off against the odds. A standard line hits on
    whichever side won; a Goblin or Demon only when it went over, since More is the only way to play it.
    Lines you played in an entry are marked."""
    with db() as con:
        ck = pd.read_sql("SELECT * FROM checks WHERE result IN ('over', 'under') AND p_over IS NOT NULL"
                         " AND started = 0", con)
        pk = pd.read_sql("SELECT game_date, player_id, stat, line, side FROM picks", con)
    days = sorted(ck["game_date"].unique(), reverse=True)
    if not days:
        return dict(days=[], date=None, lines=[])
    day = game_date if game_date in days else days[0]
    played = set(pk.loc[pk["game_date"] == day, ["player_id", "stat", "line", "side"]].itertuples(index=False, name=None))
    c = _last_seen(ck[ck["game_date"] == day])
    c = c[~c["line_type"].isin(MORE_ONLY_TYPES) | (c["result"] == "over")]
    lines = []
    for r in c.to_dict("records"):
        side = "more" if r["result"] == "over" else "less"
        kind = r["line_type"] if isinstance(r["line_type"], str) and r["line_type"] else None   # None: standard
        lines.append(dict(player=r["player"], team=r["team"], opp=r["opp"], stat=r["stat"], line=r["line"],
                          line_type=kind, side=side, actual=r["actual"],
                          chance=r["p_over"] if side == "more" else 1 - r["p_over"],
                          played=(r["player_id"], r["stat"], r["line"], side) in played))
    return dict(days=days, date=day, lines=sorted(lines, key=lambda x: x["chance"]))


CHANCE_BANDS = (0, 0.2, 0.4, 0.6, 0.8, 1)   # the model's chance of More, grouped for calibration
LEAN_AT = 0.542   # the model's chance for one side that counts as a lean (as on the page)
SURE_BANDS = (0.5, LEAN_AT, 0.6, 0.65, 0.7, 1)   # that chance, grouped; under LEAN_AT isn't a lean


def _by_sure(sure: pd.Series, right: pd.Series) -> list[dict]:
    """Standard lines grouped by how sure the model was of the side it favoured: how often that side
    was right, against what the model said. A model worth following is right more often the surer it is."""
    band = pd.cut(sure.clip(upper=0.999), SURE_BANDS, right=False)   # [50%, 54.2%), ..., [70%, 100%]
    return [dict(low=float(b.left), high=float(b.right), n=len(x), right=int(right[x.index].sum()),
                 model_said=float(x.mean()))
            for b, x in sure.groupby(band, observed=True)]


def _how_lines_went(lines: pd.DataFrame) -> dict:
    """Graded More-only lines of one kind: how often they went over against the model's average chance,
    overall and by the model's chance (is "said 30%" really about 30%?), and over how many nights."""
    over = lines["result"] == "over"
    band = pd.cut(lines["p_over"].clip(upper=0.999), CHANCE_BANDS, right=False)   # [0, 20%), ..., [80%, 100%]
    bands = [dict(low=float(b.left), high=float(b.right), n=len(x),
                  went_over=float(over[x.index].mean()), model_said=float(x["p_over"].mean()))
             for b, x in lines.groupby(band, observed=True)]
    return dict(n=len(lines), nights=int(lines["game_date"].nunique()), bands=bands,
                went_over=float(over.mean()) if len(lines) else None,
                model_said=float(lines["p_over"].mean()) if len(lines) else None)


def _how_picks_went(picks: pd.DataFrame) -> dict:
    """Your graded picks of one kind: how many hit, against the model's average chance when you saved them."""
    return dict(n=len(picks), hits=int((picks["result"] == "hit").sum()),
                model_expected=float(picks["model_p"].mean()) if picks["model_p"].notna().any() else None)
