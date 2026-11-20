"""NBALine web app: a local PrizePicks helper.

    python webapp.py        then open  http://127.0.0.1:5055   (or double-click NBALine.bat)

This file only defines the web routes: the page (a React app in frontend/, built into frontend/dist)
and the JSON API it talks to; the work happens in the nbaline package. Tabs and the routes behind them:
    /bestlines   paste a PrizePicks board, get the best picks      /api/board
    /check       the model's take on lines you type, live once     /api/players, /api/analyze,
                 the game starts                                   /api/lines/live
    /entries     record what you played, see its odds, follow it   /api/entries, /api/entries/odds,
                 live during the games, mark protected plays,      /api/entries/now, /api/entries/live,
                 fix an open entry's payouts and profit boost      /api/entries/<id>/protected,
                                                                   /api/entries/<id>/payouts
    /results     grade after the games, profit and model accuracy, /api/results, /api/refresh,
                 fix what an entry paid                            /api/entries/<id>/paid
    /longshots   the day's lines that hit against the model's odds  /api/long-shots
    (header)     download data + retrain, with a progress bar      /api/update
                 new code: refresh the page / restart the server   /api/version, /api/restart
The app only listens on this computer (127.0.0.1); nothing is exposed to your network.
"""
import argparse
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
from datetime import date

import pandas as pd
from flask import Flask, jsonify, redirect, request, send_from_directory

from nbaline import predictor
from nbaline.paths import PAGE, ROOT
from nbaline.pickem import board, calibration, explain, jerseys, lineup, lines, live, payouts, ranking, store
from nbaline.updater import UpdateJob

mimetypes.add_type("text/javascript", ".js")  # Windows can map .js to text/plain, which breaks JS modules
app = Flask(__name__, static_folder=None)   # the page's files are served below (page, page_assets)
update_job = UpdateJob(on_finish=lines.clear_cache)  # new data or models: forget old analyses
STARTED = time.time()


def _day(value: str | None) -> pd.Timestamp:
    return pd.Timestamp(value or date.today())


def _code_changed() -> bool:
    """True if the Python code changed after this server started (the page files are served fresh
    from disk, but Python code only reloads when the server restarts)."""
    files = list(ROOT.glob("*.py")) + list((ROOT / "nbaline").rglob("*.py"))
    return any(f.stat().st_mtime > STARTED for f in files)


def _page_version() -> float:
    """Changes whenever the page is rebuilt, so an open page can offer a refresh."""
    return max((f.stat().st_mtime for f in PAGE.rglob("*") if f.is_file()), default=0)


def _error(message: str, status: int = 400, **extra):
    return jsonify(error=message, **extra), status


# ---------------------------------------------------------------- page and app info
# The page is a React app (frontend/, built into frontend/dist). Each tab has its own address, all
# served the same page, which shows the tab the address names.
@app.get("/")
def index():
    return redirect("/bestlines")


@app.get("/<any(bestlines, check, entries, results, longshots):tab>")
def page(tab):
    return send_from_directory(PAGE, "index.html")


@app.get("/assets/<path:name>")
def page_assets(name):
    return send_from_directory(PAGE / "assets", name)


# the logo (browser tab, phone home screen) and the app manifest, from frontend/public
@app.get('/<any("favicon.ico", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "manifest.webmanifest"):name>')
def page_icons(name):
    return send_from_directory(PAGE, name, mimetype="application/manifest+json" if name.endswith(".webmanifest") else None)


@app.get("/api/meta")
def meta():
    """Everything the page needs at startup: model info, warnings, stats, payouts, entry types."""
    _, m = predictor.load_pipeline()
    warnings = predictor.stale_warnings()   # (new code waiting for a restart is shown from /api/version)
    return jsonify(
        today=str(date.today()), model=m["config"], trained_on=m["trained_on"], data_through=m["data_through"],
        warnings=warnings, stats=list(payouts.STATS), modeled=predictor.modeled_stats(),
        payouts=payouts.DEFAULT_PAYOUTS, reverted=payouts.REVERTED_PAYOUTS,
        targets={k: dict(label=label, break_even=payouts.break_even(kind, n))
                 for k, (label, kind, n) in payouts.ENTRY_TYPES.items()},
        break_even={kind: {n: payouts.break_even(kind, int(n)) for n in sizes}
                    for kind, sizes in payouts.DEFAULT_PAYOUTS.items()})


