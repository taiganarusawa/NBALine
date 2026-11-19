"""Command line: predict over/under on player points lines, and log every prediction.

One line (opponent and home/away come from the official NBA schedule):
    python predict.py "Stephen Curry" 28.5
    python predict.py "Stephen Curry" 28.5 --out "Zion Williamson" --over-odds -108 --under-odds -112

A whole slate from a CSV (see slate_example.csv):
    python predict.py --slate slate.csv

Run fetch_data.py first on game days so the latest games are included.
If you also pass --opp / --home / --away, they're checked against the schedule.
Who's out comes from the official NBA injury report (latest one before tip-off); --out adds more.
--no-schedule skips the check (offline, or a made-up matchup); those predictions are marked in the log.
Every prediction is appended to predictions_log.csv; grade them later with score.py.
The prediction engine itself is nbaline/predictor.py (shared with the web app).
"""
import argparse
import csv
import sys
from datetime import date, datetime

import pandas as pd

from nbaline.paths import PREDICTIONS_LOG as LOG
from nbaline.predictor import analyze, warn_if_stale

EDGE_THRESHOLD = 0.03  # need 3+ percentage points over the book's implied probability to lean


def implied_prob(american: int) -> float:
    """Sportsbook odds -> implied probability, e.g. -130 -> 0.565, +110 -> 0.476."""
    return -american / (-american + 100) if american < 0 else 100 / (american + 100)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console + accented names
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("player", nargs="?")
    ap.add_argument("line", nargs="?", type=float)
    ap.add_argument("--opp", help="optional: checked against the schedule")
    ap.add_argument("--home", action="store_true", help="optional: checked against the schedule")
    ap.add_argument("--away", action="store_true", help="optional: checked against the schedule")
    ap.add_argument("--no-injury-report", action="store_true",
                    help="don't use the official injury report (guess absences from recent games)")
    ap.add_argument("--no-schedule", action="store_true",
                    help="skip the schedule (then --opp and --home/--away are required)")
    ap.add_argument("--out", nargs="*", default=[],
                    help='players OUT tonight on either team, e.g. --out "Draymond Green" "Zion Williamson"')
    ap.add_argument("--over-odds", type=int, default=-110)
    ap.add_argument("--under-odds", type=int, default=-110)
    ap.add_argument("--slate", help="CSV with columns player,line,over_odds,under_odds,out (opp,venue optional)")
    ap.add_argument("--date", help="game date YYYY-MM-DD (default: today)")
    ap.add_argument("--no-log", action="store_true", help="don't write to predictions_log.csv")
    args = ap.parse_args()

    if args.slate:
        reqs = []
        with open(args.slate, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                venue = (r.get("venue") or "").strip().lower()
                reqs.append(dict(player=r["player"], line=float(r["line"]), opp=r.get("opp") or None,
                                 home={"home": True, "away": False}.get(venue),
                                 over_odds=int(r.get("over_odds") or -110),
                                 under_odds=int(r.get("under_odds") or -110),
                                 out=[x.strip() for x in (r.get("out") or "").split(";") if x.strip()]))
    else:
        if not (args.player and args.line is not None):
            ap.error('give PLAYER LINE, e.g.  python predict.py "Stephen Curry" 28.5   (or use --slate)')
        if args.home and args.away:
            ap.error("--home and --away can't both be set")
        reqs = [dict(player=args.player, line=args.line, opp=args.opp,
                     home=True if args.home else False if args.away else None, out=args.out,
                     over_odds=args.over_odds, under_odds=args.under_odds)]

    warn_if_stale()
    game_date = pd.Timestamp(args.date or date.today())
    results = analyze(reqs, game_date, use_schedule=not args.no_schedule, use_injuries=not args.no_injury_report)
    if len(reqs) == 1 and results[0].get("error"):
        sys.exit(results[0]["error"])

    log_rows = []
    for res in results:
        if res.get("error"):
            print(f"Skipping {res['player']}: {res['error']}")
            continue
        r = res["request"]
        po, pu = res["p_over"], 1 - res["p_over"]
        io, iu = implied_prob(r["over_odds"]), implied_prob(r["under_odds"])
        fair = io / (io + iu)  # the book's probability with its margin removed
        eo, eu = po - io, pu - iu
        verdict = ("LEAN OVER" if eo >= eu else "LEAN UNDER") if max(eo, eu) >= EDGE_THRESHOLD else "NO EDGE"
        vs = "vs." if res["home"] else "@"
        when = f"{res['game_date']} {res['tip_local']}" if res["game_id"] else f"{res['game_date']} (schedule NOT checked)"
        print(f"\n{res['player']} ({res['team']}) {vs} {res['opp']}  |  {when}  |  line {res['line']}")
        print("-" * 70)
        if res["started"]:
            print(f"WARNING: this game tipped off at {res['tip_local']}. The prediction only uses games "
                  f"before today, but it is NOT a pre-game pick. Logged as pregame=0.")
        print(f"Projection     : {res['proj']:.1f} pts   (typical range {res['q10']:.0f}-{res['q90']:.0f}, "
              f"median {res['q50']:.1f})")
        print(f"OVER  {po:6.1%}   book {io:.1%} at {r['over_odds']:+d}   edge {eo:+.1%}")
        print(f"UNDER {pu:6.1%}   book {iu:.1%} at {r['under_odds']:+d}   edge {eu:+.1%}")
        print(f"Verdict        : {verdict}" + ("" if verdict != "NO EDGE" else f"  (needs {EDGE_THRESHOLD:.0%}+ edge)"))
        if res["injury_report"]:
            miss = res["injury_missing"]
            note = f" (not yet submitted: {', '.join(miss)}, guessed from recent games)" if miss else ""
            older = f" ({'; '.join(res['injury_notes'])})" if res["injury_notes"] else ""
            print(f"Injury report  : official, {res['injury_report']}{older}{note}")
        else:
            print("Injury report  : none available, absences GUESSED from recent games (check before betting)")
        if res["self_status"]:
            print(f"WARNING        : {res['player']} is {res['self_status']}")
        for label, names_out in res["outs"].items():
            print(f"OUT ({label})      : " + ", ".join(names_out))
        for w in res["questionable"]:
            print(f"Questionable   : {w}")
        if res["reasons"]:
            print("Biggest factors (pts vs. an average rotation player):")
            for pts, label, shown in res["reasons"]:
                print(f"  {pts:+5.1f}  {label} = {shown}")
        print("Last 8 games   : " + ", ".join(f"{d} {v:g}" for d, v in res["recent"]))
        log_rows.append(dict(
            logged_at=datetime.now().isoformat(timespec="seconds"), game_date=res["game_date"],
            player_id=res["player_id"], player=res["player"], team=res["team"], opp=res["opp"],
            home=int(res["home"]), line=res["line"], over_odds=r["over_odds"], under_odds=r["under_odds"],
            proj=res["proj"], q10=res["q10"], q50=res["q50"], q90=res["q90"],
            p_over=round(po, 4), book_fair_over=round(fair, 4), edge_over=round(eo, 4),
            edge_under=round(eu, 4), verdict=verdict, model=res["model"],
            game_id=res["game_id"], tipoff_utc=res["tipoff_utc"],
            pregame="" if not res["game_id"] else int(not res["started"]),
            schedule_checked=int(bool(res["game_id"])), injury_report=res["injury_report"] or ""))

    ok = [r for r in results if not r.get("error")]
    if ok:
        print(f"\nModel {ok[0]['model']} | data through {ok[0]['data_through']} | not betting advice")
    if not args.no_log and log_rows:
        new = pd.DataFrame(log_rows)
        allrows = new
        if LOG.exists():  # rewrite instead of append, so newly added columns line up with older rows
            allrows = pd.concat([pd.read_csv(LOG, dtype={"game_id": str}), new], ignore_index=True)
        allrows.to_csv(LOG, index=False)
        print(f"Logged {len(new)} prediction(s) to {LOG.name}. Grade them after the games with: python score.py")


if __name__ == "__main__":
    main()
