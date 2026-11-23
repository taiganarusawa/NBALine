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
import re
import sys
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

    Each report is parsed once and kept as a small CSV (who's listed, plus a .nys file with the games
    a team hadn't submitted for yet); the PDF itself is deleted, since the CSV holds everything we use.
    Returns (report_time, csv_path) or (None, None)."""
    at = (at or datetime.now(ET)).astimezone(ET)
    t = at.replace(minute=at.minute - at.minute % 15, second=0, microsecond=0, tzinfo=None)
    CACHE.mkdir(parents=True, exist_ok=True)
    for _ in range(max_back):
        pdf = CACHE / Path(report_url(t)).name
        csv = pdf.with_suffix(".csv")
        if csv.exists() and _parsed_current(csv):
            return t, csv
        try:  # not cached, or cached in the old format: (re)download and parse it
            r = requests.get(report_url(t), headers=HEADERS, timeout=20)
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                pdf.write_bytes(r.content)
                _store_parsed(pdf)
                pdf.unlink()
                return t, csv
        except requests.RequestException:
            pass
        if csv.exists():  # old-format copy and the PDF can't be fetched again: use what we have
            return t, csv
        t -= timedelta(minutes=15)
    return None, None


def _parsed_current(csv: Path) -> bool:
    nys = csv.with_suffix(".nys")
    return nys.exists() and nys.read_text().startswith(f"#v{NYS_FORMAT}")


NYS_FORMAT = 2   # .nys line: "game_date|matchup|TEAM" (version 1 had only "TEAM", for any game)
KEEP_DAYS = 30   # saved reports older than this are deleted (prune_cache): only recent ones are ever read
_REPORT_DAY = re.compile(r"Injury-Report_(\d{4}-\d{2}-\d{2})_")


def prune_cache(keep_days: int = KEEP_DAYS) -> int:
    """Delete saved reports from more than keep_days ago (about 100 small files a day pile up otherwise).
    Predictions read the reports of the day they're for, so only re-predicting an older date loses them:
    it then goes by who missed recent games instead. Returns how many files it deleted."""
    oldest = str(datetime.now(ET).date() - timedelta(days=keep_days))
    old = [f for f in CACHE.glob("Injury-Report_*")
           if (m := _REPORT_DAY.match(f.name)) and m.group(1) < oldest] if CACHE.exists() else []
    for f in old:
        f.unlink(missing_ok=True)
    return len(old)


def _store_parsed(pdf: Path):
    """Parse a report PDF into <name>.csv (listed players) and <name>.nys (games not yet submitted for).
    A report covers several days: a team can have submitted for tonight but not yet for tomorrow."""
    df, missing_games = parse_report(pdf)
    df.to_csv(pdf.with_suffix(".csv"), index=False)
    codes = team_codes()
    lines = {f"{day}|{matchup}|{to_code(team, codes)}" for day, matchup, team in missing_games if to_code(team, codes)}
    pdf.with_suffix(".nys").write_text("\n".join([f"#v{NYS_FORMAT}"] + sorted(lines)))


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
    submitted). An old-format copy only knows the team, so its entries read ("*", "*", team): any game."""
    t, csv = fetch_report(at)
    if csv is None:
        return None, pd.DataFrame(), set()
    df = pd.read_csv(csv, dtype=str).fillna("")
    nys = csv.with_suffix(".nys")
    missing = set()
    for line in (nys.read_text().split("\n") if nys.exists() else []):
        if line and not line.startswith("#"):
            missing.add(tuple(line.split("|")) if "|" in line else ("*", "*", line))
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