@app.get("/api/version")
def version():
    """Polled by the page: has the page changed since it was loaded (refresh it), or the Python code
    since the server started (restart it, from the page when NBALine.bat started it)?"""
    return jsonify(page=_page_version(), restart=_code_changed(), can_restart=RESTARTABLE)


# New Python code only runs once the server starts again. NBALine.bat starts it again whenever it
# stops with RESTART_CODE (and sets NBALINE_RESTARTABLE), so the page can offer "Restart now".
RESTART_CODE = 3
RESTARTABLE = os.environ.get("NBALINE_RESTARTABLE") == "1"


@app.post("/api/restart")
def restart():
    """Stop the server so NBALine.bat starts it again with the new code. Never during an update."""
    if not RESTARTABLE:
        return _error("NBALine wasn't started with NBALine.bat, so it can't restart itself. Stop it and start it again.", 409)
    if update_job.running:
        return _error("An update is running. Restart once it finishes.", 409)
    print("\nRestarting with the new code...")
    threading.Timer(0.5, os._exit, args=(RESTART_CODE,)).start()   # once this answer has reached the page
    return jsonify(restarting=True)


# ---------------------------------------------------------------- check lines
@app.get("/api/players")
def players():
    """Everyone on a team that plays on this date (for the name autocomplete)."""
    day = _day(request.args.get("date"))
    found = lines.players_on(day)
    return jsonify(date=str(day.date()), games=len(lines.games_on(day)), players=found)


@app.post("/api/analyze")
def analyze():
    body = request.get_json(force=True)
    rows = [r for r in body.get("rows", []) if r.get("player") and r.get("line") not in (None, "")]
    if not rows:
        return _error("Add at least one player and line.")
    try:
        return jsonify(results=lines.analyze_lines(rows, _day(body.get("date"))))
    except Exception as e:  # show the problem in the page instead of a blank failure
        return _error(f"{type(e).__name__}: {e}", 500)


@app.post("/api/lines/live")
def lines_live():
    """Lines from Check lines whose game has started: the player's stat so far, clock, pace."""
    body = request.get_json(force=True)
    try:
        return jsonify(live.lines_live(body.get("lines", [])))
    except Exception as e:
        return _error(f"{type(e).__name__}: {e}", 500)


# ---------------------------------------------------------------- best lines (pasted board)
@app.post("/api/board")
def rank_board():
    """Read a pasted PrizePicks board, run every line through the models, rank the best picks, and
    build the lineups to play from them (lineup.py)."""
    body = request.get_json(force=True)
    text = body.get("text", "")
    day, date_note = ranking.board_date(text, _day(body.get("date")))
    label, kind, n = payouts.ENTRY_TYPES.get(body.get("target"), payouts.ENTRY_TYPES["flex6"])
    break_even = payouts.break_even(kind, n)

    teams = lines.teams_on(day)
    if not teams:
        return _error(f"No NBA games on {day.date()}.")
    found, unread = board.parse_board(text, list(teams), teams=teams, day=board.WEEKDAYS[day.weekday()])
    if not found:
        return _error("Couldn't find any lines in that text. Copy the whole PrizePicks page (Ctrl+A, Ctrl+C) "
                      "or type one per line, like 'Stephen Curry 28.5 Points'.", unread=unread)
    store.save_board(str(day.date()), text, len(found), len(unread))
    ranking.label_line_types(found)
    try:
        results = lines.analyze_lines([dict(player=f["player"], stat=f["stat"], line=f["line"],
                                            line_type=f.get("line_type")) for f in found], day)
    except Exception as e:
        return _error(f"{type(e).__name__}: {e}", 500)
    known_teams = set(lines.box_scores()["TEAM_ABBREVIATION"].unique())
    groups = ranking.rank_board(found, results, break_even, known_teams)
    # each stat's record on lines like a lineup's (shown at the 6-pick Flex break-even or more)
    records = calibration.stat_records(payouts.break_even(*lineup.RECORD_ENTRY))
    return jsonify(target=label, break_even=break_even, parsed=len(found), unread=unread,
                   date=str(day.date()), date_note=date_note,
                   stat_records=dict(at_least=payouts.break_even(*lineup.RECORD_ENTRY), stats=records),
                   lineups=lineup.lineups(groups["ranked"], groups["more_only"], records), **groups)


