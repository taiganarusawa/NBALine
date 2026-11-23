"""Official NBA injury report: download the PDF and turn it into a table.

The NBA posts a new report every 15 minutes at
    https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-11-09_09_45PM.pdf
(times are US Eastern). Teams must list every player who might miss a game, so a
player who is NOT on the report is expected to play.

    python injuries.py                 # latest report, all games
    python injuries.py --team GSW      # one team
    python injuries.py --at "2026-11-09 21:45"   # the report as of a given Eastern time

predict.py uses this automatically: players listed Out or Doubtful are treated as out,
Questionable/Probable players are shown as warnings.
"""
import argparse
import json
import re
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .paths import INJURY_REPORTS

ET = ZoneInfo("America/New_York")
CACHE = INJURY_REPORTS
URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{d}_{h}_{m}{ampm}.pdf"
HEADERS = {"User-Agent": "Mozilla/5.0 (NBALine personal project)"}
OUT_STATUSES = {"Out", "Doubtful"}            # treated as not playing
WATCH_STATUSES = {"Questionable", "Probable"}  # shown as warnings
# Column boundaries (x position on the page), taken from the report's header row.
COLS = [("game_date", 0), ("game_time", 115), ("matchup", 195), ("team", 260),
        ("player", 420), ("status", 580), ("reason", 660)]


# ------------------------------------------------------------------ download
def report_url(t: datetime) -> str:
    return URL.format(d=t.strftime("%Y-%m-%d"), h=t.strftime("%I"), m=t.strftime("%M"), ampm=t.strftime("%p"))


def fetch_report(at: datetime | None = None, max_back: int = 16):
    """Latest report published at or before `at` (Eastern time; default now).
    Steps back 15 minutes at a time (up to 4 hours) until a report exists.

    Each report is downloaded and parsed once, then kept in that day's JSON file (saved_reports); the
    PDF itself is deleted, since the JSON holds everything we use. The NBA takes old reports down (last
    season's are gone), so the saved ones are kept for good.
    Returns (report_time, {"players": [...], "not_submitted": [...]}) or (None, None)."""
    at = (at or datetime.now(ET)).astimezone(ET)
    t = at.replace(minute=at.minute - at.minute % 15, second=0, microsecond=0, tzinfo=None)
    CACHE.mkdir(parents=True, exist_ok=True)
    for _ in range(max_back):
        report = saved_reports(t.date()).get(f"{t:%H:%M}")
        if report is not None:
            return t, report
        try:
            r = requests.get(report_url(t), headers=HEADERS, timeout=20)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                return t, _save(t, *_parse_pdf(r.content))
        except requests.RequestException:
            pass
        t -= timedelta(minutes=15)
    return None, None


# One JSON file per day (data/injury_reports/2026-11-23.json), with every report the app read that day:
#   {"format": 1, "reports": {"17:15": {"players": [{game_date, game_time, matchup, team, player_raw,
#    player, status, reason}, ...], "not_submitted": [[game_date, matchup, team code], ...]}}}
# Times are US Eastern. "not_submitted": games a team hadn't sent its list for yet; a report covers
# several days, so a team can have submitted for tonight but not yet for tomorrow. Reports saved through
# Nov 10, 2026 only knew the team for these, so they read ["*", "*", team]: any game.
FORMAT = 1
_writing = threading.Lock()   # the web app reads reports for several requests at once


def saved_reports(day) -> dict:
    """{"HH:MM": report} for every report saved for that date (Eastern), oldest first."""
    path = CACHE / f"{day}.json"
    return json.loads(path.read_text(encoding="utf-8"))["reports"] if path.exists() else {}


def _save(t: datetime, players: pd.DataFrame, not_submitted: set) -> dict:
    """Add one parsed report to its day's file, and return it as saved."""
    report = dict(players=players.fillna("").to_dict("records"), not_submitted=sorted(map(list, not_submitted)))
    with _writing:
        reports = saved_reports(t.date())
        reports[f"{t:%H:%M}"] = report
        _write_day(CACHE / f"{t.date()}.json", reports)
    return report


def _write_day(path: Path, reports: dict):
    """A day's reports, one compact line each (a quarter smaller than indented JSON, still easy to scan).
    Written whole, then swapped in, so a reader never sees half a file."""
    lines = ",\n".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(',', ':'))}"
                       for k, v in sorted(reports.items()))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(f'{{"format": {FORMAT}, "reports": {{\n{lines}\n}}}}\n', encoding="utf-8")
    tmp.replace(path)


def _parse_pdf(content: bytes) -> tuple[pd.DataFrame, set]:
    """(listed players, {(game_date, matchup, team code)} not yet submitted) from a report's PDF."""
    with tempfile.TemporaryDirectory(prefix="nbaline-report-") as folder:
        pdf = Path(folder) / "report.pdf"
        pdf.write_bytes(content)
        df, missing_games = parse_report(pdf)
    codes = team_codes()
    return df, {(day, matchup, code) for day, matchup, team in missing_games if (code := to_code(team, codes))}


# --------------------------------------------------------------------- parse
def _col(x: float) -> str:
    name = COLS[0][0]
    for c, x0 in COLS:
        if x >= x0:
            name = c
    return name


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).replace(" - ", " - ").strip()