# ---------------------------------------------------------------- entries
@app.get("/api/entries")
def list_entries():
    entries = store.list_entries()
    open_picks = [p for e in entries if e["status"] == "open" for p in e["picks"]]
    if open_picks:   # My entries shows each open pick's jersey number
        jerseys.add_to(open_picks)
    return jsonify(entries=entries)


@app.get("/api/entries/now")
def recheck_entries():
    """Open entries re-checked with the latest data, model and injury report (saved chances stay as they were)."""
    try:
        return jsonify(lines.recheck_open_entries(store.list_entries()))
    except Exception as e:
        return _error(f"{type(e).__name__}: {e}", 500)


@app.get("/api/entries/live")
def live_entries():
    """Open entries during the games: each pick's stat so far, won/lost/in play, what each entry can
    still pay, and how likely each amount is now (from the NBA's live box scores)."""
    try:
        return jsonify(live.open_entries_live(store.list_entries(), lines.rechecked()))
    except Exception as e:
        return _error(f"{type(e).__name__}: {e}", 500)


@app.post("/api/entries/odds")
def entry_odds():
    """Chance of winning / expected return for a draft entry (needs a model probability per pick)."""
    body = request.get_json(force=True)
    probs = body.get("probs", [])
    kind, table = body.get("kind", "power"), body.get("payouts") or payouts.DEFAULT_PAYOUTS
    n = len(probs)
    resp = dict(n=n, break_even=payouts.break_even(kind, n, table) if n else None)
    if n and all(p is not None for p in probs) and str(n) in table.get(kind, {}):
        resp.update(payouts.entry_odds(probs, kind, table))
    return jsonify(resp)


@app.post("/api/entries")
def save_entry():
    """Save an entry you played. Each pick is checked with the model first (and must be a real game)."""
    body = request.get_json(force=True)
    kind, picks = body.get("kind"), body.get("picks", [])
    stake = float(body.get("stake") or 0)
    sizes = {"power": range(2, 7), "flex": range(3, 7)}
    if kind not in sizes or len(picks) not in sizes[kind]:
        return _error(f"A {kind or '?'} entry needs {min(sizes.get(kind, [2]))}-6 picks.")
    if stake <= 0:
        return _error("Enter the amount you played.")
    day = _day(body.get("date"))
    results = lines.analyze_lines([dict(player=p["player"], stat=p["stat"], line=p["line"], line_type=p.get("line_type"))
                                   for p in picks], day)
    errors = [f"{r['player']}: {r['error']}" for r in results if r.get("error")]
    if errors:
        return _error(" | ".join(errors))
    # one player can be in an entry on different stats, but not on the same stat twice
    if len({(r["player_id"], r["stat"]) for r in results}) < len(results):
        return _error("A player can't have two lines on the same stat in one entry.")
    if len({r["team"] for r in results}) < 2:
        return _error("PrizePicks entries need players from at least 2 teams.")
    rows = []
    for pick, r in zip(picks, results):
        side = pick["side"]
        model_p = None if r.get("p_over") is None else r["p_over"] if side == "more" else 1 - r["p_over"]
        line_type = pick.get("line_type") if pick.get("line_type") in store.MORE_ONLY_TYPES else None
        rows.append(dict(r, side=side, model_p=model_p, line_type=line_type))
    try:
        table = payouts.checked(body.get("payouts") or payouts.DEFAULT_PAYOUTS)
    except ValueError as e:
        return _error(str(e))
    entry_id = store.save_entry(str(day.date()), kind, stake, rows, table, body.get("note", ""),
                                protected=bool(body.get("protected")))
    return jsonify(id=entry_id)


@app.post("/api/entries/<int:entry_id>/protected")
def protect_entry(entry_id):
    """Mark an entry as a PrizePicks protected play, or not: if it loses outright, it's left out of profit and ROI."""
    store.set_protected(entry_id, bool(request.get_json(force=True).get("protected")))
    return jsonify(ok=True)


@app.post("/api/entries/<int:entry_id>/payouts")
def set_entry_payouts(entry_id):
    """Change an open entry's payouts to what PrizePicks shows (Goblins, Demons and reverted picks change
    them) and its profit boost: {"payouts": {"flex": ..., "reverted": ..., "boost": 0.3}}."""
    try:
        store.set_payouts(entry_id, payouts.checked(request.get_json(force=True).get("payouts")))
    except ValueError as e:
        return _error(str(e))
    return jsonify(ok=True)


@app.post("/api/entries/<int:entry_id>/paid")
def set_entry_paid(entry_id):
    """What PrizePicks really paid for a graded entry (its payouts change), or null for the app's own amount."""
    paid = request.get_json(force=True).get("paid")
    if paid is not None:
        try:
            paid = float(paid)
        except (TypeError, ValueError):
            paid = -1
        if not 0 <= paid < 1_000_000:   # also catches a typo, NaN or infinity
            return _error("Type the amount PrizePicks paid, e.g. 25.50 (0 if it paid nothing).")
    try:
        store.set_paid(entry_id, paid)
    except ValueError as e:
        return _error(str(e))
    return jsonify(ok=True)


@app.delete("/api/entries/<int:entry_id>")
def delete_entry(entry_id):
    store.delete_entry(entry_id)
    return jsonify(ok=True)


# ---------------------------------------------------------------- results
@app.post("/api/refresh")
def refresh():
    """Download the latest box scores (about 30-60 seconds), then grade everything."""
    r = subprocess.run([sys.executable, "fetch_data.py"], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return _error("Download failed: " + (r.stdout + r.stderr)[-400:], 500)
    return jsonify(graded=store.grade_all())


@app.post("/api/grade")
def grade():
    return jsonify(graded=store.grade_all())


@app.get("/api/results")
def results():
    store.grade_all()
    entries = store.list_entries()
    try:
        explain.add_reasons(entries)   # why each graded pick hit or missed (only a note: Results works without it)
    except Exception as e:
        print(f"Couldn't explain the graded entries: {type(e).__name__}: {e}")
    return jsonify(summary=store.summary(), entries=entries, calibration=calibration.status())


@app.get("/api/long-shots")
def long_shots():
    """The day's lines that hit although the model gave them little chance (?date=, default: latest)."""
    store.grade_all()   # games that finished since the last look
    return jsonify(store.long_shots(request.args.get("date")))


# ---------------------------------------------------------------- one-click update
@app.post("/api/update")
def start_update():
    if not update_job.start():
        return _error("An update is already running.", 409)
    return jsonify(started=True)


@app.get("/api/update")
def update_status():
    return jsonify(update_job.status())


# ---------------------------------------------------------------- start the server
def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    port = ap.parse_args().port
    try:  # Windows lets a second server share the port silently, so check first
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        print(f"NBALine is already running at  http://127.0.0.1:{port}  (use that window, or close it first)")
        return
    except OSError:
        pass
    print(f"NBALine is running at  http://127.0.0.1:{port}   (press Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