def parse_report(path: Path) -> tuple[pd.DataFrame, set]:
    """Returns (one row per listed player, {(game_date, matchup, team name)} not submitted yet)."""
    import pdfplumber
    rows, not_submitted = [], set()
    state = dict(game_date="", game_time="", matchup="", team="")
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=1.5, keep_blank_chars=True)
            # group words into text lines by vertical position
            lines: dict[int, dict] = {}
            for w in words:
                key = next((k for k in lines if abs(k - w["top"]) < 2.5), None)
                if key is None:
                    key = round(w["top"], 1)
                    lines[key] = {}
                c = _col(w["x0"])
                lines[key][c] = (lines[key].get(c, "") + " " + w["text"]).strip()
            page_rows, frags = [], []
            for top in sorted(lines):
                cells = lines[top]
                if "Player Name" in cells.get("player", "") or "Injury Report:" in " ".join(cells.values()):
                    continue  # header lines
                if re.match(r"Page \d+ of \d+", " ".join(cells.values())):
                    continue
                for k in ("game_date", "game_time", "matchup", "team"):
                    if cells.get(k):
                        state[k] = _clean(cells[k])
                if cells.get("player"):
                    page_rows.append(dict(state, top=top, player_raw=_clean(cells["player"]),
                                          status=_clean(cells.get("status", "")), reason=cells.get("reason", "")))
                elif "NOT YET SUBMITTED" in " ".join(cells.values()).upper():
                    not_submitted.add((state["game_date"], state["matchup"], state["team"]))
                elif cells.get("reason"):
                    frags.append((top, cells["reason"]))
            # wrapped "Reason" text belongs to the nearest player row on the page,
            # except text above the page's first row that continues the previous page's last row
            first_top = min((r["top"] for r in page_rows), default=float("inf"))
            for top, text in frags:
                if top < first_top and rows and rows[-1]["reason"].rstrip().endswith(("/", "-")):
                    rows[-1]["reason"] = _clean(rows[-1]["reason"] + " " + text)
                elif page_rows:
                    near = min(page_rows, key=lambda r: abs(r["top"] - top))
                    near.setdefault("extra", []).append((top, text))
            for r in page_rows:
                parts = sorted(r.pop("extra", []) + [(r["top"], r["reason"])])
                r["reason"] = _clean(" ".join(t for _, t in parts if t))
                r.pop("top")
            rows += page_rows
    df = pd.DataFrame(rows)
    if len(df):
        df["player"] = df["player_raw"].map(_first_last)
    return df, not_submitted


def _first_last(raw: str) -> str:
    """'Murphy III, Trey' -> 'Trey Murphy III'."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return " ".join([parts[-1]] + parts[:-1]) if len(parts) > 1 else raw


# ------------------------------------------------------------- team lookup
def team_codes() -> dict:
    """Report team name -> tricode, e.g. 'Golden State Warriors' -> 'GSW' (also 'LA Clippers')."""
    from nba_api.stats.static import teams
    out = {}
    for t in teams.get_teams():
        out[t["full_name"]] = t["abbreviation"]
        out[t["nickname"]] = t["abbreviation"]
    return out


def to_code(team_name: str, codes: dict) -> str | None:
    if team_name in codes:
        return codes[team_name]
    return next((c for name, c in codes.items() if team_name.endswith(name)), None)


def load(at: datetime | None = None):
    """(report_time, DataFrame with a TEAM code column, {(game_date, matchup, team code)} not yet
    submitted). Entries reading ("*", "*", team) are from older saved reports: any game."""
    t, report = fetch_report(at)
    if report is None:
        return None, pd.DataFrame(), set()
    df = pd.DataFrame(report["players"], dtype=str)
    missing = {tuple(x) for x in report["not_submitted"]}
    if len(df):
        codes = team_codes()
        df["TEAM"] = df["team"].map(lambda n: to_code(n, codes))
    return t, df, missing


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", help="e.g. GSW")
    ap.add_argument("--at", help='Eastern time, e.g. "2026-11-09 21:45" (default: now)')
    ap.add_argument("--all", action="store_true", help="include players listed Available")
    args = ap.parse_args()
    at = datetime.strptime(args.at, "%Y-%m-%d %H:%M").replace(tzinfo=ET) if args.at else None
    t, df, missing = load(at)
    if t is None:
        return print("No injury report found in the last 4 hours.")
    print(f"Official NBA injury report as of {t:%Y-%m-%d %I:%M %p} ET")
    if args.team:
        df = df[df["TEAM"] == args.team.upper()]
    if not args.all and len(df):
        df = df[df["status"] != "Available"]
    for (gd, mu, team), g in df.groupby(["game_date", "matchup", "TEAM"], sort=False):
        print(f"\n{gd}  {mu}  {team}")
        for r in g.itertuples():
            print(f"  {r.status:<12} {r.player:<26} {r.reason}")
    if missing:
        print("\nNot yet submitted: " + ", ".join(f"{team} ({matchup} {day})" if day != "*" else team
                                                   for day, matchup, team in sorted(missing)))


if __name__ == "__main__":
    main()
